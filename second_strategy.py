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

import pandas as pd
import numpy as np
from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option
import iqoptionapi.stable_api as stable_api

# ============================================================
# CONFIGURATION (STRATEGY 2: 5-MIN CONFLUENCE)
# ============================================================

load_dotenv()

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TIMEFRAME = 60          # 1-minute candles
TRADE_DURATION = 5      # 5-minute expiry
BASE_STAKE = 40.0 
MARTINGALE_MULTIPLIER = 2.0 

OTC_PAIRS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "GBPJPY-OTC",
]

global_trade_active = False
global_trade_lock = threading.Lock()
order_execution_lock = threading.Lock()

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
# CONNECTION & MAPPINGS
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
# TECHNICAL INDICATOR CALCULATIONS (STRATEGY 2)
# ============================================================

def calculate_indicators(candles):
    df = pd.DataFrame(candles)
    # Map iqoptionapi's 'min'/'max' keys to standard 'low'/'high' names
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    
    for col in ['open', 'close', 'high', 'low']:
        df[col] = df[col].astype(float)
        
    # 1. 100-period EMA (Trend Filter)
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    
    # 2. MACD (10, 22, 9)
    ema10 = df['close'].ewm(span=10, adjust=False).mean()
    ema22 = df['close'].ewm(span=22, adjust=False).mean()
    df['macd_line'] = ema10 - ema22
    df['signal_line'] = df['macd_line'].ewm(span=9, adjust=False).mean()
    df['histogram'] = df['macd_line'] - df['signal_line']
    
    # 3. SuperTrend (10, 3)
    period = 10
    multiplier = 3.0
    hl2 = (df['high'] + df['low']) / 2
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift(1))
    tr3 = abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    
    upper_basic = hl2 + (multiplier * atr)
    lower_basic = hl2 - (multiplier * atr)
    
    upper_band = [0.0] * len(df)
    lower_band = [0.0] * len(df)
    super_trend = [0.0] * len(df)
    direction = [1] * len(df) # 1 for bullish, -1 for bearish
    
    for i in range(1, len(df)):
        if df['close'].iloc[i] > upper_band[i-1]:
            upper_band[i] = upper_basic.iloc[i]
        else:
            upper_band[i] = min(upper_basic.iloc[i], upper_band[i-1]) if upper_band[i-1] != 0 else upper_basic.iloc[i]
            
        if df['close'].iloc[i] < lower_band[i]:
            lower_band[i] = lower_basic.iloc[i]
        else:
            lower_band[i] = max(lower_basic.iloc[i], lower_band[i-1]) if lower_band[i-1] != 0 else lower_basic.iloc[i]
            
        if direction[i-1] == 1:
            if df['close'].iloc[i] < lower_band[i]:
                direction[i] = -1
                super_trend[i] = upper_band[i]
            else:
                direction[i] = 1
                super_trend[i] = lower_band[i]
        else:
            if df['close'].iloc[i] > upper_band[i]:
                direction[i] = 1
                super_trend[i] = lower_band[i]
            else:
                direction[i] = -1
                super_trend[i] = upper_band[i]
                
    df['super_dir'] = direction
    
    # 4. Vortex Indicator (14)
    v_period = 14
    vm_plus = (df['high'] - df['low'].shift(1)).abs()
    vm_minus = (df['low'] - df['high'].shift(1)).abs()
    sum_tr = tr.rolling(v_period).sum()
    sum_vm_plus = vm_plus.rolling(v_period).sum()
    sum_vm_minus = vm_minus.rolling(v_period).sum()
    
    df['vi_plus'] = sum_vm_plus / sum_tr
    df['vi_minus'] = sum_vm_minus / sum_tr
    
    return df

def check_strategy_2_signal(candles):
    """
    Evaluates Strategy 2 confluence:
    - 100 EMA trend confirmation
    - SuperTrend direction change / active signal
    - Vortex Indicator crossover (vi_plus > vi_minus for call, vice versa)
    - MACD histogram alignment & count < 5
    """
    if len(candles) < 120:
        return None
        
    df = calculate_indicators(candles)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    close = last['close']
    ema100 = last['ema100']
    super_dir = last['super_dir']
    
    vi_plus = last['vi_plus']
    vi_minus = last['vi_minus']
    prev_vi_plus = prev['vi_plus']
    prev_vi_minus = prev['vi_minus']
    
    hist = last['histogram']
    hist_prev = prev['histogram']
    
    # Count consecutive histogram bars in current direction
    hist_count = 0
    for i in range(len(df)-1, -1, -1):
        h = df['histogram'].iloc[i]
        if (h > 0 and hist > 0) or (h < 0 and hist < 0):
            hist_count += 1
        else:
            break
            
    if hist_count > 5:
        return None  # Rule: MACD candles shouldn't have more than 5 bars in the move
        
    # CALL (Bullish Confluence)
    if (close > ema100 and 
        super_dir == 1 and 
        vi_plus > vi_minus and prev_vi_plus <= prev_vi_minus and 
        hist > 0 and hist > hist_prev):
        return "call"
        
    # PUT (Bearish Confluence)
    if (close < ema100 and 
        super_dir == -1 and 
        vi_plus < vi_minus and prev_vi_plus >= prev_vi_minus and 
        hist < 0 and hist < hist_prev):
        return "put"
        
    return None

# ============================================================
# EXECUTION & BALANCE VERIFICATION
# ============================================================

def place_order_with_timeout(pair, stake, direction, duration):
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
            logger.error("Order placement timed out for %s.", pair)
            return False, None
        except Exception as e:
            logger.error("Exception during threaded order execution: %s", e)
            return False, None

def execute_trade_sequence(pair, direction):
    global global_trade_active
    try:
        if not ensure_connection():
            logger.error("Could not recover connection for trade execution.")
            return

        stake = BASE_STAKE
        balance_before = API.get_balance()
        
        logger.info("Executing 5M Trade on %s | Dir: %s | Stake: $%.2f | Pre-Bal: $%.2f", pair, direction.upper(), stake, balance_before)
        
        check, order_id = place_order_with_timeout(pair, stake, direction, TRADE_DURATION)

        if not check or not order_id:
            logger.error("Order placement failed or timed out for %s.", pair)
            send_telegram_message(f"❌ <b>Order Failed</b> on {pair}\nCould not place base order.")
            return

        logger.info("Base order placed! ID: %s. Sleeping 305s for 5M outcome...", order_id)
        send_telegram_message(f"📝 <b>5M Base Order Placed</b>\nMarket: {pair}\nDirection: {direction.upper()}\nStake: ${stake:.2f}")

        # Wait for 5-minute trade expiry + buffer
        time.sleep(305)

        balance_after_base = API.get_balance()
        balance_diff = balance_after_base - balance_before
        
        logger.info("Base settlement check -> Pre: $%.2f | Post: $%.2f | Diff: $%.2f", balance_before, balance_after_base, balance_diff)

        if balance_diff > 0:
            logger.info("Trade won on base step for %s.", pair)
            send_telegram_message(f"✅ <b>WIN (Base Step)</b>\nMarket: {pair}\nProfit: +${balance_diff:.2f}")
            return

        # Deploy Martingale step
        logger.warning("Trade lost on base step for %s (Diff: $%.2f). Deploying Martingale...", pair, balance_diff)
        send_telegram_message(f"⚠️ <b>LOSS (Base Step)</b>\nMarket: {pair}\nDeploying Martingale step...")
        
        mg_stake = stake * MARTINGALE_MULTIPLIER
        balance_before_mg = API.get_balance()
        
        check_mg, mg_order_id = place_order_with_timeout(pair, mg_stake, direction, TRADE_DURATION)
            
        if not check_mg or not mg_order_id:
            logger.error("Martingale order placement failed or timed out for %s.", pair)
            send_telegram_message(f"❌ <b>Martingale Order Failed</b> on {pair}")
            return
            
        logger.info("Martingale order placed! ID: %s. Sleeping 305s for outcome...", mg_order_id)
        send_telegram_message(f"📝 <b>5M Martingale Order Placed</b>\nMarket: {pair}\nDirection: {direction.upper()}\nStake: ${mg_stake:.2f}")

        time.sleep(305)

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
# MAIN BOT LOOP
# ============================================================

def run_bot():
    global global_trade_active
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message(f"🚀 <b>Firefly AI Bot Started</b>\nStrategy 2 Active (5M Expiry | MACD + Vortex + SuperTrend + 100 EMA)")
    logger.info("Bot is running and monitoring assets with Strategy 2 rules...")
    
    last_checked_timestamps = {pair: 0 for pair in OTC_PAIRS}
    
    try:
        while True:
            if not ensure_connection():
                time.sleep(5)
                continue

            with global_trade_lock:
                if global_trade_active:
                    time.sleep(2)
                    continue

            for pair in OTC_PAIRS:
                try:
                    with global_trade_lock:
                        if global_trade_active:
                            break

                    logger.info("Fetching candles for %s...", pair)
                    candles = API.get_candles(pair, TIMEFRAME, 150, time.time())
                    if not candles:
                        logger.warning("No candles returned for %s. Retrying next cycle...", pair)
                        continue
                    
                    latest_candle = candles[-1]
                    candle_from = int(latest_candle["from"])
                    
                    if candle_from > last_checked_timestamps[pair]:
                        last_checked_timestamps[pair] = candle_from
                        logger.info("New candle detected for %s. Evaluating Strategy 2...", pair)
                        
                        signal = check_strategy_2_signal(candles)
                        if signal:
                            with global_trade_lock:
                                if global_trade_active:
                                    continue
                                global_trade_active = True

                            send_telegram_message(f"🔥 <b>Strategy 2 Confluence Found!</b>\nMarket: <b>{pair}</b>\nDirection: <b>{signal.upper()}</b> (5M Expiry)")
                            logger.info("Signal confirmed on %s -> %s. Spawning trade thread.", pair, signal.upper())
                            
                            threading.Thread(target=execute_trade_sequence, args=(pair, signal), daemon=True).start()
                            break
                        else:
                            logger.info("No signal confluence for %s on this candle.", pair)
                                
                except Exception as ex:
                    logger.error("Error evaluating strategy for %s: %s", pair, ex)
                        
            time.sleep(3)
            
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        send_telegram_message("⚠️ <b>Firefly AI Bot Stopped</b> by user command.")
        
if __name__ == "__main__":
    run_bot()