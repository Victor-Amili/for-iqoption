# import asyncio
# import pandas as pd
# from pocketoptionapi_async import AsyncPocketOptionClient

# # Your active WebSocket auth string from DevTools
# SSID_PAYLOAD = '42["auth",{"session": "itd3dnrfo38am7lbldeqklppph", "isDemo": 1, "uid": 131006989, "platform": 2, "isFastHistory": true}]'

# async def evaluate_strategy(client, asset):
#     print(f"Fetching recent candles for {asset}...")
    
#     # Fetch 1-minute or 5-minute candles (timeframe in seconds: 60 = 1 min, 300 = 5 min)
#     df = await client.get_candles_dataframe(asset=asset, timeframe=60)
    
#     if df is None or df.empty:
#         print("Could not fetch candle data.")
#         return

#     # Look at the latest closed candle
#     last_candle = df.iloc[-1]
#     prev_candle = df.iloc[-2]
    
#     print(f"Latest Close Price: {last_candle['close']} | Previous Close: {prev_candle['close']}")
    
#     # --- YOUR STRATEGY LOGIC GOES HERE ---
#     # Example: Simple green/red candle check or streak check
#     is_green_last = last_candle['close'] > last_candle['open']
#     is_green_prev = prev_candle['close'] > prev_candle['open']
    
#     print(f"Candle Status -> Previous Green: {is_green_prev}, Current Green: {is_green_last}")
    
#     # Example condition: If you want to test placing a demo trade
#     # action = "call" if is_green_last else "put"
#     # amount = 10 # $10 demo stake
#     # 
#     # print(f"Placing a {action.upper()} trade of ${amount} on {asset}...")
#     # success, order_id = await client.buy(asset=asset, amount=amount, action=action, timeframe=60)
#     # print(f"Order Result: Success={success}, ID={order_id}")

# async def main():
#     print("Connecting to Pocket Option Demo...")
#     client = AsyncPocketOptionClient(SSID_PAYLOAD, is_demo=True, enable_logging=False)
    
#     try:
#         await client.connect()
#         print("Connected successfully!\n")
        
#         # Check balance first
#         balance = await client.get_balance()
#         print(f"Demo Balance: ${balance.balance} {balance.currency}\n")
        
#         # Run evaluation on EURUSD OTC
#         await evaluate_strategy(client, asset='EURUSD_otc')
        
#     except Exception as exc:
#         print(f"An error occurred: {exc}")
        
#     finally:
#         await client.disconnect()
#         print("\nDisconnected safely.")

# if __name__ == "__main__":
#     asyncio.run(main())

import asyncio
import pandas as pd
from datetime import datetime
from pocketoptionapi_async import AsyncPocketOptionClient

# Active WebSocket auth string
SSID_PAYLOAD = '42["auth",{"session": "itd3dnrfo38am7lbldeqklppph", "isDemo": 1, "uid": 131006989, "platform": 2, "isFastHistory": true}]'

# Strategy Settings
STREAK_COUNT = 7      # Number of consecutive candles needed
TRADE_AMOUNT = 1      # Demo stake in USD
EXPIRATION_TIME = 60  # Trade duration in seconds (1 min)
ASSET = 'EURUSD_otc'

def check_candle_streak(df):
    """
    Checks the last 'N' closed candles in the dataframe for consecutive green or red streaks.
    """
    closed_candles = df.iloc[-STREAK_COUNT-1:-1]
    
    is_green = lambda row: row['close'] > row['open']
    is_red = lambda row: row['close'] < row['open']
    
    if all(is_green(row) for _, row in closed_candles.iterrows()):
        return "call"  # All consecutive candles are green
    elif all(is_red(row) for _, row in closed_candles.iterrows()):
        return "put"   # All consecutive candles are red
    
    return None

async def run_streak_strategy(client, asset):
    current_time = datetime.now().strftime('%H:%M:%S')
    print(f"[{current_time}] Checking {asset} for a {STREAK_COUNT}-Candle Streak...")
    
    df = await client.get_candles_dataframe(asset=asset, timeframe=60)
    
    if df is None or len(df) < STREAK_COUNT + 1:
        print("Insufficient candle data retrieved.")
        return

    signal = check_candle_streak(df)
    
    if signal:
        print(f"🔥 STREAK DETECTED: {STREAK_COUNT} consecutive {'GREEN' if signal == 'call' else 'RED'} candles!")
        print(f"Placing ${TRADE_AMOUNT} {signal.upper()} trade on {asset}...")
        
        result = await client.place_order(
            asset=asset, 
            amount=TRADE_AMOUNT, 
            direction=signal,  # 'call' or 'put'
            duration=EXPIRATION_TIME
        )
        print(f"Trade Execution Result -> {result}")
    else:
        print(f"No {STREAK_COUNT}-candle streak found. Waiting for next check...")

async def main():
    while True: # Outer loop for auto-reconnection
        print("\nConnecting to Pocket Option Demo...")
        client = AsyncPocketOptionClient(SSID_PAYLOAD, is_demo=True, enable_logging=False)
        
        try:
            await client.connect()
            balance = await client.get_balance()
            print(f"Connected | Demo Balance: ${balance.balance} {balance.currency}\n")
            
            # Inner strategy loop
            while True:
                await run_streak_strategy(client, asset=ASSET)
                print("-" * 40)
                await asyncio.sleep(60)
                
        except Exception as exc:
            print(f"Connection lost or error occurred: {exc}")
            print("Attempting to reconnect in 10 seconds...")
            try:
                await client.disconnect()
                print("\nDisconnected safely.")
            except:
                pass
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())