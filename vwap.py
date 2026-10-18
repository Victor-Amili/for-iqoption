import os
import sys
import time
import json
import logging
import urllib.parse
import urllib.request

import pandas as pd
from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option
import iqoptionapi.stable_api as stable_api

load_dotenv()

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STARTING_BALANCE = 10.0 
FLAT_STAKE = 1.00        # Flat $1.00 stake for clean win rate tracking
PAYOUT_RATE = 0.82

OTC_PAIRS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "GBPJPY-OTC",
]

TIMEFRAME_SEC = 300      # 5-Minute timeframe
TIMEFRAME_NAME = "5-Minute"

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
logger = logging.getLogger("FIREFLY-EMA-SURGE")

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
        logger.error("Failed to send Telegram notification: %exc")

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

def fetch_candle_history(pair, timeframe, total_needed=5000):
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

def generate_signals(candles, pair_name):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low', 'from']:
        df[col] = df[col].astype(float)
        
    # Moving Averages
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

    signals = []
    
    # Start after indicators have warmed up (index >= 50)
    for i in range(50, len(df) - 1):
        prev = df.iloc[i-1]
        curr = df.iloc[i]
        
        is_bullish_trend = curr['close'] > curr['ema50']
        is_bearish_trend = curr['close'] < curr['ema50']
        
        # Pullback condition: previous candle touched or crossed EMA 20
        pulled_back_to_ema20 = (prev['low'] <= prev['ema20']) if is_bullish_trend else (prev['high'] >= prev['ema20'])
        
        entry_time = df.loc[i+1, 'from']
        exit_close = df.loc[i+1, 'close']
        entry_close = curr['close']
        
        # Bullish Surge (Call)
        if is_bullish_trend and pulled_back_to_ema20:
            is_green_surge = (curr['close'] > curr['open']) and (curr['close'] > prev['high'])
            if is_green_surge:
                signals.append({
                    "timestamp": entry_time,
                    "pair": pair_name,
                    "action": "call",
                    "is_win": exit_close > entry_close
                })
                
        # Bearish Surge (Put)
        elif is_bearish_trend and pulled_back_to_ema20:
            is_red_surge = (curr['close'] < curr['open']) and (curr['close'] < prev['low'])
            if is_red_surge:
                signals.append({
                    "timestamp": entry_time,
                    "pair": pair_name,
                    "action": "put",
                    "is_win": exit_close < entry_close
                })
                
    return signals

def run_backtest():
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message("🌊 <b>5,000-Candle EMA Pullback Surge Backtest Started</b>\nTimeframe: 5-Minute | Stake: Flat $1.00...")

    report_lines = ["🌊 <b>EMA PULLBACK SURGE RESULTS (5M)</b>\n"]

    all_signals = []
    for pair in OTC_PAIRS:
        candles = fetch_candle_history(pair, TIMEFRAME_SEC, total_needed=5000)
        if not candles or len(candles) < 100:
            continue
        pair_signals = generate_signals(candles, pair)
        all_signals.extend(pair_signals)
        
    all_signals.sort(key=lambda x: x["timestamp"])
    
    balance = STARTING_BALANCE
    trades_taken = 0
    wins = 0
    losses = 0
    active_trades = []
    
    for sig in all_signals:
        sig_time = sig["timestamp"]
        active_trades = [exp for exp in active_trades if exp > sig_time]
        
        if len(active_trades) < 2 and balance >= FLAT_STAKE:
            trades_taken += 1
            active_trades.append(sig_time + TIMEFRAME_SEC)
            
            if sig["is_win"]:
                wins += 1
                balance += FLAT_STAKE * PAYOUT_RATE
            else:
                losses += 1
                balance -= FLAT_STAKE

    win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0.0
    profit = balance - STARTING_BALANCE
    
    report_lines.append(
        f"<b>EMA Pullback Surge Strategy</b>\n"
        f"• Trades Taken: {trades_taken} | Wins: {wins} | Losses: {losses}\n"
        f"• Win Rate: <b>{win_rate:.2f}%</b>\n"
        f"• Final Balance: <b>${balance:.2f}</b> (P/L: ${profit:+.2f})\n"
        f"-----------------------------------"
    )

    send_telegram_message("\n".join(report_lines))
    logger.info("EMA pullback surge backtest complete.")

if __name__ == "__main__":
    run_backtest()