# import os
# import sys
# import time
# import logging
# import pandas as pd
# import numpy as np
# from dotenv import load_dotenv
# from iqoptionapi.stable_api import IQ_Option
# import iqoptionapi.stable_api as stable_api

# load_dotenv()

# OWNER_EMAIL = os.getenv("OWNER_EMAIL")
# OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")

# # Real binary currency pairs (non-OTC)
# REAL_PAIRS = [
#     "EURUSD",
#     "GBPUSD",
#     "USDJPY",
#     "AUDUSD",
# ]

# INITIAL_BALANCE = 1000.0  # Starting virtual balance for backtest
# BASE_STAKE = 40.0
# PAYOUT_RATE = 0.82  # Estimated average payout for real pairs

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s | %(levelname)s | %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S",
# )
# logger = logging.getLogger("FIREFLY-BACKTEST")

# def connect_iq():
#     logger.info("Connecting to IQ Option for historical data...")
#     api = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
#     check, reason = api.connect()
#     if not check:
#         logger.error("Connection failed: %s", reason)
#         return None
#     api.change_balance("PRACTICE")
#     logger.info("Connected successfully.")
#     return api

# def refresh_mappings(api):
#     api.api.api_option_init_all_result = None
#     api.api.get_api_option_init_all()
#     start = time.time()
#     while api.api.api_option_init_all_result is None and time.time() - start < 30:
#         time.sleep(0.1)
#     result = api.api.api_option_init_all_result
#     if result and result.get("isSuccessful"):
#         result_data = result.get("result", {})
#         for market_type in ("binary", "turbo"):
#             actives = result_data.get(market_type, {}).get("actives", {})
#             for active_id, active_data in actives.items():
#                 raw_name = active_data.get("name", "")
#                 asset_name = raw_name.split(".", 1)[1] if "." in raw_name else raw_name
#                 if asset_name in REAL_PAIRS:
#                     stable_api.OP_code.ACTIVES[asset_name] = int(active_id)

# # ============================================================
# # STRATEGY 2 INDICATOR CALCULATION HELPERS
# # ============================================================

# def calc_strategy_2_df(candles):
#     df = pd.DataFrame(candles)
#     df = df.rename(columns={'min': 'low', 'max': 'high'})
#     for col in ['open', 'close', 'high', 'low']:
#         df[col] = df[col].astype(float)
        
#     # 100 EMA
#     df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    
#     # MACD (10, 22, 9)
#     ema10 = df['close'].ewm(span=10, adjust=False).mean()
#     ema22 = df['close'].ewm(span=22, adjust=False).mean()
#     df['macd_line'] = ema10 - ema22
#     df['signal_line'] = df['macd_line'].ewm(span=9, adjust=False).mean()
#     df['histogram'] = df['macd_line'] - df['signal_line']
    
#     # SuperTrend (10, 3)
#     period = 10
#     multiplier = 3.0
#     hl2 = (df['high'] + df['low']) / 2
#     tr1 = df['high'] - df['low']
#     tr2 = (df['high'] - df['close'].shift(1)).abs()
#     tr3 = (df['low'] - df['close'].shift(1)).abs()
#     tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
#     atr = tr.ewm(span=period, adjust=False).mean()
    
#     upper_basic = hl2 + (multiplier * atr)
#     lower_basic = hl2 - (multiplier * atr)
    
#     upper_band = [0.0] * len(df)
#     lower_band = [0.0] * len(df)
#     direction = [1] * len(df)
    
#     for i in range(1, len(df)):
#         if df['close'].iloc[i] > upper_band[i-1]:
#             upper_band[i] = upper_basic.iloc[i]
#         else:
#             upper_band[i] = min(upper_basic.iloc[i], upper_band[i-1]) if upper_band[i-1] != 0 else upper_basic.iloc[i]
            
#         if df['close'].iloc[i] < lower_band[i]:
#             lower_band[i] = lower_basic.iloc[i]
#         else:
#             lower_band[i] = max(lower_basic.iloc[i], lower_band[i-1]) if lower_band[i-1] != 0 else lower_basic.iloc[i]
            
#         if direction[i-1] == 1:
#             if df['close'].iloc[i] < lower_band[i]:
#                 direction[i] = -1
#             else:
#                 direction[i] = 1
#         else:
#             if df['close'].iloc[i] > upper_band[i]:
#                 direction[i] = 1
#             else:
#                 direction[i] = -1
                
#     df['super_dir'] = direction
    
#     # Vortex Indicator (14)
#     v_period = 14
#     vm_plus = (df['high'] - df['low'].shift(1)).abs()
#     vm_minus = (df['low'] - df['high'].shift(1)).abs()
#     sum_tr = tr.rolling(v_period).sum()
#     sum_vm_plus = vm_plus.rolling(v_period).sum()
#     sum_vm_minus = vm_minus.rolling(v_period).sum()
#     df['vi_plus'] = sum_vm_plus / sum_tr
#     df['vi_minus'] = sum_vm_minus / sum_tr
    
#     return df

# # ============================================================
# # BACKTEST EXECUTION ENGINE (STRATEGY 2 ONLY)
# # ============================================================

# def run_strategy_2_backtest(api):
#     logger.info("==============================================")
#     logger.info("RUNNING BACKTEST FOR STRATEGY 2 (REAL PAIRS - NO MG)")
#     logger.info("==============================================")
    
#     balance = INITIAL_BALANCE
#     total_trades = 0
#     wins = 0
#     losses = 0
#     duration = 5  # 5-minute expiry
    
#     for pair in REAL_PAIRS:
#         logger.info("Fetching historical candles for %s...", pair)
#         candles = api.get_candles(pair, 60, 1000, time.time())
#         if not candles or len(candles) < 150:
#             logger.warning("Insufficient data for %s", pair)
#             continue
            
#         df = calc_strategy_2_df(candles)
#         i = 120  # Start after indicator warm-up period
        
#         while i < len(df) - duration:
#             row = df.iloc[i]
#             prev = df.iloc[i-1]
#             signal = None
            
#             # Check MACD histogram count condition
#             hist_count = 0
#             for idx in range(i, -1, -1):
#                 h = df['histogram'].iloc[idx]
#                 if (h > 0 and row['histogram'] > 0) or (h < 0 and row['histogram'] < 0):
#                     hist_count += 1
#                 else:
#                     break
                    
#             if hist_count <= 5:
#                 if (row['close'] > row['ema100'] and row['super_dir'] == 1 and 
#                     row['vi_plus'] > row['vi_minus'] and prev['vi_plus'] <= prev['vi_minus'] and 
#                     row['histogram'] > 0 and row['histogram'] > prev['histogram']):
#                     signal = "call"
#                 elif (row['close'] < row['ema100'] and row['super_dir'] == -1 and 
#                       row['vi_plus'] < row['vi_minus'] and prev['vi_plus'] >= prev['vi_minus'] and 
#                       row['histogram'] < 0 and row['histogram'] < prev['histogram']):
#                     signal = "put"
            
#             if signal:
#                 total_trades += 1
#                 entry_price = row['close']
#                 exit_price = df.iloc[i + duration]['close']
                
#                 trade_win = False
#                 if signal == "call" and exit_price > entry_price:
#                     trade_win = True
#                 elif signal == "put" and exit_price < entry_price:
#                     trade_win = True
                
#                 if trade_win:
#                     wins += 1
#                     balance += BASE_STAKE * PAYOUT_RATE
#                 else:
#                     losses += 1
#                     balance -= BASE_STAKE
                
#                 # Advance forward by trade duration
#                 i += duration
#             else:
#                 i += 1

#     win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

#     logger.info("--- STRATEGY 2 RESULTS SUMMARY (REAL PAIRS) ---")
#     logger.info("Total Trades Taken: %d", total_trades)
#     logger.info("Wins: %d | Losses: %d", wins, losses)
#     logger.info("Win Rate: %.2f%%", win_rate)
#     logger.info("Starting Balance: $%.2f", INITIAL_BALANCE)
#     logger.info("Final Equity Balance: $%.2f (Net Profit: $%.2f)", balance, balance - INITIAL_BALANCE)
#     logger.info("----------------------------------------------------\n")

# def main():
#     api = connect_iq()
#     if not api:
#         return
#     refresh_mappings(api)
    
#     run_strategy_2_backtest(api)

# if __name__ == "__main__":
#     main()

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

REAL_PAIRS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
]

INITIAL_BALANCE = 1000.0
BASE_STAKE = 40.0
PAYOUT_RATE = 0.82

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
                if asset_name in REAL_PAIRS:
                    stable_api.OP_code.ACTIVES[asset_name] = int(active_id)

def fetch_deep_candles(api, pair, total_target=5000):
    """Paginates backward in time to fetch deeper historical candles past API limits."""
    all_candles = []
    end_from = time.time()
    chunk_size = 1000
    
    logger.info("Fetching target of %d candles for %s via pagination...", total_target, pair)
    while len(all_candles) < total_target:
        candles = api.get_candles(pair, 60, chunk_size, end_from)
        if not candles or len(candles) <= 1:
            break
        
        # Avoid duplicate overlapping candles
        if all_candles and candles[-1]['from'] == all_candles[0]['from']:
            break
            
        all_candles = candles + all_candles
        end_from = candles[0]['from']  # Shift back-time window to the oldest candle received
        time.sleep(0.5)  # Throttle to prevent rate limits
        
        if len(candles) < chunk_size:
            break # Reached the broker's maximum history depth for this asset

    logger.info("Successfully gathered %d candles for %s.", len(all_candles), pair)
    return all_candles

# ============================================================
# INDICATORS & ENGINE
# ============================================================

def calc_strategy_2_df(candles):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low']:
        df[col] = df[col].astype(float)
        
    df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
    
    ema10 = df['close'].ewm(span=10, adjust=False).mean()
    ema22 = df['close'].ewm(span=22, adjust=False).mean()
    df['macd_line'] = ema10 - ema22
    df['signal_line'] = df['macd_line'].ewm(span=9, adjust=False).mean()
    df['histogram'] = df['macd_line'] - df['signal_line']
    
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
    
    v_period = 14
    vm_plus = (df['high'] - df['low'].shift(1)).abs()
    vm_minus = (df['low'] - df['high'].shift(1)).abs()
    sum_tr = tr.rolling(v_period).sum()
    sum_vm_plus = vm_plus.rolling(v_period).sum()
    sum_vm_minus = vm_minus.rolling(v_period).sum()
    df['vi_plus'] = sum_vm_plus / sum_tr
    df['vi_minus'] = sum_vm_minus / sum_tr
    
    return df

def run_strategy_2_backtest(api):
    logger.info("==============================================")
    logger.info("RUNNING DEEP 5000-CANDLE BACKTEST (PAGINATED)")
    logger.info("==============================================")
    
    balance = INITIAL_BALANCE
    total_trades = 0
    wins = 0
    losses = 0
    duration = 5
    
    for pair in REAL_PAIRS:
        candles = fetch_deep_candles(api, pair, total_target=5000)
        if not candles or len(candles) < 150:
            logger.warning("Insufficient data for %s", pair)
            continue
            
        df = calc_strategy_2_df(candles)
        i = 120
        
        while i < len(df) - duration:
            row = df.iloc[i]
            prev = df.iloc[i-1]
            signal = None
            
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
                
                trade_win = False
                if signal == "call" and exit_price > entry_price:
                    trade_win = True
                elif signal == "put" and exit_price < entry_price:
                    trade_win = True
                
                if trade_win:
                    wins += 1
                    balance += BASE_STAKE * PAYOUT_RATE
                else:
                    losses += 1
                    balance -= BASE_STAKE
                
                i += duration
            else:
                i += 1

    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0

    logger.info("--- DEEP BACKTEST RESULTS SUMMARY ---")
    logger.info("Total Trades Taken: %d", total_trades)
    logger.info("Wins: %d | Losses: %d", wins, losses)
    logger.info("Win Rate: %.2f%%", win_rate)
    logger.info("Starting Balance: $%.2f", INITIAL_BALANCE)
    logger.info("Final Equity Balance: $%.2f (Net Profit: $%.2f)", balance, balance - INITIAL_BALANCE)
    logger.info("-------------------------------------\n")

def main():
    api = connect_iq()
    if not api:
        return
    refresh_mappings(api)
    run_strategy_2_backtest(api)

if __name__ == "__main__":
    main()