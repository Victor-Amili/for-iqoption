# from iqoptionapi.stable_api import IQ_Option
# import time

# # Use your practice account credentials for testing
# email = 
# password = 

# print("Connecting to IQ Option...")
# API = IQ_Option(email, password)
# check, reason = API.connect()

# if check:
#     print("Successfully connected!")
#     # Switch to practice mode explicitly
#     API.change_balance("PRACTICE")
#     balance = API.get_balance()
#     print(f"Current Practice Balance: {balance}")
# else:
#     print(f"Connection failed: {reason}")

import os
from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option
import time

# import logging
# # Enable detailed logging to see server rejection reasons
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(message)s')

# Load secure environment variables
load_dotenv()

email = os.getenv("OWNER_EMAIL")
password = os.getenv("OWNER_PASSWORD")

# Initialize and connect
API = IQ_Option(email, password)
API.connect()

if API.check_connect():
    print("Connected successfully using secure environment variables.")
    
    # Force practice account mode for safety
    API.change_balance("PRACTICE")
    print(f"Current Practice Balance: ${API.get_balance():.2f}")

    # Trade parameters (using binary option API method to avoid digital spot hanging)
    asset = "EURUSD-OTC"
    amount = 50        
    action = "call"    # "call" means go up / higher
    duration = 1       # 1 minute expiration

    print(f"Placing a ${amount} '{action.upper()}' binary order on {asset} for {duration} minute...")

    # Execute standard binary trade
    check, order_id = API.buy(amount, asset, action, duration)

    if check:
        print(f"Order successfully placed! Order ID: {order_id}")
        
        # Get balance before trade completion
        balance_before = API.get_balance()
        print(f"Balance before trade: ${balance_before:.2f}")

        # Wait for the option duration (60 seconds for 1 min + 5s buffer for settlement)
        wait_time = (duration * 60) + 5
        print(f"Waiting {wait_time} seconds for trade expiration...")
        time.sleep(wait_time)

        # Check balance after trade
        balance_after = API.get_balance()
        diff = balance_after - balance_before
        
        print(f"Current Balance: ${balance_after:.2f}")
        if diff > 0:
            print(f"Trade likely Won! Estimated Profit: ${diff:.2f}")
        elif diff < 0:
            print(f"Trade likely Lost. P/L: ${diff:.2f}")
        else:
            print("Trade resulted in a tie (Refund).")
    else:
        print("Order execution failed.")
else:
    print("Authentication or connection failed. Check your .env credentials.")