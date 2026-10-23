import asyncio
import pandas as pd
from pocketoptionapi_async import AsyncPocketOptionClient

# Active WebSocket auth string
SSID_PAYLOAD = '42["auth",{"session": "itd3dnrfo38am7lbldeqklppph", "isDemo": 1, "uid": 131006989, "platform": 2, "isFastHistory": true}]'

# Strategy Parameters
ASSET = 'EURUSD_otc'
STREAK_COUNT = 3       # Consecutive candles required
EMA_FAST = 20          # Fast trend filter
EMA_SLOW = 50          # Slow trend filter
RSI_PERIOD = 14        # Momentum filter
PAYOUT_RATE = 0.92     # 92% payout on wins ($1 stake returns $0.92 profit)
STAKE = 1.0            # $1 per trade

def calculate_indicators(df):
    """Calculates EMA and RSI indicators on the dataframe."""
    # Trend: Exponential Moving Averages
    df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    
    # Momentum: Relative Strength Index (RSI)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=RSI_PERIOD).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Candle color classification
    df['is_green'] = df['close'] > df['open']
    df['is_red'] = df['close'] < df['open']
    
    return df

async def run_backtest():
    print(f"Connecting to fetch historical data for {ASSET}...")
    client = AsyncPocketOptionClient(SSID_PAYLOAD, is_demo=True, enable_logging=False)
    
    try:
        await client.connect()
        # Fetch maximum available historical 1-minute candles (e.g., 1000 candles)
        df = await client.get_candles_dataframe(asset=ASSET, timeframe=60)
        await client.disconnect()
        
        if df is None or len(df) < EMA_SLOW + STREAK_COUNT:
            print("Not enough historical data retrieved for backtesting.")
            return

        print(f"Fetched {len(df)} candles. Running backtest simulation...\n")
        df = calculate_indicators(df)
        
        wins = 0
        losses = 0
        total_profit = 0.0
        trades_executed = 0

        # Loop through historical candles (skipping the warmup period for indicators)
        start_index = max(EMA_SLOW, STREAK_COUNT + 1)
        
        for i in range(start_index, len(df) - 1):
            # Look at the window of closed candles up to index i
            window = df.iloc[i - STREAK_COUNT : i]
            current_row = df.iloc[i]
            next_row = df.iloc[i + 1]  # The trade expiration candle
            
            # Check 1: Streak condition
            all_green = all(window['is_green'])
            all_red = all(window['is_red'])
            
            if not all_green and not all_red:
                continue
                
            # Check 2: Trend Filter (EMA Confluence)
            trend_bullish = current_row['ema_fast'] > current_row['ema_slow']
            trend_bearish = current_row['ema_fast'] < current_row['ema_slow']
            
            # Check 3: RSI Filter (Avoid overbought/oversold extremes)
            rsi_ok_call = current_row['rsi'] < 70
            rsi_ok_put = current_row['rsi'] > 30
            
            signal = None
            if all_green and trend_bullish and rsi_ok_call:
                signal = "call"
            elif all_red and trend_bearish and rsi_ok_put:
                signal = "put"
                
            if signal:
                trades_executed += 1
                # Simulate outcome on the NEXT candle (1-minute binary expiration)
                next_is_green = next_row['close'] > next_row['open']
                next_is_red = next_row['close'] < next_row['open']
                
                if (signal == "call" and next_is_green) or (signal == "put" and next_is_red):
                    wins += 1
                    total_profit += (STAKE * PAYOUT_RATE)
                else:
                    losses += 1
                    total_profit -= STAKE

        # Print Backtest Results Report
        print("=" * 45)
        print("       STRATEGY BACKTEST RESULTS REPORT       ")
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
            print("Status                : No trades triggered with current strict filters.")
        print("=" * 45)

    except Exception as exc:
        print(f"Backtest error: {exc}")

if __name__ == "__main__":
    asyncio.run(run_backtest())