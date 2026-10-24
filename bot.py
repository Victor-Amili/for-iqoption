import asyncio
import pandas as pd
from datetime import datetime
from pocketoptionapi_async import AsyncPocketOptionClient

# Configuration
SSID_PAYLOAD = '42["auth",{"session": "itd3dnrfo38am7lbldeqklppph", "isDemo": 1, "uid": 131006989, "platform": 2, "isFastHistory": true}]'
ASSET = 'EURUSD_otc'
STAKE = 40.0            # $40.00 demo stake
EXPIRATION_TIME = 60    # 1-minute expiration

# Strategy Parameters (Matching our winning backtester)
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 50

def calculate_indicators(df):
    df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    df['ema_trend'] = df['close'].ewm(span=EMA_TREND, adjust=False).mean()
    return df

async def run_bot_session(client, asset):
    df = await client.get_candles_dataframe(asset=asset, timeframe=60)
    
    if df is None or len(df) < EMA_TREND + 2:
        print("Insufficient candle data retrieved.")
        return

    df = calculate_indicators(df)
    
    # Evaluate using the most recently closed candles (-3 and -2)
    prev_row = df.iloc[-3]
    current_row = df.iloc[-2]
    
    # Crossover Logic
    fast_above_slow_now = current_row['ema_fast'] > current_row['ema_slow']
    fast_above_slow_prev = prev_row['ema_fast'] > prev_row['ema_slow']
    
    bullish_cross = not fast_above_slow_prev and fast_above_slow_now
    bearish_cross = fast_above_slow_prev and not fast_above_slow_now
    
    # Macro Trend Filter
    above_macro_trend = current_row['close'] > current_row['ema_trend']
    below_macro_trend = current_row['close'] < current_row['ema_trend']
    
    signal = None
    if bullish_cross and above_macro_trend:
        signal = "call"
    elif bearish_cross and below_macro_trend:
        signal = "put"
        
    current_time = datetime.now().strftime('%H:%M:%S')
    if signal:
        print(f"\n[{current_time}] 🚀 SIGNAL DETECTED: {signal.upper()} on {asset}!")
        print(f"Placing ${STAKE} {signal.upper()} trade...")
        
        # Correct order method signature from your working reference snippet
        result = await client.place_order(
            asset=asset, 
            amount=STAKE, 
            direction=signal,  # 'call' or 'put'
            duration=EXPIRATION_TIME
        )
        print(f"Trade Execution Result -> {result}\n")
    else:
        print(f"[{current_time}] Price: {current_row['close']:.5f} | Scanning for valid EMA trend crossover...")

async def main():
    while True:  # Robust outer reconnection loop
        print("\nConnecting to Pocket Option Demo...")
        client = AsyncPocketOptionClient(SSID_PAYLOAD, is_demo=True, enable_logging=False)
        
        try:
            await client.connect()
            balance = await client.get_balance()
            print(f"Connected successfully | Demo Balance: ${balance.balance} {balance.currency}\n")
            
            # Inner scanning loop
            while True:
                await run_bot_session(client, asset=ASSET)
                print("-" * 50)
                await asyncio.sleep(30)  # Check every 30 seconds
                
        except Exception as exc:
            print(f"Connection lost or error occurred: {exc}")
            print("Attempting to reconnect in 10 seconds...")
            try:
                await client.disconnect()
            except:
                pass
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())