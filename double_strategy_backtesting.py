import os
import sys
import time
import logging
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option
import iqoptionapi.stable_api as stable_api

load_dotenv()

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")

OTC_PAIRS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "GBPJPY-OTC",
]

INITIAL_BALANCE = 1000.0  # Starting virtual balance for backtest
BASE_STAKE = 40.0
MARTINGALE_MULTIPLIER = 2.0
PAYOUT_RATE = 0.82  # Estimated average OTC payout (82%)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("FIREFLY-BACKTEST")

def connect_iq():
    logger.info("Connecting to IQ Option for historical data...")
    api = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
    check, reason = api.connect()
    if not check:
        logger.error("Connection failed: %s", reason)
        return None
    api.change_balance("PRACTICE")
    logger.info("Connected successfully.")
    return api

def refresh_mappings(api):
    api.api.api_option_init_all_result = None
    api.api.get_api_option_init_all()
    start = time.time()
    while api.api.api_option_init_all_result is None and time.time() - start < 30:
        time.sleep(0.1)
    result = api.api.api_option_init_all_result
    if result and result.get("isSuccessful"):
        result_data = result.get("result", {})
        for market_type in ("binary", "turbo"):
            actives = result_data.get(market_type, {}).get("actives", {})
            for active_id, active_data in actives.items():
                raw_name = active_data.get("name", "")
                asset_name = raw_name.split(".", 1)[1] if "." in raw_name else raw_name
                if asset_name in OTC_PAIRS:
                    stable_api.OP_code.ACTIVES[asset_name] = int(active_id)

# ============================================================
# INDICATOR CALCULATION HELPERS
# ============================================================

def calc_strategy_1_df(candles):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low']:
        df[col] = df[col].astype(float)
        
    # Bollinger Bands (20, 2)
    period = 20
    df['sma20'] = df['close'].rolling(window=period).mean()
    df['std20'] = df['close'].rolling(window=period).std()
    df['bb_upper'] = df['sma20'] + (2.0 * df['std20'])
    df['bb_lower'] = df['sma20'] - (2.0 * df['std20'])
    
    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi14'] = 100 - (100 / (1 + rs))
    return df

def calc_strategy_2_df(candles):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low']:
        df[col] = df[col].astype(float)
        
    # 100 EMA
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    
    # MACD (10, 22, 9)
    ema10 = df['close'].ewm(span=10, adjust=False).mean()
    ema22 = df['close'].ewm(span=22, adjust=False).mean()
    df['macd_line'] = ema10 - ema22
    df['signal_line'] = df['macd_line'].ewm(span=9, adjust=False).mean()
    df['histogram'] = df['macd_line'] - df['signal_line']
    
    # SuperTrend (10, 3)
    period = 10
    multiplier = 3.0
    hl2 = (df['high'] + df['low']) / 2
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    
    upper_basic = hl2 + (multiplier * atr)
    lower_basic = hl2 - (multiplier * atr)
    
    upper_band = [0.0] * len(df)
    lower_band = [0.0] * len(df)
    super_trend = [0.0] * len(df)
    direction = [1] * len(df)
    
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
            else:
                direction[i] = 1
        else:
            if df['close'].iloc[i] > upper_band[i]:
                direction[i] = 1
            else:
                direction[i] = -1
                
    df['super_dir'] = direction
    
    # Vortex Indicator (14)
    v_period = 14
    vm_plus = (df['high'] - df['low'].shift(1)).abs()
    vm_minus = (df['low'] - df['high'].shift(1)).abs()
    sum_tr = tr.rolling(v_period).sum()
    sum_vm_plus = vm_plus.rolling(v_period).sum()
    sum_vm_minus = vm_minus.rolling(v_period).sum()
    df['vi_plus'] = sum_vm_plus / sum_tr
    df['vi_minus'] = sum_vm_minus / sum_tr
    
    return df

# ============================================================
# BACKTEST EXECUTION ENGINE
# ============================================================

def run_backtest_for_strategy(api, strategy_num):
    logger.info("==============================================")
    logger.info("RUNNING BACKTEST FOR STRATEGY %d", strategy_num)
    logger.info("==============================================")
    
    balance = INITIAL_BALANCE
    total_trades = 0
    wins = 0
    losses = 0
    martingale_wins = 0
    martingale_losses = 0
    
    duration = 1 if strategy_num == 1 else 5
    
    for pair in OTC_PAIRS:
        logger.info("Fetching historical candles for %s...", pair)
        # Fetching maximum allowable candles (e.g., 1000 candles)
        candles = api.get_candles(pair, 60, 1000, time.time())
        if not candles or len(candles) < 150:
            logger.warning("Insufficient data for %s", pair)
            continue
            
        if strategy_num == 1:
            df = calc_strategy_1_df(candles)
        else:
            df = calc_strategy_2_df(candles)
            
        i = 120  # Start after indicator warm-up period
        while i < len(df) - duration:
            row = df.iloc[i]
            signal = None
            
            # Strategy 1 Signal Logic
            if strategy_num == 1:
                if row['close'] > row['bb_upper'] and row['close'] > row['open'] and row['rsi14'] < 70:
                    signal = "call"
                elif row['close'] < row['bb_lower'] and row['close'] < row['open'] and row['rsi14'] > 30:
                    signal = "put"
            
            # Strategy 2 Signal Logic
            elif strategy_num == 2:
                prev = df.iloc[i-1]
                # Check MACD histogram count condition
                hist_count = 0
                for idx in range(i, -1, -1):
                    h = df['histogram'].iloc[idx]
                    if (h > 0 and row['histogram'] > 0) or (h < 0 and row['histogram'] < 0):
                        hist_count += 1
                    else:
                        break
                        
                if hist_count <= 5:
                    if (row['close'] > row['ema100'] and row['super_dir'] == 1 and 
                        row['vi_plus'] > row['vi_minus'] and prev['vi_plus'] <= prev['vi_minus'] and 
                        row['histogram'] > 0 and row['histogram'] > prev['histogram']):
                        signal = "call"
                    elif (row['close'] < row['ema100'] and row['super_dir'] == -1 and 
                          row['vi_plus'] < row['vi_minus'] and prev['vi_plus'] >= prev['vi_minus'] and 
                          row['histogram'] < 0 and row['histogram'] < prev['histogram']):
                        signal = "put"
            
            if signal:
                total_trades += 1
                entry_price = row['close']
                exit_price = df.iloc[i + duration]['close']
                
                # Evaluate Base Trade
                base_win = False
                if signal == "call" and exit_price > entry_price:
                    base_win = True
                elif signal == "put" and exit_price < entry_price:
                    base_win = True
                
                if base_win:
                    wins += 1
                    balance += BASE_STAKE * PAYOUT_RATE
                    i += duration  # Skip ahead by expiry duration
                else:
                    losses += 1
                    balance -= BASE_STAKE
                    
                    # Deploy Martingale Step
                    mg_index = i + duration
                    if mg_index + duration < len(df):
                        mg_entry = df.iloc[mg_index]['close']
                        mg_exit = df.iloc[mg_index + duration]['close']
                        mg_stake = BASE_STAKE * MARTINGALE_MULTIPLIER
                        
                        mg_win = False
                        if signal == "call" and mg_exit > mg_entry:
                            mg_win = True
                        elif signal == "put" and mg_exit < mg_entry:
                            mg_win = True
                            
                        if mg_win:
                            martingale_wins += 1
                            balance += mg_stake * PAYOUT_RATE
                        else:
                            martingale_losses += 1
                            balance -= mg_stake
                            
                        i = mg_index + duration
                    else:
                        i += duration
            else:
                i += 1

    logger.info("--- STRATEGY %d RESULTS SUMMARY ---", strategy_num)
    logger.info("Total Signals Taken: %d", total_trades)
    logger.info("Base Wins: %d | Base Losses: %d", wins, losses)
    logger.info("Martingale Recoveries: %d | Unrecovered Sequences: %d", martingale_wins, martingale_losses)
    logger.info("Starting Balance: $%.2f", INITIAL_BALANCE)
    logger.info("Final Equity Balance: $%.2f (Net Profit: $%.2f)", balance, balance - INITIAL_BALANCE)
    logger.info("----------------------------------------------\n")

def main():
    api = connect_iq()
    if not api:
        return
    refresh_mappings(api)
    
    # Run backtests for both strategies
    run_backtest_for_strategy(api, strategy_num=1)
    run_backtest_for_strategy(api, strategy_num=2)

if __name__ == "__main__":
    main()