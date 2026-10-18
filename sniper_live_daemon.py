import os
import sys
import time
import json
import logging
import urllib.parse
import urllib.request

import pandas as pd
import numpy as np
from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option
import iqoptionapi.stable_api as stable_api

load_dotenv()

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STAKE_PERCENTAGE = 0.18  # Steady 18% compounding risk per live trade
TOTAL_CANDLES_NEEDED = 10000

OTC_PAIRS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "GBPJPY-OTC",
]

TIMEFRAME_SEC = 900  # 15-Minute candles
TIMEFRAME_NAME = "15-Minute"

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
logger = logging.getLogger("FIREFLY-LIVE-DAEMON")

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

def connect_iq_option():
    global API
    logger.info("Connecting to IQ Option for LIVE execution...")
    API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
    check, reason = API.connect()
    if not check:
        logger.error("Connection failed: %s", reason)
        return False
    logger.info("Connected successfully. Account Mode: REAL/PRACTICE sync.")
    return True

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
    return True

def fetch_candle_history(pair, timeframe, total_needed=10000):
    all_candles = []
    end_time = time.time()
    chunk_size = 1000
    
    while len(all_candles) < total_needed:
        remaining = total_needed - len(all_candles)
        current_count = min(chunk_size, remaining)
        candles = API.get_candles(pair, timeframe, current_count, end_time)
        if not candles:
            break
        all_candles = candles + all_candles
        end_time = candles[0]['from'] - 1
        time.sleep(0.2)
    return all_candles

def evaluate_latest_signal(candles):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low']:
        df[col] = df[col].astype(float)
        
    df['datetime'] = pd.to_datetime(df['from'], unit='s')
    df_1h = df.set_index('datetime').resample('1h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
    }).dropna()
    df_1h['ema50_1h'] = df_1h['close'].ewm(span=50, adjust=False).mean()
    
    df_1h_reset = df_1h.reset_index()
    df = pd.merge_asof(df.sort_values('datetime'), df_1h_reset[['datetime', 'ema50_1h', 'close']], on='datetime', direction='backward')
    df = df.rename(columns={'close_x': 'close', 'close_y': 'close_1h'})

    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()
    
    up_move = df['high'] - df['high'].shift(1)
    down_move = df['low'].shift(1) - df['low']
    p_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    m_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    p_di = 100 * pd.Series(p_dm).rolling(14).mean() / (atr14 + 1e-9)
    m_di = 100 * pd.Series(m_dm).rolling(14).mean() / (atr14 + 1e-9)
    dx = 100 * (p_di - m_di).abs() / (p_di + m_di + 1e-9)
    df['adx'] = dx.rolling(14).mean()

    df['body_size'] = (df['close'] - df['open']).abs()
    df['avg_body'] = df['body_size'].rolling(20).mean()
    df['sma50'] = df['close'].rolling(50).mean()

    # We evaluate the second-to-last completed candle to check for a fresh signal
    i = len(df) - 2
    row = df.iloc[i]

    if row['adx'] <= 24 or row['body_size'] < (0.35 * row['avg_body']):
        return None

    ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i]
    ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i]
    prev_ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i-1]
    prev_ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i-1]
    
    s4 = 'call' if ema9 > ema21 and prev_ema9 <= prev_ema21 else ('put' if ema9 < ema21 and prev_ema9 >= prev_ema21 else None)

    sma50_val = row['sma50']
    sma50_prev = df['sma50'].iloc[i-2]
    lower_wick = min(row['open'], row['close']) - row['low']
    upper_wick = row['high'] - max(row['open'], row['close'])
    
    s7 = None
    if sma50_val > sma50_prev and row['low'] <= sma50_val and row['close'] > sma50_val and lower_wick >= (1.2 * row['body_size']):
        s7 = 'call'
    elif sma50_val < sma50_prev and row['high'] >= sma50_val and row['close'] < sma50_val and upper_wick >= (1.2 * row['body_size']):
        s7 = 'put'

    recent_s4 = s4
    if recent_s4 is None:
        p_ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i-1]
        p_ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i-1]
        pp_ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i-2]
        pp_ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i-2]
        if p_ema9 > p_ema21 and pp_ema9 <= pp_ema21:
            recent_s4 = 'call'
        elif p_ema9 < p_ema21 and pp_ema9 >= pp_ema21:
            recent_s4 = 'put'

    if recent_s4 is not None and s7 is not None and recent_s4 == s7:
        htf_close, htf_ema = row['close_1h'], row['ema50_1h']
        if pd.notna(htf_close) and pd.notna(htf_ema):
            if recent_s4 == 'call' and htf_close > htf_ema:
                return 'call'
            elif recent_s4 == 'put' and htf_close < htf_ema:
                return 'put'

    return None

def run_live_daemon():
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message("🚀 <b>FIREFLY LIVE DAEMON STARTED</b>\nMonitoring 4 OTC pairs on 15M timeframe...\nSteady Compounding Risk: 18%")
    logger.info("Live monitoring daemon active. Waiting for candle boundaries...")

    last_checked_timestamp = 0

    while True:
        try:
            # Check current balance
            balance = API.get_balance()
            
            # Align with 15-minute candle intervals
            current_time = time.time()
            time_to_next_candle = TIMEFRAME_SEC - (current_time % TIMEFRAME_SEC)
            
            # Sleep until we are 5 seconds past the start of a new 15-minute candle
            if time_to_next_candle > 5:
                time.sleep(5)
                continue

            logger.info("New 15M candle interval reached. Scanning pairs for sniper setup...")
            refresh_otc_mappings()

            for pair in OTC_PAIRS:
                candles = fetch_candle_history(pair, TIMEFRAME_SEC, total_needed=TOTAL_CANDLES_NEEDED)
                if not candles or len(candles) < 200:
                    continue

                # Ensure we only evaluate a new completed candle once
                latest_candle_time = candles[-2]['from']
                if latest_candle_time == last_checked_timestamp:
                    continue

                signal = evaluate_latest_signal(candles)
                if signal:
                    last_checked_timestamp = latest_candle_time
                    stake = max(1.0, round(balance * STAKE_PERCENTAGE, 2))
                    
                    logger.info(f"SIGNAL DETECTED on {pair}: {signal.upper()} | Executing live stake: ${stake}")
                    
                    # Execute binary option trade (expiration = 1 candle / 15 minutes = 1)
                    check, order_id = API.buy(stake, pair, signal, 1)
                    
                    if check:
                        msg = (
                            f"⚡ <b>LIVE TRADE EXECUTED!</b>\n\n"
                            f"• Pair: <b>{pair}</b>\n"
                            f"• Direction: <b>{signal.upper()}</b>\n"
                            f"• Stake: <b>${stake:.2f}</b> (18%)\n"
                            f"• Current Balance: ${balance:.2f}\n"
                            f"• Order ID: {order_id}"
                        )
                        send_telegram_message(msg)
                    else:
                        logger.error(f"Failed to execute trade on {pair}: {order_id}")
                        send_telegram_message(f"❌ <b>Execution Error</b> on {pair}: {order_id}")

            # Sleep a bit to prevent duplicate checks in the same window
            time.sleep(10)

        except Exception as exc:
            logger.error(f"Error in live daemon loop: {exc}")
            time.sleep(15)

if __name__ == "__main__":
    run_live_daemon()