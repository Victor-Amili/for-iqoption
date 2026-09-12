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
BASE_STAKE = 40.0 
MARTINGALE_MULTIPLIER = 2.0 
TARGET_STREAK = 5

OTC_PAIRS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "GBPJPY-OTC",
]

# Global lock to ensure strictly ONE trade/martingale sequence runs at a time
global_trade_active = False
global_trade_lock = threading.Lock()
order_execution_lock = threading.Lock()

# ============================================================
# VALIDATION & LOGGING
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("FIREFLY-TRADER")

API = None

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
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

def ensure_connection():
    global API
    try:
        if API is None or not API.check_connect():
            logger.warning("Socket connection lost. Reconnecting...")
            success = connect_iq_option()
            if success:
                refresh_otc_mappings()
                return True
            return False
        return True
    except Exception as e:
        logger.error("Exception during connection check: %s", e)
        return connect_iq_option()

def refresh_otc_mappings():
    if API is None:
        return False
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
# EXECUTION & BALANCE VERIFICATION
# ============================================================

def place_order_with_timeout(pair, stake, direction, duration=1):
    def _execute():
        if not ensure_connection():
            return False, None
        
        active_id = stable_api.OP_code.ACTIVES.get(pair)
        if not active_id:
            return False, None
            
        with order_execution_lock:
            status, order_id = API.buy(stake, pair, direction, duration)
            return status, order_id

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

def execute_trade_sequence(pair, direction):
    """
    Executes Base Trade -> Balance Check -> Optional Martingale -> Global Unlock.
    """
    global global_trade_active
    try:
        if not ensure_connection():
            logger.error("Could not recover connection for trade execution.")
            return

        stake = BASE_STAKE
        balance_before = API.get_balance()
        
        logger.info("Executing Trade on %s | Direction: %s | Stake: $%.2f | Pre-Balance: $%.2f", pair, direction.upper(), stake, balance_before)
        
        check, order_id = place_order_with_timeout(pair, stake, direction, 1)

        if not check or not order_id:
            logger.error("Order placement failed or timed out for %s.", pair)
            send_telegram_message(f"❌ <b>Order Failed</b> on {pair}\nCould not place base order.")
            return

        logger.info("Order placed successfully! Order ID: %s. Sleeping 61s for outcome...", order_id)
        send_telegram_message(f"📝 <b>Base Order Placed</b>\nMarket: {pair}\nDirection: {direction.upper()}\nStake: ${stake:.2f}")

        # Wait for the 60s option to expire + brief buffer
        time.sleep(61)

        balance_after_base = API.get_balance()
        balance_diff = balance_after_base - balance_before
        
        logger.info("Base trade settlement check -> Pre: $%.2f | Post: $%.2f | Diff: $%.2f", balance_before, balance_after_base, balance_diff)

        # If balance increased or stayed above previous (accounting for win profit), it's a win
        if balance_diff > 0:
            logger.info("Trade won on base step for %s. Profit recorded.", pair)
            send_telegram_message(f"✅ <b>WIN (Base Step)</b>\nMarket: {pair}\nProfit: +${balance_diff:.2f}")
            return

        # Otherwise, deploy Martingale
        logger.warning("Trade lost on base step for %s (Diff: $%.2f). Deploying Martingale...", pair, balance_diff)
        send_telegram_message(f"⚠️ <b>LOSS (Base Step)</b>\nMarket: {pair}\nDeploying Martingale step...")
        
        mg_stake = stake * MARTINGALE_MULTIPLIER
        balance_before_mg = API.get_balance()
        
        check_mg, mg_order_id = place_order_with_timeout(pair, mg_stake, direction, 1)
            
        if not check_mg or not mg_order_id:
            logger.error("Martingale order placement failed or timed out for %s.", pair)
            send_telegram_message(f"❌ <b>Martingale Order Failed</b> on {pair}")
            return
            
        logger.info("Martingale order placed! Order ID: %s. Sleeping 61s for outcome...", mg_order_id)
        send_telegram_message(f"📝 <b>Martingale Order Placed</b>\nMarket: {pair}\nDirection: {direction.upper()}\nStake: ${mg_stake:.2f}")

        time.sleep(61)

        balance_after_mg = API.get_balance()
        mg_diff = balance_after_mg - balance_before_mg
        
        logger.info("Martingale settlement check -> Pre: $%.2f | Post: $%.2f | Diff: $%.2f", balance_before_mg, balance_after_mg, mg_diff)

        if mg_diff > 0:
            logger.info("Martingale step recovered successfully for %s.", pair)
            send_telegram_message(f"✅ <b>MARTINGALE RECOVERY WIN</b>\nMarket: {pair}\nProfit secured: +${mg_diff:.2f}")
        else:
            logger.error("Martingale step lost for %s. Sequence finished.", pair)
            send_telegram_message(f"❌ <b>SEQUENCE LOST</b>\nMarket: {pair}\nBoth base and Martingale steps resulted in a loss.")

    except Exception as e:
        logger.error("Error in trade worker thread for %s: %s", pair, e)
    finally:
        with global_trade_lock:
            global_trade_active = False
            logger.info("Global trading lock released. Bot is ready for new signals.")

# ============================================================
# STREAK ANALYZER LOGIC
# ============================================================

def get_current_live_streak(candles):
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
    global global_trade_active
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message(f"🚀 <b>Firefly AI Bot Started</b>\nMonitoring OTC pairs with Balance-Delta Mode | Target Streak: {TARGET_STREAK}")
    logger.info("Bot is running and monitoring assets for streaks...")
    
    last_checked_timestamps = {pair: 0 for pair in OTC_PAIRS}
    
    try:
        while True:
            if not ensure_connection():
                time.sleep(5)
                continue

            # Skip scanning if a trade sequence is already active anywhere
            with global_trade_lock:
                if global_trade_active:
                    time.sleep(2)
                    continue

            for pair in OTC_PAIRS:
                try:
                    with global_trade_lock:
                        if global_trade_active:
                            break

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
                            with global_trade_lock:
                                if global_trade_active:
                                    continue
                                global_trade_active = True

                            send_telegram_message(f"🔥 <b>Target Streak Found!</b>\nMarket: <b>{pair}</b>\nStreak: <b>{streak_count} {current_color}</b>\nTriggering Reversal Trade...")
                            
                            if current_color == "RED":
                                logger.info("Target RED streak hit on %s. Spawning trade thread (CALL).", pair)
                                threading.Thread(target=execute_trade_sequence, args=(pair, "call"), daemon=True).start()
                                break
                                
                            elif current_color == "GREEN":
                                logger.info("Target GREEN streak hit on %s. Spawning trade thread (PUT).", pair)
                                threading.Thread(target=execute_trade_sequence, args=(pair, "put"), daemon=True).start()
                                break
                                
                except Exception as ex:
                    logger.error("Error checking candles for %s: %s", pair, ex)
                        
            time.sleep(3)
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        send_telegram_message("⚠️ <b>Firefly AI Bot Stopped</b> by user command.")

if __name__ == "__main__":
    run_bot()