import os
import sys
import time
import logging
import requests
import pandas as pd
from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option

load_dotenv()

EMAIL = os.getenv("OWNER_EMAIL")
PASSWORD = os.getenv("OWNER_PASSWORD")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ASSET = "GBPUSD-OTC"
TIMEFRAME = 3600  # 1 hour
STAKE = 10.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("RETEST-BOT")

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

def run_retest_bot():
    api = IQ_Option(EMAIL, PASSWORD)
    check, reason = api.connect()
    if not check:
        err_msg = f"❌ Connection failed: {reason}"
        logger.error(err_msg)
        send_telegram_alert(err_msg)
        return

    api.change_balance("PRACTICE")
    start_msg = f"🚀 *S&R Retest Bot Started*\nAsset: {ASSET}\nTimeframe: 1H\nMode: PRACTICE"
    logger.info(start_msg)
    send_telegram_alert(start_msg)

    last_candle_time = 0

    while True:
        try:
            if not api.check_connect():
                logger.warning("Connection lost. Reconnecting...")
                api.connect()

            candles = api.get_candles(ASSET, TIMEFRAME, 60, time.time())
            if not candles:
                time.sleep(10)
                continue

            df = pd.DataFrame(candles)
            
            # Map iqoptionapi keys ('max'/'min') to standard names ('high'/'low')
            if 'max' in df.columns:
                df = df.rename(columns={'max': 'high', 'min': 'low'})

            for col in ['open', 'close', 'high', 'low']:
                df[col] = df[col].astype(float)

            current_candle = df.iloc[-1]
            candle_time = int(current_candle["from"])

            if candle_time > last_candle_time:
                last_candle_time = candle_time
                logger.info("Evaluating Support/Resistance levels...")

                # Define a recent resistance level from previous swing high
                resistance_level = df['high'].iloc[-30:-2].max()
                support_level = df['low'].iloc[-30:-2].min()

                prev_candle = df.iloc[-2]
                live_price = current_candle['close']

                # Retest of Broken Resistance (Now acting as Support)
                broke_resistance = prev_candle['close'] > resistance_level
                retesting_level = abs(live_price - resistance_level) / resistance_level < 0.001

                if broke_resistance and retesting_level:
                    msg = f"🟢 *Support Retest Signal Confirmed*\nAsset: {ASSET}\nLevel: {resistance_level:.5f}\nExecuting BUY (CALL)..."
                    logger.info(msg)
                    send_telegram_alert(msg)

                    status, order_id = api.buy(STAKE, ASSET, "call", 3)
                    if status:
                        success_msg = f"✅ *CALL Order Placed*\nID: `{order_id}`"
                        logger.info("Retest BUY order placed. ID: %s", order_id)
                        send_telegram_alert(success_msg)
                    else:
                        fail_msg = f"❌ *CALL Order Failed*: {order_id}"
                        logger.error(fail_msg)
                        send_telegram_alert(fail_msg)

                # Retest of Broken Support (Now acting as Resistance)
                broke_support = prev_candle['close'] < support_level
                retesting_support = abs(live_price - support_level) / support_level < 0.001

                if broke_support and retesting_support:
                    msg = f"🔴 *Resistance Retest Signal Confirmed*\nAsset: {ASSET}\nLevel: {support_level:.5f}\nExecuting SELL (PUT)..."
                    logger.info(msg)
                    send_telegram_alert(msg)

                    status, order_id = api.buy(STAKE, ASSET, "put", 3)
                    if status:
                        success_msg = f"✅ *PUT Order Placed*\nID: `{order_id}`"
                        logger.info("Retest SELL order placed. ID: %s", order_id)
                        send_telegram_alert(success_msg)
                    else:
                        fail_msg = f"❌ *PUT Order Failed*: {order_id}"
                        logger.error(fail_msg)
                        send_telegram_alert(fail_msg)
                else:
                    logger.info("No retest signal met criteria on this candle.")

            time.sleep(30)
        except Exception as e:
            err_msg = f"⚠️ *Retest Bot Loop Error*: {str(e)}"
            logger.error(err_msg)
            send_telegram_alert(err_msg)
            time.sleep(15)

if __name__ == "__main__":
    run_retest_bot()