import os
import sys
import time
import logging
from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option
import pandas as pd
import numpy as np

load_dotenv()

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")

# Strict Risk Parameters
TRADE_STAKE = 1.0  # Broker absolute minimum
TIMEFRAME_SEC = 300  # 5-Minute Charts
EXPIRATION_MIN = 5  # 5-Minute Expiration contract

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "EURGBP"]

if not OWNER_EMAIL or not OWNER_PASSWORD:
    print("ERROR: Authentication credentials missing from .env")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("LIVE-BOT")

logger.info("Initializing connection to IQ Option...")
API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
check, reason = API.connect()
if not check:
    logger.error(f"Authentication failed: {reason}")
    sys.exit(1)

# Set to practice account for safety verification
API.change_balance("PRACTICE") 
logger.info("Connected successfully. Mode set to PRACTICE balance.")

def check_market_setup(pair):
    try:
        # Fetch recent historical dataset to warm up rolling calculations
        candles = API.get_candles(pair, TIMEFRAME_SEC, 40, time.time())
        if not candles or len(candles) < 30:
            return
            
        df = pd.DataFrame(candles)
        df = df.rename(columns={'min': 'low', 'max': 'high'})
        for col in ['open', 'close', 'high', 'low']:
            df[col] = df[col].astype(float)
            
        df['body_size'] = (df['close'] - df['open']).abs()
        df['avg_body'] = df['body_size'].rolling(window=20).mean()
        df['is_green'] = df['close'] > df['open']
        df['is_red'] = df['close'] < df['open']
        
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift(1)).abs()
        tr3 = (df['low'] - df['close'].shift(1)).abs()
        df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr14'] = df['tr'].rolling(window=14).mean()
        
        # Isolate the live processing candle parameters
        live_idx = len(df) - 1
        row = df.iloc[live_idx]
        
        # Verify identical directional runs across the 4 trailing structures
        green_4 = all(df.iloc[live_idx - j]['is_green'] for j in range(4))
        red_4 = all(df.iloc[live_idx - j]['is_red'] for j in range(4))
        
        if pd.isna(row['avg_body']) or pd.isna(row['atr14']) or row['body_size'] == 0:
            return

        # --- VALIDATED STRATEGY 56.66% ENGINE CONDITION MAP ---
        if row['body_size'] >= (1.6 * row['avg_body']) and row['tr'] > row['atr14']:
            if green_4:
                logger.info(f"🚨 Setup detected: Placing $1 PUT on {pair}")
                id_status, order_id = API.buy(TRADE_STAKE, pair, "put", EXPIRATION_MIN)
                if id_status: logger.info(f"✅ PUT Execution Successful. ID: {order_id}")
                time.sleep(10)  # Intercept double order execution blocks
            elif red_4:
                logger.info(f"🚨 Setup detected: Placing $1 CALL on {pair}")
                id_status, order_id = API.buy(TRADE_STAKE, pair, "call", EXPIRATION_MIN)
                if id_status: logger.info(f"✅ CALL Execution Successful. ID: {order_id}")
                time.sleep(10)
    except Exception as err:
        logger.error(f"Error handling live data slice for {pair}: {err}")

if __name__ == "__main__":
    logger.info("Live Monitoring Engine Active. Scanning asset rails...")
    while True:
        for target_pair in PAIRS:
            check_market_setup(target_pair)
            time.sleep(2)  # Control API rate requests smoothly
        time.sleep(10)
