import sqlite3
import pandas as pd
import numpy as np

DB_NAME = 'market_data.db'
ASSET = 'EURUSD_otc'

# Strategy Parameters
EMA_FAST = 9
EMA_SLOW = 21
EMA_5M_PERIOD = 20     # 5-Minute Trend Filter Period
PAYOUT_RATE = 0.92     
STAKE = 1.0

def load_data_from_db():
    conn = sqlite3.connect(DB_NAME)
    query = "SELECT time, open, high, low, close FROM candles WHERE asset = ? ORDER BY time ASC"
    df = pd.read_sql_query(query, conn, params=(ASSET,))
    conn.close()
    
    df['datetime'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('datetime', inplace=True)
    return df

def add_multitimeframe_indicators(df):
    # 1. Calculate 1-Minute Triggers (EMA Crossover)
    df['ema_fast_1m'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['ema_slow_1m'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    
    # 2. Aggregate 1-Minute candles into 5-Minute candles
    df_5m = df.resample('5min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()
    
    # Calculate 5-Minute Trend Indicator
    df_5m['ema_5m'] = df_5m['close'].ewm(span=EMA_5M_PERIOD, adjust=False).mean()
    df_5m['bullish_5m'] = df_5m['close'] > df_5m['ema_5m']
    df_5m['bearish_5m'] = df_5m['close'] < df_5m['ema_5m']
    
    # SHIFT by 1 to prevent lookahead bias (ensures 1m trades only look at CLOSED 5m candles)
    df_5m['locked_bullish_5m'] = df_5m['bullish_5m'].shift(1)
    df_5m['locked_bearish_5m'] = df_5m['bearish_5m'].shift(1)
    
    # Map 5-minute states back to the 1-minute dataframe
    df['5m_block'] = df.index.floor('5min')
    df = df.merge(df_5m[['locked_bullish_5m', 'locked_bearish_5m']], left_on='5m_block', right_index=True, how='left')
    
    return df

def run_backtest():
    df = load_data_from_db()
    if len(df) < 100:
        print(f"Not enough data in database yet. Current rows: {len(df)}")
        return

    print(f"Loaded {len(df)} candles from SQLite. Running Multi-Timeframe (1M + 5M) backtest...\n")
    df = add_multitimeframe_indicators(df)
    
    wins = 0
    losses = 0
    total_profit = 0.0
    trades_executed = 0

    start_index = 50 # Warmup buffer
    
    for i in range(start_index, len(df) - 1):
        prev_row = df.iloc[i - 1]
        current_row = df.iloc[i]
        next_row = df.iloc[i + 1]
        
        # Skip if 5-minute data hasn't locked in yet
        if pd.isna(current_row['locked_bullish_5m']):
            continue
            
        # 1-Minute Trigger: EMA Crossover
        fast_above_slow_now = current_row['ema_fast_1m'] > current_row['ema_slow_1m']
        fast_above_slow_prev = prev_row['ema_fast_1m'] > prev_row['ema_slow_1m']
        
        bullish_cross_1m = not fast_above_slow_prev and fast_above_slow_now
        bearish_cross_1m = fast_above_slow_prev and not fast_above_slow_now
        
        # 5-Minute Higher Timeframe Confirmation Filter
        confirm_bullish_5m = current_row['locked_bullish_5m']
        confirm_bearish_5m = current_row['locked_bearish_5m']
        
        signal = None
        
        # MTF Confluence Rule: 1M Crossover MUST align with 5M Trend Direction
        if bullish_cross_1m and confirm_bullish_5m:
            signal = "call"
        elif bearish_cross_1m and confirm_bearish_5m:
            signal = "put"
            
        if signal:
            trades_executed += 1
            next_is_green = next_row['close'] > next_row['open']
            next_is_red = next_row['close'] < next_row['open']
            
            if (signal == "call" and next_is_green) or (signal == "put" and next_is_red):
                wins += 1
                total_profit += (STAKE * PAYOUT_RATE)
            else:
                losses += 1
                total_profit -= STAKE

    print("=" * 55)
    print("    MULTI-TIMEFRAME (1M + 5M) BACKTEST REPORT       ")
    print("=" * 55)
    print(f"Asset Evaluated       : {ASSET}")
    print(f"Total Candles Scanned : {len(df)}")
    print(f"Total Trades Triggered: {trades_executed}")
    if trades_executed > 0:
        win_rate = (wins / trades_executed) * 100
        print(f"Winning Trades        : {wins}")
        print(f"Losing Trades         : {losses}")
        print(f"Win Rate              : {win_rate:.2f}%")
        print(f"Net Profit / Loss     : ${total_profit:.2f}")
        breakeven_needed = (1 / (1 + PAYOUT_RATE)) * 100
        print(f"Breakeven Win Rate    : {breakeven_needed:.2f}%")
        if win_rate > breakeven_needed:
            print("Status                : 🟢 PROFITABLE EDGE")
        else:
            print("Status                : 🔴 UNPROFITABLE")
    else:
        print("Status                : No trades triggered with MTF filters.")
    print("=" * 55)

if __name__ == "__main__":
    run_backtest()