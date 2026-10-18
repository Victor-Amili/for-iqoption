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
logger = logging.getLogger("FIREFLY-TARGETED-BACKTEST")

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

# ============================================================
# TARGETED EVALUATION: STRATEGY 4 & STRATEGY 7 ONLY
# ============================================================

def evaluate_precision_signals(candles):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low']:
        df[col] = df[col].astype(float)
        
    # ADX (14)
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

    # ATR & Volatility
    df['atr'] = atr14
    df['atr_sma'] = df['atr'].rolling(20).mean()

    # RSI (14) for Strategy 7 filter
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi14'] = 100 - (100 / (1 + (gain / loss)))

    df['body_size'] = (df['close'] - df['open']).abs()
    df['avg_body'] = df['body_size'].rolling(20).mean()
    
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    df['sma50'] = df['close'].rolling(50).mean()

    df['sig_4'] = None
    df['sig_7'] = None

    for i in range(120, len(df)):
        row = df.iloc[i]
        
        # ========================================================
        # STRATEGY 4: EMA Cross + ADX + Macro EMA + ATR Volatility
        # ========================================================
        ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i]
        ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i]
        prev_ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i-1]
        prev_ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i-1]
        
        if ema9 > ema21 and prev_ema9 <= prev_ema21:
            if row['adx'] > 28 and row['close'] > row['ema100'] and row['atr'] > row['atr_sma']:
                df.loc[i, 'sig_4'] = 'call'
        elif ema9 < ema21 and prev_ema9 >= prev_ema21:
            if row['adx'] > 28 and row['close'] < row['ema100'] and row['atr'] > row['atr_sma']:
                df.loc[i, 'sig_4'] = 'put'

        # ========================================================
        # STRATEGY 7: Precision MA Pullback + 3x Wick + RSI Reset
        # ========================================================
        sma50_val = row['sma50']
        sma50_prev = df['sma50'].iloc[i-3]
        
        lower_wick = min(row['open'], row['close']) - row['low']
        upper_wick = row['high'] - max(row['open'], row['close'])
        total_range = row['high'] - row['low']
        
        if total_range > 0:
            # Bullish: Upward slope, deep rejection wick (3x body), RSI reset below 55
            if sma50_val > sma50_prev and row['low'] <= sma50_val and row['close'] > sma50_val:
                if lower_wick >= (3.0 * row['body_size']) and row['rsi14'] < 55:
                    df.loc[i, 'sig_7'] = 'call'
                    
            # Bearish: Downward slope, deep upper wick (3x body), RSI reset above 45
            elif sma50_val < sma50_prev and row['high'] >= sma50_val and row['close'] < sma50_val:
                if upper_wick >= (3.0 * row['body_size']) and row['rsi14'] > 45:
                    df.loc[i, 'sig_7'] = 'put'

    return df


def fetch_large_candle_history(pair, total_needed=5000):
    """
    Paginates backward to fetch more than the API's single-request limit (1,000).
    """
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
            
        # Prepend older candles to the list
        all_candles = candles + all_candles
        
        # Update end_time to the timestamp of the oldest candle received in this batch
        end_time = candles[0]['from'] - 1
        
        # Prevent infinite loops if API stops returning data
        time.sleep(0.5)
        
    return all_candles

# ============================================================
# BACKTEST EXECUTION
# ============================================================

def run_targeted_backtest():
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message("🎯 <b>Targeted Backtest Started (Strategies 4 & 7)</b>\nAnalyzing expanded dataset (1,000 candles per pair)...")

    strategy_names = {
        4: "Strategy 4 (EMA Cross Strict)",
        7: "Strategy 7 (MA Pullback Pin Bar)"
    }

    results = {s_id: {
        "name": name,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "balance": STARTING_BALANCE
    } for s_id, name in strategy_names.items()}

    payout_rate = 0.82 

    for pair in OTC_PAIRS:
        logger.info("Fetching 5,000 historical candles for %s...", pair)
        # Increased count parameter from 600 to 1000 for a deeper look
        # NEW PGINATED LINE:
        candles = fetch_large_candle_history(pair, total_needed=5000)
        if not candles or len(candles) < 150:
            continue
            
        df = evaluate_precision_signals(candles)

        for i in range(100, len(df) - 1):
            for s_id in (4, 7):
                sig = df.loc[i, f'sig_{s_id}']
                if sig is not None:
                    entry_close = df.loc[i, 'close']
                    exit_close = df.loc[i+1, 'close']
                    
                    is_win = (sig == 'call' and exit_close > entry_close) or (sig == 'put' and exit_close < entry_close)
                    
                    st = results[s_id]
                    st["trades"] += 1

                    if is_win:
                        st["wins"] += 1
                        st["balance"] += BASE_STAKE * payout_rate
                    else:
                        st["losses"] += 1
                        st["balance"] -= BASE_STAKE

    report_lines = ["🎯 <b>FIREFLY TARGETED BACKTEST RESULTS (4 & 7)</b>\n"]
    
    for s_id, st in results.items():
        total_trades = st["trades"] if st["trades"] > 0 else 1
        win_rate = (st["wins"] / total_trades) * 100
        total_profit = st["balance"] - STARTING_BALANCE

        report_lines.append(
            f"<b>{st['name']}</b>\n"
            f"• Total Trades: {st['trades']}\n"
            f"• Wins: {st['wins']} | Losses: {st['losses']}\n"
            f"• Win Percentage: <b>{win_rate:.2f}%</b>\n"
            f"• Starting Balance: ${STARTING_BALANCE:.2f}\n"
            f"• Final Balance: <b>${st['balance']:.2f}</b>\n"
            f"• Total Profit/Loss: <b>${total_profit:+.2f}</b>\n"
            f"-----------------------------------"
        )

    final_message = "\n".join(report_lines)
    send_telegram_message(final_message)
    logger.info("Targeted backtest complete. Report dispatched to Telegram.")

if __name__ == "__main__":
    run_targeted_backtest()