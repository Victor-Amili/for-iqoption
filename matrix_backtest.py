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

BASE_STAKE = 40.0 
STARTING_BALANCE = 1000.0 

OTC_PAIRS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "GBPJPY-OTC",
]

# Timeframes to test (in seconds): 60 (1m), 300 (5m), 900 (15m)
TIMEFRAMES = {
    60: "1-Minute",
    300: "5-Minute",
    900: "15-Minute"
}

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
logger = logging.getLogger("FIREFLY-MATRIX-20K")

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
    logger.info("Connecting to IQ Option...")
    API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
    check, reason = API.connect()
    if not check:
        logger.error("Connection failed: %s", reason)
        return False
    logger.info("Connected successfully.")
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

def fetch_candle_history(pair, timeframe, total_needed=20000):
    all_candles = []
    end_time = time.time()
    chunk_size = 1000
    
    while len(all_candles) < total_needed:
        remaining = total_needed - len(all_candles)
        current_count = min(chunk_size, remaining)
        
        logger.info(f"Fetching chunk for {pair} ({timeframe}s) - Current total: {len(all_candles)}/{total_needed}")
        candles = API.get_candles(pair, timeframe, current_count, end_time)
        if not candles:
            break
            
        all_candles = candles + all_candles
        end_time = candles[0]['from'] - 1
        time.sleep(0.2)
        
    return all_candles

# ============================================================
# MATRIX STRATEGY EVALUATION
# ============================================================

def evaluate_matrix_signals(candles):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low']:
        df[col] = df[col].astype(float)
        
    # Indicators
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
    df['sma50'] = df['close'].rolling(50).mean()

    df['sig_4'] = None
    df['sig_7'] = None
    df['sig_confluence'] = None

    for i in range(60, len(df)):
        row = df.iloc[i]
        
        # --- Strategy 4: EMA Cross ---
        ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i]
        ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i]
        prev_ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i-1]
        prev_ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i-1]
        
        s4 = None
        if ema9 > ema21 and prev_ema9 <= prev_ema21 and row['adx'] > 20:
            s4 = 'call'
        elif ema9 < ema21 and prev_ema9 >= prev_ema21 and row['adx'] > 20:
            s4 = 'put'
        df.loc[i, 'sig_4'] = s4

        # --- Strategy 7: MA Pullback Pin Bar ---
        sma50_val = row['sma50']
        sma50_prev = df['sma50'].iloc[i-2]
        lower_wick = min(row['open'], row['close']) - row['low']
        upper_wick = row['high'] - max(row['open'], row['close'])
        
        s7 = None
        if sma50_val > sma50_prev and row['low'] <= sma50_val and row['close'] > sma50_val:
            if lower_wick >= (1.5 * row['body_size']):
                s7 = 'call'
        elif sma50_val < sma50_prev and row['high'] >= sma50_val and row['close'] < sma50_val:
            if upper_wick >= (1.5 * row['body_size']):
                s7 = 'put'
        df.loc[i, 'sig_7'] = s7

        # --- Confluence ---
        if s4 == s7 and s4 is not None:
            df.loc[i, 'sig_confluence'] = s4

    return df

# ============================================================
# EXECUTION (20,000 CANDLES STRESS TEST)
# ============================================================

def run_matrix_backtest():
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message("🚀 <b>20,000-Candle Stress Test Started</b>\nEvaluating Matrix across 1m, 5m, and 15m timeframes with deep history...")

    payout_rate = 0.82 

    matrix_results = {}
    for tf_sec, tf_name in TIMEFRAMES.items():
        for mode in ("sig_4", "sig_7", "sig_confluence"):
            matrix_results[(tf_name, mode)] = {"trades": 0, "wins": 0, "losses": 0, "balance": STARTING_BALANCE}

    for tf_sec, tf_name in TIMEFRAMES.items():
        logger.info("Evaluating Timeframe: %s with 20k candles", tf_name)
        for pair in OTC_PAIRS:
            candles = fetch_candle_history(pair, tf_sec, total_needed=20000)
            if not candles or len(candles) < 200:
                continue
                
            df = evaluate_matrix_signals(candles)

            for i in range(60, len(df) - 1):
                for mode in ("sig_4", "sig_7", "sig_confluence"):
                    sig = df.loc[i, mode]
                    if sig is not None:
                        entry_close = df.loc[i, 'close']
                        exit_close = df.loc[i+1, 'close']
                        
                        is_win = (sig == 'call' and exit_close > entry_close) or (sig == 'put' and exit_close < entry_close)
                        
                        st = matrix_results[(tf_name, mode)]
                        st["trades"] += 1
                        if is_win:
                            st["wins"] += 1
                            st["balance"] += BASE_STAKE * payout_rate
                        else:
                            st["losses"] += 1
                            st["balance"] -= BASE_STAKE

    # Build Report
    report_lines = ["🚀 <b>FIREFLY 20K CANDLE MATRIX STRESS RESULTS</b>\n"]
    
    names_map = {
        "sig_4": "Strategy 4 (EMA Cross)",
        "sig_7": "Strategy 7 (MA Pullback)",
        "sig_confluence": "Confluence (4 & 7 Combined)"
    }

    for tf_sec, tf_name in TIMEFRAMES.items():
        report_lines.append(f"<b>--- TIMEFRAME: {tf_name} (20k Candles) ---</b>")
        for mode in ("sig_4", "sig_7", "sig_confluence"):
            st = matrix_results[(tf_name, mode)]
            tot = st["trades"] if st["trades"] > 0 else 1
            wr = (st["wins"] / tot) * 100
            prof = st["balance"] - STARTING_BALANCE
            
            report_lines.append(
                f"<b>{names_map[mode]}</b>\n"
                f"• Trades: {st['trades']} | Win Rate: <b>{wr:.2f}%</b>\n"
                f"• Final P/L: <b>${prof:+.2f}</b>\n"
            )
        report_lines.append("-----------------------------------")

    send_telegram_message("\n".join(report_lines))
    logger.info("20K Matrix backtest complete. Dispatched to Telegram.")

if __name__ == "__main__":
    run_matrix_backtest()