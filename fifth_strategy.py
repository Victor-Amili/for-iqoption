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

ASSET = "EURUSD-OTC"
TIMEFRAME = 900  # 15 minutes in seconds
STAKE = 10.0      # Trade amount in your account currency

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("SNEAKY-PIVOT-BOT")

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

def run_sneaky_pivot_bot():
    api = IQ_Option(EMAIL, PASSWORD)
    check, reason = api.connect()
    if not check:
        err_msg = f"❌ Connection failed: {reason}"
        logger.error(err_msg)
        send_telegram_alert(err_msg)
        return

    api.change_balance("PRACTICE")
    start_msg = f"🚀 *Sneaky Pivot Bot Started*\nAsset: {ASSET}\nTimeframe: 15M\nMode: PRACTICE"
    logger.info(start_msg)
    send_telegram_alert(start_msg)

    last_candle_time = 0

    while True:
        try:
            if not api.check_connect():
                logger.warning("Connection lost. Reconnecting...")
                api.connect()

            # Fetch enough 15-min candles to cover a full trading day (~96 candles)
            candles = api.get_candles(ASSET, TIMEFRAME, 100, time.time())
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

            # Run only when a new 15-minute candle closes
            if candle_time > last_candle_time:
                last_candle_time = candle_time
                logger.info("New 15M candle closed. Evaluating Sneaky Pivot levels...")

                # 1. Define Range High & Low (Previous Day approximation using past 96 15-min candles)
                prev_day_slice = df.iloc[-96:-4] 
                range_high = prev_day_slice['high'].max()
                range_low = prev_day_slice['low'].min()

                # 2. Extract the 3-Candle Framework (Last 3 completed candles)
                c1 = df.iloc[-4] # The push candle
                c2 = df.iloc[-3] # The "sneaky" validation candle
                c3 = df.iloc[-2] # The breakout/entry candle

                # --- BUY SETUP (At Range Low) ---
                dipped_to_low = c1['low'] <= range_low * 1.0005
                c2_is_green = c2['close'] > c2['open']
                breaks_c2_high = c3['close'] > c2['high']

                if dipped_to_low and c2_is_green and breaks_c2_high:
                    msg = f"🟢 *Sneaky Pivot BUY Signal Confirmed*\nAsset: {ASSET}\nLevel: {range_low:.5f}\nExecuting CALL..."
                    logger.info("Sneaky Pivot BUY Signal Confirmed at Range Low (%.5f)! Executing...", range_low)
                    send_telegram_alert(msg)

                    # Expiry duration: 1 = 1 candle expiry (15 mins)
                    status, order_id = api.buy(STAKE, ASSET, "call", 1)
                    if status:
                        success_msg = f"✅ *CALL Order Placed*\nID: `{order_id}`"
                        logger.info("CALL Order placed successfully! ID: %s", order_id)
                        send_telegram_alert(success_msg)
                    else:
                        fail_msg = f"❌ *CALL Order Failed*: {order_id}"
                        logger.error("Order failed: %s", order_id)
                        send_telegram_alert(fail_msg)

                # --- SELL SETUP (At Range High) ---
                spiked_to_high = c1['high'] >= range_high * 0.9995
                c2_is_red = c2['close'] < c2['open']
                breaks_c2_low = c3['close'] < c2['low']

                if spiked_to_high and c2_is_red and breaks_c2_low:
                    msg = f"🔴 *Sneaky Pivot SELL Signal Confirmed*\nAsset: {ASSET}\nLevel: {range_high:.5f}\nExecuting PUT..."
                    logger.info("Sneaky Pivot SELL Signal Confirmed at Range High (%.5f)! Executing...", range_high)
                    send_telegram_alert(msg)

                    status, order_id = api.buy(STAKE, ASSET, "put", 1)
                    if status:
                        success_msg = f"✅ *PUT Order Placed*\nID: `{order_id}`"
                        logger.info("PUT Order placed successfully! ID: %s", order_id)
                        send_telegram_alert(success_msg)
                    else:
                        fail_msg = f"❌ *PUT Order Failed*: {order_id}"
                        logger.error("Order failed: %s", order_id)
                        send_telegram_alert(fail_msg)
                else:
                    logger.info("No setup criteria met on this candle cycle.")

            time.sleep(30)
        except Exception as e:
            err_msg = f"⚠️ *Bot Loop Error*: {str(e)}"
            logger.error(err_msg)
            send_telegram_alert(err_msg)
            time.sleep(10)

if __name__ == "__main__":
    run_sneaky_pivot_bot()