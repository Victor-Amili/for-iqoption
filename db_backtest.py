import sqlite3
import pandas as pd

DB_NAME = 'market_data.db'
ASSET = 'EURUSD_otc'
STREAK_COUNT = 3
EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
PAYOUT_RATE = 0.92
STAKE = 1.0

def load_data_from_db():
    conn = sqlite3.connect(DB_NAME)
    query = "SELECT time, open, high, low, close FROM candles WHERE asset = ? ORDER BY time ASC"
    df = pd.read_sql_query(query, conn, params=(ASSET,))
    conn.close()
    
    # Convert timestamp back to datetime index
    df['datetime'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('datetime', inplace=True)
    return df

def calculate_indicators(df):
    df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    df['is_green'] = df['close'] > df['open']
    df['is_red'] = df['close'] < df['open']
    return df

def run_backtest():
    df = load_data_from_db()
    if len(df) < EMA_SLOW + STREAK_COUNT:
        print(f"Not enough data in database yet. Current rows: {len(df)}")
        return

    print(f"Loaded {len(df)} candles from SQLite database. Running backtest...\n")
    df = calculate_indicators(df)
    
    wins = 0
    losses = 0
    total_profit = 0.0
    trades_executed = 0

    start_index = max(EMA_SLOW, STREAK_COUNT + 1)
    
    for i in range(start_index, len(df) - 1):
        window = df.iloc[i - STREAK_COUNT : i]
        current_row = df.iloc[i]
        next_row = df.iloc[i + 1]
        
        all_green = all(window['is_green'])
        all_red = all(window['is_red'])
        
        if not all_green and not all_red:
            continue
            
        trend_bullish = current_row['ema_fast'] > current_row['ema_slow']
        trend_bearish = current_row['ema_fast'] < current_row['ema_slow']
        
        rsi_ok_call = current_row['rsi'] < 70
        rsi_ok_put = current_row['rsi'] > 30
        
        signal = None
        if all_green and trend_bullish and rsi_ok_call:
            signal = "call"
        elif all_red and trend_bearish and rsi_ok_put:
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

    print("=" * 45)
    print("       DATABASE BACKTEST RESULTS REPORT       ")
    print("=" * 45)
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
            print("Status                : 🔴 UNPROFITABLE (Needs tuning)")
    else:
        print("Status                : No trades triggered with current filters.")
    print("=" * 45)

if __name__ == "__main__":
    run_backtest()