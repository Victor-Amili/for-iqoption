import os
import sys
import time
import logging
import requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option

load_dotenv()

EMAIL = os.getenv("OWNER_EMAIL")
PASSWORD = os.getenv("OWNER_PASSWORD")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ASSET = "EURUSD-OTC"
TIMEFRAME = 3600  # 1 hour in seconds
STAKE = 10.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("PULLBACK-BOT")

def send_telegram_alert(message):
    """Sends notifications directly to your Telegram chat."""
    if not TG_TOKEN or not TG_CHAT_ID:
        logger.warning("Telegram credentials missing in .env. Skipping alert.")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        response = requests.post(url, json=payload, timeout=10)
        if not response.ok:
            logger.error("Failed to send Telegram message: %s", response.text)
    except Exception as e:
        logger.error("Telegram error: %s", e)

def run_pullback_bot():
    api = IQ_Option(EMAIL, PASSWORD)
    check, reason = api.connect()
    if not check:
        err_msg = f"❌ Connection failed: {reason}"
        logger.error(err_msg)
        send_telegram_alert(err_msg)
        return

    balance_mode = "PRACTICE"
    api.change_balance(balance_mode)
    
    start_msg = f"🚀 *Pullback Bot Started*\nAsset: {ASSET}\nTimeframe: 1H\nMode: {balance_mode}"
    logger.info(start_msg)
    send_telegram_alert(start_msg)

    last_candle_time = 0

    while True:
        try:
            if not api.check_connect():
                logger.warning("Connection lost. Reconnecting...")
                api.connect()

            candles = api.get_candles(ASSET, TIMEFRAME, 250, time.time())
            if not candles:
                time.sleep(10)
                continue

            df = pd.DataFrame(candles)
            
            # Map iqoptionapi specific keys to standard names
            if 'max' in df.columns:
                df = df.rename(columns={'max': 'high', 'min': 'low'})

            for col in ['open', 'close', 'high', 'low']:
                df[col] = df[col].astype(float)

            current_candle = df.iloc[-1]
            candle_time = int(current_candle["from"])

            if candle_time > last_candle_time:
                last_candle_time = candle_time
                logger.info("New 1H candle closed. Analyzing pullback setup...")

                # Calculate Indicators
                df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
                df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
                
                # RSI 14
                delta = df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                df['rsi14'] = 100 - (100 / (1 + rs))

                row = df.iloc[-2] # Evaluate completed previous candle
                prev_close = row['close']
                ema50 = row['ema50']
                ema200 = row['ema200']
                rsi = row['rsi14']

                # Bullish Trend Pullback Rule:
                is_uptrend = ema50 > ema200
                touched_ema = abs(row['low'] - ema50) / ema50 < 0.0015  # within 0.15% of EMA 50
                bullish_rejection = prev_close > row['open']

                if is_uptrend and touched_ema and bullish_rejection and rsi > 45:
                    msg = f"🟢 *BULLISH PULLBACK SIGNAL*\nAsset: {ASSET}\nExecuting BUY (CALL)..."
                    logger.info(msg)
                    send_telegram_alert(msg)

                    status, order_id = api.buy(STAKE, ASSET, "call", 5) # 5-candle expiry
                    if status:
                        success_msg = f"✅ *CALL Order Placed Successfully*\nID: `{order_id}`"
                        logger.info(success_msg)
                        send_telegram_alert(success_msg)
                    else:
                        fail_msg = f"❌ *CALL Order Failed*: {order_id}"
                        logger.error(fail_msg)
                        send_telegram_alert(fail_msg)

                # Bearish Trend Pullback Rule:
                elif not is_uptrend and abs(row['high'] - ema50) / ema50 < 0.0015 and prev_close < row['open'] and rsi < 55:
                    msg = f"🔴 *BEARISH PULLBACK SIGNAL*\nAsset: {ASSET}\nExecuting SELL (PUT)..."
                    logger.info(msg)
                    send_telegram_alert(msg)

                    status, order_id = api.buy(STAKE, ASSET, "put", 5)
                    if status:
                        success_msg = f"✅ *PUT Order Placed Successfully*\nID: `{order_id}`"
                        logger.info(success_msg)
                        send_telegram_alert(success_msg)
                    else:
                        fail_msg = f"❌ *PUT Order Failed*: {order_id}"
                        logger.error(fail_msg)
                        send_telegram_alert(fail_msg)
                else:
                    logger.info("No pullback signal met criteria.")

            time.sleep(30)
        except Exception as e:
            err_msg = f"⚠️ *Bot Loop Error*: {str(e)}"
            logger.error(err_msg)
            send_telegram_alert(err_msg)
            time.sleep(15)

if __name__ == "__main__":
    run_pullback_bot()