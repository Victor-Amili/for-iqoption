# # import asyncio
# # from pocketoptionapi_async import AsyncPocketOptionClient

# # # Paste your full 42["auth", ...] string inside the quotes below:
# # SSID_PAYLOAD = '42["auth",{"session":"itd3dnrfo38am7lbldeqklppph","isDemo":1,"uid":131006989,"platform":2,"isFastHistory":true,"isOptimized":true}]'

# # async def main():
# #     print("Connecting to Pocket Option Demo using WebSocket Auth Payload...")
    
# #     # Initialize using the full WebSocket auth payload
# #     client = AsyncPocketOptionClient(SSID_PAYLOAD, is_demo=True, enable_logging=True)
    
# #     try:
# #         await client.connect()
# #         print(" Connected successfully!")
        
# #         # 1. Fetch Demo Balance
# #         balance = await client.get_balance()
# #         print(f" Demo Balance: ${balance.balance} {balance.currency}")
        
# #         # 2. Fetch Latest 5-Minute Candles for EURUSD_otc
# #         print(" Fetching 5-minute candles for EURUSD_otc...")
# #         candles_df = await client.get_candles_dataframe(asset='EURUSD_otc', timeframe=300)
# #         print("\nRecent Candles:")
# #         print(candles_df.tail())
        
# #     except Exception as exc:
# #         print(f" Error: {exc}")
        
# #     finally:
# #         await client.disconnect()
# #         print(" Disconnected safely.")

# # if __name__ == "__main__":
# #     asyncio.run(main())

# import asyncio
# from pocketoptionapi_async import AsyncPocketOptionClient

# SSID_PAYLOAD = '42["auth",{"session": "itd3dnrfo38am7lbldeqklppph", "isDemo": 1, "uid": 131006989, "platform": 2, "isFastHistory": true}]'

# async def main():
#     client = AsyncPocketOptionClient(SSID_PAYLOAD, is_demo=True, enable_logging=False)
#     await client.connect()
    
#     # Print all methods/attributes containing order, trade, or buy
#     methods = [m for m in dir(client) if any(k in m.lower() for k in ['order', 'trade', 'buy', 'sell'])]
#     print("Available trade/order methods:", methods)
    
#     await client.disconnect()

# asyncio.run(main())

import asyncio
import inspect
from pocketoptionapi_async import AsyncPocketOptionClient

SSID_PAYLOAD = '42["auth",{"session": "itd3dnrfo38am7lbldeqklppph", "isDemo": 1, "uid": 131006989, "platform": 2, "isFastHistory": true}]'

async def main():
    client = AsyncPocketOptionClient(SSID_PAYLOAD, is_demo=True, enable_logging=False)
    sig = inspect.signature(client.place_order)
    print("place_order signature:", sig)

asyncio.run(main())