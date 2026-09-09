import os
import sys
import time
import json
import logging
import threading
import urllib.parse
import urllib.request
import concurrent.futures
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option
import iqoptionapi.stable_api as stable_api

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TIMEFRAME = 60
BASE_STAKE = 40.0  # Initial trade amount in USD
MARTINGALE_MULTIPLIER = 2.0  # Double the stake for the 1 single Martingale step
TARGET_STREAK = 5  # Number of consecutive candles needed to trigger a reversal

OTC_PAIRS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "GBPJPY-OTC",
]

LOCAL_TIMEZONE = timezone(timedelta(hours=1))

# ============================================================
# VALIDATION
# ============================================================

for var_name, val in [
    ("OWNER_EMAIL", OWNER_EMAIL),
    ("OWNER_PASSWORD", OWNER_PASSWORD),
    ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
    ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
]:
    if not val:
        print(f"ERROR: {var_name} is missing from .env")
        sys.exit(1)

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("FIREFLY-TRADER")

API = None

# ============================================================
# TELEGRAM NOTIFIER
# ============================================================

def send_telegram_message(message):
    """
    Send text alerts directly to your Telegram chat.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }).encode("utf-8")

    try:
        logger.info("Sending to chat_id: %s | Message payload length: %d", TELEGRAM_CHAT_ID, len(message))
        req = urllib.request.Request(url, data=payload, method="POST")
        logger.info("Request prepared. Sending...")
        with urllib.request.urlopen(req, timeout=10) as response:
            logger.info("Response received. Processing...")
            res = json.loads(response.read().decode("utf-8"))
            if not res.get("ok"):
                logger.error("Telegram API rejection: %s", res)
    except Exception as exc:
        logger.error("Failed to send Telegram notification: %s", exc)

# ============================================================
# CONNECTION & SETUP
# ============================================================

def connect_iq_option():
    global API
    logger.info("Connecting to IQ Option...")
    API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
    check, reason = API.connect()
    if not check:
        logger.error("Connection failed: %s", reason)
        return False
    
    API.change_balance("PRACTICE")
    logger.info("Connected successfully. Practice balance: $%.2f", API.get_balance())
    return True

def refresh_otc_mappings():
    API.api.api_option_init_all_result = None
    API.api.get_api_option_init_all()
    start = time.time()
    while API.api.api_option_init_all_result is None and time.time() - start < 30:
        time.sleep(0.1)
        
    result = API.api.api_option_init_all_result
    if result and result.get("isSuccessful"):
        result_data = result.get("result", {})
        for market_type in ("binary", "turbo"):
            actives = result_data.get(market_type, {}).get("actives", {})
            for active_id, active_data in actives.items():
                raw_name = active_data.get("name", "")
                asset_name = raw_name.split(".", 1)[1] if "." in raw_name else raw_name
                if asset_name in OTC_PAIRS:
                    stable_api.OP_code.ACTIVES[asset_name] = int(active_id)
                    logger.info("Mapped asset %s -> ID %s", asset_name, active_id)
    return True

# ============================================================
# EXECUTION & TIMEOUT PROTECTION
# ============================================================

def place_order_with_timeout(pair, stake, direction, duration=1):
    """
    Executes a digital spot trade directly with a strict timeout guard.
    """
    def _execute():
        return API.buy_digital_spot(pair, stake, direction, duration)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_execute)
        try:
            return future.result(timeout=6.0)
        except concurrent.futures.TimeoutError:
            logger.error("Order placement timed out for %s. Socket unresponsive.", pair)
            return False, None
        except Exception as e:
            logger.error("Exception during threaded order execution: %s", e)
            return False, None

def execute_trade_with_martingale(pair, direction):
    """
    Runs asynchronously in a background thread to prevent blocking the main loop.
    """
    try:
        if not API.check_connect():
            logger.warning("Connection lost. Reconnecting to IQ Option...")
            if not connect_iq_option():
                return

        stake = BASE_STAKE
        logger.info("Executing Trade on %s | Direction: %s | Stake: $%.2f", pair, direction.upper(), stake)
        
        check, order_id = place_order_with_timeout(pair, stake, direction, 1)

        if not check or not order_id:
            logger.error("Order placement failed or timed out for %s.", pair)
            send_telegram_message(f"❌ <b>Order Failed</b> on {pair}\nCould not place base order (Timeout/Rejected).")
            return

        logger.info("Order placed successfully! Order ID: %s. Waiting for result...", order_id)
        send_telegram_message(f"📝 <b>Order Placed Successfully</b>\nMarket: {pair}\nDirection: {direction.upper()}\nStake: ${stake:.2f}\nOrder ID: {order_id}")

        win_result = wait_for_digital_trade_result(order_id)
        
        if win_result == "win":
            logger.info("Trade won on base step.")
            send_telegram_message(f"✅ <b>WIN (Base Step)</b>\nMarket: {pair}\nBase step recovered successfully!")
            return

        elif win_result == "loss":
            logger.warning("Trade lost on base step. Deploying 1st and final Martingale step...")
            send_telegram_message(f"⚠️ <b>LOSS (Base Step)</b>\nMarket: {pair}\nDeploying Martingale step...")
            
            mg_stake = stake * MARTINGALE_MULTIPLIER
            check_mg, mg_order_id = place_order_with_timeout(pair, mg_stake, direction, 1)
                
            if not check_mg or not mg_order_id:
                logger.error("Martingale order placement failed or timed out.")
                send_telegram_message(f"❌ <b>Martingale Order Failed</b> on {pair}\nCould not place Martingale order.")
                return
                
            logger.info("Martingale order placed! Order ID: %s. Waiting for result...", mg_order_id)
            send_telegram_message(f"📝 <b>Martingale Order Placed</b>\nMarket: {pair}\nDirection: {direction.upper()}\nStake: ${mg_stake:.2f}\nOrder ID: {mg_order_id}")

            mg_win_result = wait_for_digital_trade_result(mg_order_id)
            
            if mg_win_result == "win":
                logger.info("Martingale step recovered successfully.")
                send_telegram_message(f"✅ <b>MARTINGALE RECOVERY WIN</b>\nMarket: {pair}\nProfit secured on Martingale step!")
            else:
                logger.error("Martingale step lost. Stopping sequence for this signal.")
                send_telegram_message(f"❌ <b>SEQUENCE LOST</b>\nMarket: {pair}\nBoth base and Martingale steps resulted in a loss.")
    except Exception as e:
        logger.error("Error in trade worker thread: %s", e)

def wait_for_digital_trade_result(order_id):
    """
    Safely polls digital option win/loss status using get_digital_spot_profit.
    """
    start_wait = time.time()
    while time.time() - start_wait < 90:  # Max 90 seconds timeout
        try:
            # Check digital option profit settlement
            status, profit = API.get_digital_spot_profit(order_id)
            if status:
                if profit is not None:
                    if profit > 0:
                        return "win"
                    else:
                        return "loss"
        except Exception:
            pass
        time.sleep(1)
    return "loss"  # Safe fallback if API drops connection frame

# ============================================================
# STREAK ANALYZER LOGIC
# ============================================================

def get_current_live_streak(candles):
    """
    Analyzes completed candles to locate streak color and count.
    """
    if not candles or len(candles) < 2:
        return "DOJI", 0
        
    color_streak = None
    count = 0
    
    for candle in reversed(candles[:-1]):
        open_p = float(candle["open"])
        close_p = float(candle["close"])
        c_color = "GREEN" if close_p > open_p else ("RED" if close_p < open_p else "DOJI")
        
        if color_streak is None:
            if c_color == "DOJI":
                return "DOJI", 0
            color_streak = c_color
            count = 1
        elif c_color == color_streak:
            count += 1
        else:
            break
            
    return color_streak, count

# ============================================================
# MAIN BOT LOOP
# ============================================================

def run_bot():
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message(f"🚀 <b>Firefly AI Bot Started</b>\nMonitoring OTC pairs for target streak: {TARGET_STREAK}")
    logger.info("Bot is running and monitoring assets for streaks...")
    
    last_checked_timestamps = {pair: 0 for pair in OTC_PAIRS}
    
    try:
        while True:
            for pair in OTC_PAIRS:
                candles = API.get_candles(pair, TIMEFRAME, 20, time.time())
                if not candles:
                    continue
                
                latest_candle = candles[-1]
                candle_from = int(latest_candle["from"])
                
                if candle_from > last_checked_timestamps[pair]:
                    last_checked_timestamps[pair] = candle_from
                    
                    current_color, streak_count = get_current_live_streak(candles)
                    logger.info("Pair: %s | Streak: %d %s", pair, streak_count, current_color)
                    
                    if streak_count >= TARGET_STREAK:
                        send_telegram_message(f"🔥 <b>Target Streak Found!</b>\nMarket: <b>{pair}</b>\nStreak: <b>{streak_count} {current_color}</b>\nTriggering Reversal Trade...")
                        
                        if current_color == "RED":
                            logger.info("Target RED streak hit on %s. Spawning trade thread (CALL).", pair)
                            threading.Thread(target=execute_trade_with_martingale, args=(pair, "call"), daemon=True).start()
                            time.sleep(5)  # Brief buffer to avoid duplicate triggers on the same candle
                            
                        elif current_color == "GREEN":
                            logger.info("Target GREEN streak hit on %s. Spawning trade thread (PUT).", pair)
                            threading.Thread(target=execute_trade_with_martingale, args=(pair, "put"), daemon=True).start()
                            time.sleep(5)  # Brief buffer to avoid duplicate triggers on the same candle
                            
            time.sleep(5)
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        send_telegram_message("⚠️ <b>Firefly AI Bot Stopped</b> by user command.")

if __name__ == "__main__":
    run_bot()