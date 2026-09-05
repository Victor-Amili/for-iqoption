from iqoptionapi.stable_api import IQ_Option
import time

# Use your practice account credentials for testing
email = "your_email@example.com"
password = "your_password"

print("Connecting to IQ Option...")
API = IQ_Option(email, password)
check, reason = API.connect()

if check:
    print("Successfully connected!")
    # Switch to practice mode explicitly
    API.change_balance("PRACTICE")
    balance = API.get_balance()
    print(f"Current Practice Balance: {balance}")
else:
    print(f"Connection failed: {reason}")