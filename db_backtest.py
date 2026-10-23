import sqlite3
import pandas as pd
import numpy as np

DB_NAME = 'market_data.db'
ASSET = 'EURUSD_otc'

# Bollinger Band Strategy Parameters
BB_PERIOD = 20         # Moving average period
BB_STD = 2.0           # Standard deviation multiplier
PAYOUT_RATE = 0.92     # 92% payout
STAKE = 1.0

def load_data_from_db():
    conn = sqlite3.connect(DB_NAME)
    query = "SELECT time, open, high, low, close FROM candles WHERE asset = ? ORDER BY time ASC"
    df = pd.read_sql_query(query, conn, params=(ASSET,))
    conn.close()
    
    df['datetime'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('datetime', inplace=True)
    return df

def calculate_bollinger_bands(df):
    """Calculates Bollinger Bands and checks for extreme breakouts."""
    # Middle Band (Simple Moving Average)
    df['sma'] = df['close'].rolling(window=BB_PERIOD).mean()
    
    # Standard Deviation
    df['std'] = df['close'].rolling(window=BB_PERIOD).std()
    
    # Upper and Lower Bands
    df['upper_band'] = df['sma'] + (df['std'] * BB_STD)
    df['lower_band'] = df['sma'] - (df['std'] * BB_STD)
    
    return df

def run_backtest():
    df = load_data_from_db()
    if len(df) < BB_PERIOD + 2:
        print(f"Not enough data in database yet. Current rows: {len(df)}")
        return

    print(f"Loaded {len(df)} candles from SQLite database. Running Bollinger Band Mean Reversion backtest...\n")
    df = calculate_bollinger_bands(df)
    
    wins = 0
    losses = 0
    total_profit = 0.0
    trades_executed = 0

    # Start after the BB warmup period
    start_index = BB_PERIOD
    
    for i in range(start_index, len(df) - 1):
        current_row = df.iloc[i]
        next_row = df.iloc[i + 1]
        
        close_price = current_row['close']
        upper = current_row['upper_band']
        lower = current_row['lower_band']
        
        signal = None
        
        # Mean Reversion Trigger:
        # If price closes ABOVE the upper band, fade it with a PUT (expecting drop back inside)
        if close_price > upper:
            signal = "put"
        # If price closes BELOW the lower band, fade it with a CALL (expecting bounce back inside)
        elif close_price < lower:
            signal = "call"
            
        if signal:
            trades_executed += 1
            next_is_green = next_row['close'] > next_row['open']
            next_is_red = next_row['close'] < next_row['open']
            
            # Evaluate 1-minute expiration outcome
            if (signal == "call" and next_is_green) or (signal == "put" and next_is_red):
                wins += 1
                total_profit += (STAKE * PAYOUT_RATE)
            else:
                losses += 1
                total_profit -= STAKE

    # Print Results Report
    print("=" * 50)
    print("   BOLLINGER BAND MEAN REVERSION BACKTEST REPORT   ")
    print("=" * 50)
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
        print("Status                : No trades triggered with current band settings.")
    print("=" * 50)

if __name__ == "__main__":
    run_backtest()