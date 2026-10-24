import sqlite3
import pandas as pd
import numpy as np

DB_NAME = 'market_data.db'
ASSET = 'EURUSD_otc'

# Trend-Following Parameters
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 50
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

def calculate_indicators(df):
    # Trend-Following Moving Averages
    df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    df['ema_trend'] = df['close'].ewm(span=EMA_TREND, adjust=False).mean()
    return df

def run_backtest():
    df = load_data_from_db()
    if len(df) < EMA_TREND + 2:
        print(f"Not enough data in database yet. Current rows: {len(df)}")
        return

    print(f"Loaded {len(df)} candles from SQLite. Running Trend-Following backtest...\n")
    df = calculate_indicators(df)
    
    wins = 0
    losses = 0
    total_profit = 0.0
    trades_executed = 0

    start_index = EMA_TREND
    
    for i in range(start_index, len(df) - 1):
        prev_row = df.iloc[i - 1]
        current_row = df.iloc[i]
        next_row = df.iloc[i + 1]
        
        # Check EMA Crossover
        fast_above_slow_now = current_row['ema_fast'] > current_row['ema_slow']
        fast_above_slow_prev = prev_row['ema_fast'] > prev_row['ema_slow']
        
        bullish_cross = not fast_above_slow_prev and fast_above_slow_now
        bearish_cross = fast_above_slow_prev and not fast_above_slow_now
        
        # Macro Trend Filter
        above_macro_trend = current_row['close'] > current_row['ema_trend']
        below_macro_trend = current_row['close'] < current_row['ema_trend']
        
        signal = None
        
        # Trend-Following Rules
        if bullish_cross and above_macro_trend:
            signal = "call"
        elif bearish_cross and below_macro_trend:
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
    print("      EMA TREND-FOLLOWING BACKTEST REPORT          ")
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
            print("Status                : 🔴 UNPROFITABLE (Needs tuning)")
    else:
        print("Status                : No trades triggered with current filters.")
    print("=" * 55)

if __name__ == "__main__":
    run_backtest()