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
logger = logging.getLogger("FIREFLY-MASTER-BACKTEST")

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
# MASTER MERGED SIGNAL EVALUATION
# Strategies 1-4: Strict Filters (Code 1)
# Strategies 5-7: Optimized Price Action & ADX (Code 2)
# ============================================================

def evaluate_master_strategy_signals(candles):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low']:
        df[col] = df[col].astype(float)
        
    # Bollinger Bands (20, 2)
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['bb_upper'] = df['sma20'] + (2.0 * df['std20'])
    df['bb_lower'] = df['sma20'] - (2.0 * df['std20'])
    
    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi14'] = 100 - (100 / (1 + (gain / loss)))
    
    # EMAs
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # MACD components
    ema10 = df['close'].ewm(span=10, adjust=False).mean()
    ema22 = df['close'].ewm(span=22, adjust=False).mean()
    df['macd_line'] = ema10 - ema22
    df['signal_line'] = df['macd_line'].ewm(span=9, adjust=False).mean()
    df['histogram'] = df['macd_line'] - df['signal_line']

    # ADX (14) Calculation
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

    # Candle body filter
    df['body_size'] = (df['close'] - df['open']).abs()
    df['avg_body'] = df['body_size'].rolling(14).mean()

    for s_id in range(1, 8):
        df[f'sig_{s_id}'] = None

    for i in range(100, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        # --- STRATEGIES 1 TO 4 (From Strict Code 1) ---
        # General filter for 1-4
        if row['adx'] >= 20 and row['body_size'] >= (0.5 * row['avg_body']):
            # Strategy 1: BB + RSI Strict
            if row['close'] > row['bb_upper'] and row['close'] > row['open'] and row['rsi14'] < 65:
                df.loc[i, 'sig_1'] = 'call'
            elif row['close'] < row['bb_lower'] and row['close'] < row['open'] and row['rsi14'] > 35:
                df.loc[i, 'sig_1'] = 'put'
                
            # Strategy 2: MACD Trend Strict
            if row['close'] > row['ema100'] and row['histogram'] > 0 and row['histogram'] > (prev['histogram'] * 1.2):
                df.loc[i, 'sig_2'] = 'call'
            elif row['close'] < row['ema100'] and row['histogram'] < 0 and row['histogram'] < (prev['histogram'] * 1.2):
                df.loc[i, 'sig_2'] = 'put'

        # Strategy 3: RSI Extreme Strict
        if row['rsi14'] < 18:
            df.loc[i, 'sig_3'] = 'call'
        elif row['rsi14'] > 82:
            df.loc[i, 'sig_3'] = 'put'

        # Strategy 4: EMA Cross Strict (9/21 with ADX > 25)
        ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i]
        ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i]
        prev_ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[i-1]
        prev_ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[i-1]
        if ema9 > ema21 and prev_ema9 <= prev_ema21 and row['adx'] > 25:
            df.loc[i, 'sig_4'] = 'call'
        elif ema9 < ema21 and prev_ema9 >= prev_ema21 and row['adx'] > 25:
            df.loc[i, 'sig_4'] = 'put'


        # --- STRATEGIES 5 TO 7 (From Optimized Code 2) ---

        # Strategy 5: Breakout with Candle Close & Body Size Confirmation (>= 1.5x avg body)
        max_high_25 = df['high'].iloc[i-25:i].max()
        min_low_25 = df['low'].iloc[i-25:i].min()
        if row['close'] > max_high_25 and row['body_size'] >= (1.5 * row['avg_body']) and row['close'] > row['open']:
            df.loc[i, 'sig_5'] = 'call'
        elif row['close'] < min_low_25 and row['body_size'] >= (1.5 * row['avg_body']) and row['close'] < row['open']:
            df.loc[i, 'sig_5'] = 'put'

        # Strategy 6: Stochastic Midline Continuation (%K crosses 50 with EMA 100 trend)
        low14 = df['low'].iloc[i-14:i].min()
        high14 = df['high'].iloc[i-14:i].max()
        k = 100 * ((row['close'] - low14) / (high14 - low14 + 1e-9))
        prev_low14 = df['low'].iloc[i-15:i-1].min()
        prev_high14 = df['high'].iloc[i-15:i-1].max()
        prev_k = 100 * ((prev['close'] - prev_low14) / (prev_high14 - prev_low14 + 1e-9))
        
        if row['close'] > row['ema100'] and prev_k <= 50 and k > 50:
            df.loc[i, 'sig_6'] = 'call'
        elif row['close'] < row['ema100'] and prev_k >= 50 and k < 50:
            df.loc[i, 'sig_6'] = 'put'

        # Strategy 7: MA Pullback with Rejection Wick (Pin bar style at SMA 50)
        sma50_val = df['close'].rolling(50).mean().iloc[i]
        lower_wick = min(row['open'], row['close']) - row['low']
        upper_wick = row['high'] - max(row['open'], row['close'])
        
        if row['close'] > sma50_val and row['low'] <= sma50_val and lower_wick > row['body_size']:
            df.loc[i, 'sig_7'] = 'call'
        elif row['close'] < sma50_val and row['high'] >= sma50_val and upper_wick > row['body_size']:
            df.loc[i, 'sig_7'] = 'put'

    return df

# ============================================================
# MASTER BACKTEST EXECUTION
# ============================================================

def run_master_backtest():
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message("🔥 <b>Master Hybrid Backtest Started</b>\nRunning Strict 1-4 + Optimized 5-7...")

    strategy_names = {
        1: "Strategy 1 (BB + RSI Strict)",
        2: "Strategy 2 (MACD Trend Strict)",
        3: "Strategy 3 (RSI Extreme Strict)",
        4: "Strategy 4 (EMA Cross Strict)",
        5: "Strategy 5 (Confirmed Breakout)",
        6: "Strategy 6 (Stochastic Midline)",
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
        logger.info("Fetching historical data for %s...", pair)
        candles = API.get_candles(pair, 60, 6000, time.time())
        if not candles or len(candles) < 150:
            continue
            
        df = evaluate_master_strategy_signals(candles)

        for i in range(100, len(df) - 1):
            for s_id in range(1, 8):
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

    report_lines = ["🔥 <b>FIREFLY MASTER BACKTEST RESULTS</b>\n"]
    
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
    logger.info("Master backtest complete. Report dispatched to Telegram.")

if __name__ == "__main__":
    run_master_backtest()