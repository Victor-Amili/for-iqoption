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
logger = logging.getLogger("FIREFLY-CONFLUENCE-BACKTEST")

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

def fetch_large_candle_history(pair, total_needed=5000):
    all_candles = []
    end_time = time.time()
    chunk_size = 1000
    
    while len(all_candles) < total_needed:
        remaining = total_needed - len(all_candles)
        current_count = min(chunk_size, remaining)
        
        logger.info(f"Fetching batch for {pair} (Current total: {len(all_candles)}/{total_needed})...")
        candles = API.get_candles(pair, 60, current_count, end_time)
        
        if not candles:
            break
            
        all_candles = candles + all_candles
        end_time = candles[0]['from'] - 1
        time.sleep(0.5)
        
    return all_candles

# ============================================================
# UNIFIED SNIPER CONFLUENCE EVALUATION
# ============================================================

def evaluate_sniper_confluence_signals(candles):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low']:
        df[col] = df[col].astype(float)
        
    # 1. Higher Timeframe (5-Minute) Trend Calculation via Resampling
    df['datetime'] = pd.to_datetime(df['from'], unit='s')
    df_5m = df.set_index('datetime').resample('5min').agg({'close': 'last'}).dropna()
    df_5m['ema_5m'] = df_5m['close'].ewm(span=20, adjust=False).mean()
    
    df['dt_5m'] = df['datetime'].dt.floor('5min')
    df = df.merge(df_5m[['ema_5m']], left_on='dt_5m', right_index=True, how='left')
    df['htf_trend_up'] = df['close'] > df['ema_5m']
    df['htf_trend_down'] = df['close'] < df['ema_5m']

    # 2. Indicators for Strategy 4 & 7
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

    df['sig_confluence'] = None

    for i in range(120, len(df)):
        row = df.iloc[i]
        
        # 3. Active Market Hours Filter (UTC 07:00 to 20:00)
        trade_hour = row['datetime'].hour
        if not (7 <= trade_hour <= 20):
            continue

        # --- Strategy 4 Logic Check ---
        ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i]
        ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i]
        prev_ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i-1]
        prev_ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i-1]
        
        s4_signal = None
        if ema9 > ema21 and prev_ema9 <= prev_ema21 and row['adx'] > 25:
            s4_signal = 'call'
        elif ema9 < ema21 and prev_ema9 >= prev_ema21 and row['adx'] > 25:
            s4_signal = 'put'

        # --- Strategy 7 Logic Check ---
        sma50_val = row['sma50']
        sma50_prev = df['sma50'].iloc[i-3]
        lower_wick = min(row['open'], row['close']) - row['low']
        upper_wick = row['high'] - max(row['open'], row['close'])
        
        s7_signal = None
        if sma50_val > sma50_prev and row['low'] <= sma50_val and row['close'] > sma50_val:
            if lower_wick >= (2.0 * row['body_size']):
                s7_signal = 'call'
        elif sma50_val < sma50_prev and row['high'] >= sma50_val and row['close'] < sma50_val:
            if upper_wick >= (2.0 * row['body_size']):
                s7_signal = 'put'

        # --- Confluence & Higher Timeframe Enforcement ---
        if s4_signal == s7_signal and s4_signal is not None:
            if s4_signal == 'call' and row['htf_trend_up']:
                df.loc[i, 'sig_confluence'] = 'call'
            elif s4_signal == 'put' and row['htf_trend_down']:
                df.loc[i, 'sig_confluence'] = 'put'

    return df

# ============================================================
# BACKTEST EXECUTION
# ============================================================

def run_targeted_backtest():
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message("🎯 <b>Sniper Confluence Backtest Started</b>\nEvaluating combined Strategy 4 & 7 with MTF & Session filters across 5,000 candles...")

    results = {
        "confluence": {
            "name": "Sniper Confluence (Strategies 4 & 7 Combined)",
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "balance": STARTING_BALANCE
        }
    }

    payout_rate = 0.82 

    for pair in OTC_PAIRS:
        logger.info("Fetching 10,000 historical candles for %s...", pair)
        candles = fetch_large_candle_history(pair, total_needed=20000)
        if not candles or len(candles) < 200:
            continue
            
        df = evaluate_sniper_confluence_signals(candles)

        for i in range(120, len(df) - 1):
            sig = df.loc[i, 'sig_confluence']
            if sig is not None:
                entry_close = df.loc[i, 'close']
                exit_close = df.loc[i+1, 'close']
                
                is_win = (sig == 'call' and exit_close > entry_close) or (sig == 'put' and exit_close < entry_close)
                
                st = results["confluence"]
                st["trades"] += 1

                if is_win:
                    st["wins"] += 1
                    st["balance"] += BASE_STAKE * payout_rate
                else:
                    st["losses"] += 1
                    st["balance"] -= BASE_STAKE

    st = results["confluence"]
    total_trades = st["trades"] if st["trades"] > 0 else 1
    win_rate = (st["wins"] / total_trades) * 100
    total_profit = st["balance"] - STARTING_BALANCE

    report_message = (
        f"🎯 <b>FIREFLY SNIPER CONFLUENCE RESULTS</b>\n\n"
        f"<b>{st['name']}</b>\n"
        f"• Total Trades: {st['trades']}\n"
        f"• Wins: {st['wins']} | Losses: {st['losses']}\n"
        f"• Win Percentage: <b>{win_rate:.2f}%</b>\n"
        f"• Starting Balance: ${STARTING_BALANCE:.2f}\n"
        f"• Final Balance: <b>${st['balance']:.2f}</b>\n"
        f"• Total Profit/Loss: <b>${total_profit:+.2f}</b>\n"
        f"-----------------------------------"
    )

    send_telegram_message(report_message)
    logger.info("Sniper Confluence backtest complete. Report dispatched to Telegram.")

if __name__ == "__main__":
    run_targeted_backtest()