# # # # # # import os
# # # # # # import sys
# # # # # # import time
# # # # # # import json
# # # # # # import logging
# # # # # # import urllib.parse
# # # # # # import urllib.request

# # # # # # import pandas as pd
# # # # # # import numpy as np
# # # # # # from dotenv import load_dotenv
# # # # # # from iqoptionapi.stable_api import IQ_Option
# # # # # # import iqoptionapi.stable_api as stable_api

# # # # # # load_dotenv()

# # # # # # OWNER_EMAIL = os.getenv("OWNER_EMAIL")
# # # # # # OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
# # # # # # TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# # # # # # TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# # # # # # STARTING_BALANCE = 10.0 
# # # # # # STAKE_PERCENTAGE = 0.10  # 10% of current balance per trade
# # # # # # PAYOUT_RATE = 0.82

# # # # # # OTC_PAIRS = [
# # # # # #     "USDJPY-OTC",
# # # # # #     "AUDUSD-OTC",
# # # # # #     "EURJPY-OTC",
# # # # # #     "GBPJPY-OTC",
# # # # # # ]

# # # # # # TIMEFRAMES = {
# # # # # #     60: "1-Minute",
# # # # # #     300: "5-Minute",
# # # # # #     900: "15-Minute"
# # # # # # }

# # # # # # for var_name, val in [
# # # # # #     ("OWNER_EMAIL", OWNER_EMAIL),
# # # # # #     ("OWNER_PASSWORD", OWNER_PASSWORD),
# # # # # #     ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
# # # # # #     ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
# # # # # # ]:
# # # # # #     if not val:
# # # # # #         print(f"ERROR: {var_name} is missing from .env")
# # # # # #         sys.exit(1)

# # # # # # logging.basicConfig(
# # # # # #     level=logging.INFO,
# # # # # #     format="%(asctime)s | %(levelname)s | %(message)s",
# # # # # #     datefmt="%Y-%m-%d %H:%M:%S",
# # # # # # )
# # # # # # logger = logging.getLogger("FIREFLY-4STREAK-RSI")

# # # # # # API = None

# # # # # # def send_telegram_message(message):
# # # # # #     url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
# # # # # #     payload = urllib.parse.urlencode({
# # # # # #         "chat_id": TELEGRAM_CHAT_ID,
# # # # # #         "text": message,
# # # # # #         "parse_mode": "HTML"
# # # # # #     }).encode("utf-8")
# # # # # #     try:
# # # # # #         req = urllib.request.Request(url, data=payload, method="POST")
# # # # # #         with urllib.request.urlopen(req, timeout=10) as response:
# # # # # #             res = json.loads(response.read().decode("utf-8"))
# # # # # #             if not res.get("ok"):
# # # # # #                 logger.error("Telegram API rejection: %s", res)
# # # # # #     except Exception as exc:
# # # # # #         logger.error("Failed to send Telegram notification: %s", exc)

# # # # # # def connect_iq_option():
# # # # # #     global API
# # # # # #     logger.info("Connecting to IQ Option...")
# # # # # #     API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
# # # # # #     check, reason = API.connect()
# # # # # #     if not check:
# # # # # #         logger.error("Connection failed: %s", reason)
# # # # # #         return False
# # # # # #     logger.info("Connected successfully.")
# # # # # #     return True

# # # # # # def refresh_otc_mappings():
# # # # # #     if API is None:
# # # # # #         return False
# # # # # #     API.api.api_option_init_all_result = None
# # # # # #     API.api.get_api_option_init_all()
# # # # # #     start = time.time()
# # # # # #     while API.api.api_option_init_all_result is None and time.time() - start < 30:
# # # # # #         time.sleep(0.1)
        
# # # # # #     result = API.api.api_option_init_all_result
# # # # # #     if result and result.get("isSuccessful"):
# # # # # #         result_data = result.get("result", {})
# # # # # #         for market_type in ("binary", "turbo"):
# # # # # #             actives = result_data.get(market_type, {}).get("actives", {})
# # # # # #             for active_id, active_data in actives.items():
# # # # # #                 raw_name = active_data.get("name", "")
# # # # # #                 asset_name = raw_name.split(".", 1)[1] if "." in raw_name else raw_name
# # # # # #                 if asset_name in OTC_PAIRS:
# # # # # #                     stable_api.OP_code.ACTIVES[asset_name] = int(active_id)
# # # # # #     return True

# # # # # # def fetch_candle_history(pair, timeframe, total_needed=5000):
# # # # # #     all_candles = []
# # # # # #     end_time = time.time()
# # # # # #     chunk_size = 1000
    
# # # # # #     while len(all_candles) < total_needed:
# # # # # #         remaining = total_needed - len(all_candles)
# # # # # #         current_count = min(chunk_size, remaining)
        
# # # # # #         logger.info(f"Fetching chunk for {pair} ({timeframe}s) - Current total: {len(all_candles)}/{total_needed}")
# # # # # #         candles = API.get_candles(pair, timeframe, current_count, end_time)
# # # # # #         if not candles:
# # # # # #             break
            
# # # # # #         all_candles = candles + all_candles
# # # # # #         end_time = candles[0]['from'] - 1
# # # # # #         time.sleep(0.2)
        
# # # # # #     return all_candles

# # # # # # # ============================================================
# # # # # # # 4-CANDLE STREAK + RSI FILTER SIGNAL GENERATION
# # # # # # # ============================================================

# # # # # # def generate_signals_for_pair(candles, pair_name):
# # # # # #     df = pd.DataFrame(candles)
# # # # # #     df = df.rename(columns={'min': 'low', 'max': 'high'})
# # # # # #     for col in ['open', 'close', 'high', 'low', 'from']:
# # # # # #         df[col] = df[col].astype(float)
        
# # # # # #     # Calculate 14-period RSI (Wilder's smoothing)
# # # # # #     delta = df['close'].diff()
# # # # # #     gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
# # # # # #     loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
# # # # # #     rs = gain / (loss + 1e-9)
# # # # # #     df['rsi'] = 100 - (100 / (1 + rs))

# # # # # #     signals = []
# # # # # #     green_streak_active = False
# # # # # #     red_streak_active = False
    
# # # # # #     for i in range(15, len(df) - 1): # Start after RSI has warmed up (15+ periods)
# # # # # #         c0 = df.iloc[i-3]
# # # # # #         c1 = df.iloc[i-2]
# # # # # #         c2 = df.iloc[i-1]
# # # # # #         c3 = df.iloc[i]
        
# # # # # #         is_c0_green = c0['close'] > c0['open']
# # # # # #         is_c1_green = c1['close'] > c1['open']
# # # # # #         is_c2_green = c2['close'] > c2['open']
# # # # # #         is_c3_green = c3['close'] > c3['open']
        
# # # # # #         is_c0_red = c0['close'] < c0['open']
# # # # # #         is_c1_red = c1['close'] < c1['open']
# # # # # #         is_c2_red = c2['close'] < c2['open']
# # # # # #         is_c3_red = c3['close'] < c3['open']
        
# # # # # #         current_rsi = c3['rsi']
# # # # # #         entry_time = df.loc[i+1, 'from']
# # # # # #         entry_close = c3['close']
# # # # # #         exit_close = df.loc[i+1, 'close']
        
# # # # # #         # Check for 4 Green Candles -> Call Signal (Filtered by RSI <= 75)
# # # # # #         if is_c0_green and is_c1_green and is_c2_green and is_c3_green:
# # # # # #             if not green_streak_active:
# # # # # #                 if current_rsi <= 75:  # Filter out overbought entries
# # # # # #                     signals.append({
# # # # # #                         "timestamp": entry_time,
# # # # # #                         "pair": pair_name,
# # # # # #                         "action": "call",
# # # # # #                         "entry_price": entry_close,
# # # # # #                         "exit_price": exit_close,
# # # # # #                         "is_win": exit_close > entry_close
# # # # # #                     })
# # # # # #                 green_streak_active = True
# # # # # #         else:
# # # # # #             green_streak_active = False
            
# # # # # #         # Check for 4 Red Candles -> Put Signal (Filtered by RSI >= 25)
# # # # # #         if is_c0_red and is_c1_red and is_c2_red and is_c3_red:
# # # # # #             if not red_streak_active:
# # # # # #                 if current_rsi >= 25:  # Filter out oversold entries
# # # # # #                     signals.append({
# # # # # #                         "timestamp": entry_time,
# # # # # #                         "pair": pair_name,
# # # # # #                         "action": "put",
# # # # # #                         "entry_price": entry_close,
# # # # # #                         "exit_price": exit_close,
# # # # # #                         "is_win": exit_close < entry_close
# # # # # #                     })
# # # # # #                 red_streak_active = True
# # # # # #         else:
# # # # # #             red_streak_active = False
            
# # # # # #     return signals

# # # # # # def run_backtest():
# # # # # #     if not connect_iq_option():
# # # # # #         return
# # # # # #     refresh_otc_mappings()
    
# # # # # #     send_telegram_message("🚀 <b>5,000-Candle 4-Streak + RSI Filter Backtest Started</b>\nStarting Balance: $10.00 | Stake: 10% Compounding | RSI Thresholds: 25 / 75...")

# # # # # #     report_lines = ["🚀 <b>4-STREAK + RSI FILTER BACKTEST RESULTS</b>\n"]

# # # # # #     for tf_sec, tf_name in TIMEFRAMES.items():
# # # # # #         logger.info("Evaluating Timeframe: %s (5k candles with RSI filter)", tf_name)
        
# # # # # #         all_signals = []
# # # # # #         for pair in OTC_PAIRS:
# # # # # #             candles = fetch_candle_history(pair, tf_sec, total_needed=5000)
# # # # # #             if not candles or len(candles) < 100:
# # # # # #                 continue
# # # # # #             pair_signals = generate_signals_for_pair(candles, pair)
# # # # # #             all_signals.extend(pair_signals)
            
# # # # # #         # Sort chronologically across all pairs for global concurrency management
# # # # # #         all_signals.sort(key=lambda x: x["timestamp"])
        
# # # # # #         balance = STARTING_BALANCE
# # # # # #         trades_taken = 0
# # # # # #         wins = 0
# # # # # #         losses = 0
# # # # # #         active_trades = []
# # # # # #         duration_seconds = tf_sec
        
# # # # # #         for sig in all_signals:
# # # # # #             sig_time = sig["timestamp"]
            
# # # # # #             # Remove expired active trades
# # # # # #             active_trades = [exp for exp in active_trades if exp > sig_time]
            
# # # # # #             if len(active_trades) < 2 and balance > 0.5:
# # # # # #                 trades_taken += 1
# # # # # #                 active_trades.append(sig_time + duration_seconds)
                
# # # # # #                 stake = balance * STAKE_PERCENTAGE
# # # # # #                 if sig["is_win"]:
# # # # # #                     wins += 1
# # # # # #                     balance += stake * PAYOUT_RATE
# # # # # #                 else:
# # # # # #                     losses += 1
# # # # # #                     balance -= stake

# # # # # #         win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0.0
# # # # # #         profit = balance - STARTING_BALANCE
        
# # # # # #         report_lines.append(
# # # # # #             f"<b>Timeframe: {tf_name}</b>\n"
# # # # # #             f"• Trades Taken: {trades_taken} | Wins: {wins} | Losses: {losses}\n"
# # # # # #             f"• Win Rate: <b>{win_rate:.2f}%</b>\n"
# # # # # #             f"• Final Balance: <b>${balance:.2f}</b> (P/L: ${profit:+.2f})\n"
# # # # # #             f"-----------------------------------"
# # # # # #         )

# # # # # #     send_telegram_message("\n".join(report_lines))
# # # # # #     logger.info("4-streak + RSI filter backtest complete. Dispatched to Telegram.")

# # # # # # if __name__ == "__main__":
# # # # # #     run_backtest()
# # # # # import os
# # # # # import sys
# # # # # import time
# # # # # import json
# # # # # import logging
# # # # # import urllib.parse
# # # # # import urllib.request

# # # # # import pandas as pd
# # # # # import numpy as np
# # # # # from dotenv import load_dotenv
# # # # # from iqoptionapi.stable_api import IQ_Option
# # # # # import iqoptionapi.stable_api as stable_api

# # # # # load_dotenv()

# # # # # OWNER_EMAIL = os.getenv("OWNER_EMAIL")
# # # # # OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
# # # # # TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# # # # # TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# # # # # STARTING_BALANCE = 10.0 
# # # # # STAKE_PERCENTAGE = 0.10  # 10% of current balance per trade
# # # # # PAYOUT_RATE = 0.82

# # # # # OTC_PAIRS = [
# # # # #     "USDJPY-OTC",
# # # # #     "AUDUSD-OTC",
# # # # #     "EURJPY-OTC",
# # # # #     "GBPJPY-OTC",
# # # # # ]

# # # # # TIMEFRAMES = {
# # # # #     60: "1-Minute",
# # # # #     300: "5-Minute",
# # # # #     900: "15-Minute"
# # # # # }

# # # # # for var_name, val in [
# # # # #     ("OWNER_EMAIL", OWNER_EMAIL),
# # # # #     ("OWNER_PASSWORD", OWNER_PASSWORD),
# # # # #     ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
# # # # #     ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
# # # # # ]:
# # # # #     if not val:
# # # # #         print(f"ERROR: {var_name} is missing from .env")
# # # # #         sys.exit(1)

# # # # # logging.basicConfig(
# # # # #     level=logging.INFO,
# # # # #     format="%(asctime)s | %(levelname)s | %(message)s",
# # # # #     datefmt="%Y-%m-%d %H:%M:%S",
# # # # # )
# # # # # logger = logging.getLogger("FIREFLY-4STREAK-EMA")

# # # # # API = None

# # # # # def send_telegram_message(message):
# # # # #     url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
# # # # #     payload = urllib.parse.urlencode({
# # # # #         "chat_id": TELEGRAM_CHAT_ID,
# # # # #         "text": message,
# # # # #         "parse_mode": "HTML"
# # # # #     }).encode("utf-8")
# # # # #     try:
# # # # #         req = urllib.request.Request(url, data=payload, method="POST")
# # # # #         with urllib.request.urlopen(req, timeout=10) as response:
# # # # #             res = json.loads(response.read().decode("utf-8"))
# # # # #             if not res.get("ok"):
# # # # #                 logger.error("Telegram API rejection: %s", res)
# # # # #     except Exception as exc:
# # # # #         logger.error("Failed to send Telegram notification: %s", exc)

# # # # # def connect_iq_option():
# # # # #     global API
# # # # #     logger.info("Connecting to IQ Option...")
# # # # #     API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
# # # # #     check, reason = API.connect()
# # # # #     if not check:
# # # # #         logger.error("Connection failed: %s", reason)
# # # # #         return False
# # # # #     logger.info("Connected successfully.")
# # # # #     return True

# # # # # def refresh_otc_mappings():
# # # # #     if API is None:
# # # # #         return False
# # # # #     API.api.api_option_init_all_result = None
# # # # #     API.api.get_api_option_init_all()
# # # # #     start = time.time()
# # # # #     while API.api.api_option_init_all_result is None and time.time() - start < 30:
# # # # #         time.sleep(0.1)
        
# # # # #     result = API.api.api_option_init_all_result
# # # # #     if result and result.get("isSuccessful"):
# # # # #         result_data = result.get("result", {})
# # # # #         for market_type in ("binary", "turbo"):
# # # # #             actives = result_data.get(market_type, {}).get("actives", {})
# # # # #             for active_id, active_data in actives.items():
# # # # #                 raw_name = active_data.get("name", "")
# # # # #                 asset_name = raw_name.split(".", 1)[1] if "." in raw_name else raw_name
# # # # #                 if asset_name in OTC_PAIRS:
# # # # #                     stable_api.OP_code.ACTIVES[asset_name] = int(active_id)
# # # # #     return True

# # # # # def fetch_candle_history(pair, timeframe, total_needed=5000):
# # # # #     all_candles = []
# # # # #     end_time = time.time()
# # # # #     chunk_size = 1000
    
# # # # #     while len(all_candles) < total_needed:
# # # # #         remaining = total_needed - len(all_candles)
# # # # #         current_count = min(chunk_size, remaining)
        
# # # # #         logger.info(f"Fetching chunk for {pair} ({timeframe}s) - Current total: {len(all_candles)}/{total_needed}")
# # # # #         candles = API.get_candles(pair, timeframe, current_count, end_time)
# # # # #         if not candles:
# # # # #             break
            
# # # # #         all_candles = candles + all_candles
# # # # #         end_time = candles[0]['from'] - 1
# # # # #         time.sleep(0.2)
        
# # # # #     return all_candles

# # # # # # ============================================================
# # # # # # 4-CANDLE STREAK + EMA 50 TREND FILTER SIGNAL GENERATION
# # # # # # ============================================================

# # # # # def generate_signals_for_pair(candles, pair_name):
# # # # #     df = pd.DataFrame(candles)
# # # # #     df = df.rename(columns={'min': 'low', 'max': 'high'})
# # # # #     for col in ['open', 'close', 'high', 'low', 'from']:
# # # # #         df[col] = df[col].astype(float)
        
# # # # #     # Calculate 50-period EMA
# # # # #     df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()

# # # # #     signals = []
# # # # #     green_streak_active = False
# # # # #     red_streak_active = False
    
# # # # #     for i in range(50, len(df) - 1): # Start after EMA 50 has warmed up
# # # # #         c0 = df.iloc[i-3]
# # # # #         c1 = df.iloc[i-2]
# # # # #         c2 = df.iloc[i-1]
# # # # #         c3 = df.iloc[i]
        
# # # # #         is_c0_green = c0['close'] > c0['open']
# # # # #         is_c1_green = c1['close'] > c1['open']
# # # # #         is_c2_green = c2['close'] > c2['open']
# # # # #         is_c3_green = c3['close'] > c3['open']
        
# # # # #         is_c0_red = c0['close'] < c0['open']
# # # # #         is_c1_red = c1['close'] < c1['open']
# # # # #         is_c2_red = c2['close'] < c2['open']
# # # # #         is_c3_red = c3['close'] < c3['open']
        
# # # # #         current_close = c3['close']
# # # # #         current_ema = c3['ema50']
        
# # # # #         entry_time = df.loc[i+1, 'from']
# # # # #         entry_close = current_close
# # # # #         exit_close = df.loc[i+1, 'close']
        
# # # # #         # Check for 4 Green Candles -> Call Signal (Filtered by price > EMA 50)
# # # # #         if is_c0_green and is_c1_green and is_c2_green and is_c3_green:
# # # # #             if not green_streak_active:
# # # # #                 if current_close > current_ema:  # Only take Call if in a bullish trend
# # # # #                     signals.append({
# # # # #                         "timestamp": entry_time,
# # # # #                         "pair": pair_name,
# # # # #                         "action": "call",
# # # # #                         "entry_price": entry_close,
# # # # #                         "exit_price": exit_close,
# # # # #                         "is_win": exit_close > entry_close
# # # # #                     })
# # # # #                 green_streak_active = True
# # # # #         else:
# # # # #             green_streak_active = False
            
# # # # #         # Check for 4 Red Candles -> Put Signal (Filtered by price < EMA 50)
# # # # #         if is_c0_red and is_c1_red and is_c2_red and is_c3_red:
# # # # #             if not red_streak_active:
# # # # #                 if current_close < current_ema:  # Only take Put if in a bearish trend
# # # # #                     signals.append({
# # # # #                         "timestamp": entry_time,
# # # # #                         "pair": pair_name,
# # # # #                         "action": "put",
# # # # #                         "entry_price": entry_close,
# # # # #                         "exit_price": exit_close,
# # # # #                         "is_win": exit_close < entry_close
# # # # #                     })
# # # # #                 red_streak_active = True
# # # # #         else:
# # # # #             red_streak_active = False
            
# # # # #     return signals

# # # # # def run_backtest():
# # # # #     if not connect_iq_option():
# # # # #         return
# # # # #     refresh_otc_mappings()
    
# # # # #     send_telegram_message("🚀 <b>5,000-Candle 4-Streak + EMA 50 Filter Backtest Started</b>\nStarting Balance: $10.00 | Stake: 10% Compounding | EMA 50 Trend Filter...")

# # # # #     report_lines = ["🚀 <b>4-STREAK + EMA 50 FILTER BACKTEST RESULTS</b>\n"]

# # # # #     for tf_sec, tf_name in TIMEFRAMES.items():
# # # # #         logger.info("Evaluating Timeframe: %s (5k candles with EMA 50 filter)", tf_name)
        
# # # # #         all_signals = []
# # # # #         for pair in OTC_PAIRS:
# # # # #             candles = fetch_candle_history(pair, tf_sec, total_needed=5000)
# # # # #             if not candles or len(candles) < 100:
# # # # #                 continue
# # # # #             pair_signals = generate_signals_for_pair(candles, pair)
# # # # #             all_signals.extend(pair_signals)
            
# # # # #         # Sort chronologically across all pairs for global concurrency management
# # # # #         all_signals.sort(key=lambda x: x["timestamp"])
        
# # # # #         balance = STARTING_BALANCE
# # # # #         trades_taken = 0
# # # # #         wins = 0
# # # # #         losses = 0
# # # # #         active_trades = []
# # # # #         duration_seconds = tf_sec
        
# # # # #         for sig in all_signals:
# # # # #             sig_time = sig["timestamp"]
            
# # # # #             # Remove expired active trades
# # # # #             active_trades = [exp for exp in active_trades if exp > sig_time]
            
# # # # #             if len(active_trades) < 2 and balance > 0.5:
# # # # #                 trades_taken += 1
# # # # #                 active_trades.append(sig_time + duration_seconds)
                
# # # # #                 stake = balance * STAKE_PERCENTAGE
# # # # #                 if sig["is_win"]:
# # # # #                     wins += 1
# # # # #                     balance += stake * PAYOUT_RATE
# # # # #                 else:
# # # # #                     losses += 1
# # # # #                     balance -= stake

# # # # #         win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0.0
# # # # #         profit = balance - STARTING_BALANCE
        
# # # # #         report_lines.append(
# # # # #             f"<b>Timeframe: {tf_name}</b>\n"
# # # # #             f"• Trades Taken: {trades_taken} | Wins: {wins} | Losses: {losses}\n"
# # # # #             f"• Win Rate: <b>{win_rate:.2f}%</b>\n"
# # # # #             f"• Final Balance: <b>${balance:.2f}</b> (P/L: ${profit:+.2f})\n"
# # # # #             f"-----------------------------------"
# # # # #         )

# # # # #     send_telegram_message("\n".join(report_lines))
# # # # #     logger.info("4-streak + EMA 50 filter backtest complete. Dispatched to Telegram.")

# # # # # if __name__ == "__main__":
# # # # #     run_backtest()

# # # # import os
# # # # import sys
# # # # import time
# # # # import json
# # # # import logging
# # # # import urllib.parse
# # # # import urllib.request

# # # # import pandas as pd
# # # # import numpy as np
# # # # from dotenv import load_dotenv
# # # # from iqoptionapi.stable_api import IQ_Option
# # # # import iqoptionapi.stable_api as stable_api

# # # # load_dotenv()

# # # # OWNER_EMAIL = os.getenv("OWNER_EMAIL")
# # # # OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
# # # # TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# # # # TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# # # # STARTING_BALANCE = 10.0 
# # # # STAKE_PERCENTAGE = 0.10  # 10% of current balance per trade
# # # # PAYOUT_RATE = 0.82

# # # # OTC_PAIRS = [
# # # #     "USDJPY-OTC",
# # # #     "AUDUSD-OTC",
# # # #     "EURJPY-OTC",
# # # #     "GBPJPY-OTC",
# # # # ]

# # # # TIMEFRAMES = {
# # # #     60: "1-Minute",
# # # #     300: "5-Minute",
# # # #     900: "15-Minute"
# # # # }

# # # # for var_name, val in [
# # # #     ("OWNER_EMAIL", OWNER_EMAIL),
# # # #     ("OWNER_PASSWORD", OWNER_PASSWORD),
# # # #     ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
# # # #     ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
# # # # ]:
# # # #     if not val:
# # # #         print(f"ERROR: {var_name} is missing from .env")
# # # #         sys.exit(1)

# # # # logging.basicConfig(
# # # #     level=logging.INFO,
# # # #     format="%(asctime)s | %(levelname)s | %(message)s",
# # # #     datefmt="%Y-%m-%d %H:%M:%S",
# # # # )
# # # # logger = logging.getLogger("FIREFLY-4STREAK-INVERTED")

# # # # API = None

# # # # def send_telegram_message(message):
# # # #     url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
# # # #     payload = urllib.parse.urlencode({
# # # #         "chat_id": TELEGRAM_CHAT_ID,
# # # #         "text": message,
# # # #         "parse_mode": "HTML"
# # # #     }).encode("utf-8")
# # # #     try:
# # # #         req = urllib.request.Request(url, data=payload, method="POST")
# # # #         with urllib.request.urlopen(req, timeout=10) as response:
# # # #             res = json.loads(response.read().decode("utf-8"))
# # # #             if not res.get("ok"):
# # # #                 logger.error("Telegram API rejection: %s", res)
# # # #     except Exception as exc:
# # # #         logger.error("Failed to send Telegram notification: %s", exc)

# # # # def connect_iq_option():
# # # #     global API
# # # #     logger.info("Connecting to IQ Option...")
# # # #     API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
# # # #     check, reason = API.connect()
# # # #     if not check:
# # # #         logger.error("Connection failed: %s", reason)
# # # #         return False
# # # #     logger.info("Connected successfully.")
# # # #     return True

# # # # def refresh_otc_mappings():
# # # #     if API is None:
# # # #         return False
# # # #     API.api.api_option_init_all_result = None
# # # #     API.api.get_api_option_init_all()
# # # #     start = time.time()
# # # #     while API.api.api_option_init_all_result is None and time.time() - start < 30:
# # # #         time.sleep(0.1)
        
# # # #     result = API.api.api_option_init_all_result
# # # #     if result and result.get("isSuccessful"):
# # # #         result_data = result.get("result", {})
# # # #         for market_type in ("binary", "turbo"):
# # # #             actives = result_data.get(market_type, {}).get("actives", {})
# # # #             for active_id, active_data in actives.items():
# # # #                 raw_name = active_data.get("name", "")
# # # #                 asset_name = raw_name.split(".", 1)[1] if "." in raw_name else raw_name
# # # #                 if asset_name in OTC_PAIRS:
# # # #                     stable_api.OP_code.ACTIVES[asset_name] = int(active_id)
# # # #     return True

# # # # def fetch_candle_history(pair, timeframe, total_needed=5000):
# # # #     all_candles = []
# # # #     end_time = time.time()
# # # #     chunk_size = 1000
    
# # # #     while len(all_candles) < total_needed:
# # # #         remaining = total_needed - len(all_candles)
# # # #         current_count = min(chunk_size, remaining)
        
# # # #         logger.info(f"Fetching chunk for {pair} ({timeframe}s) - Current total: {len(all_candles)}/{total_needed}")
# # # #         candles = API.get_candles(pair, timeframe, current_count, end_time)
# # # #         if not candles:
# # # #             break
            
# # # #         all_candles = candles + all_candles
# # # #         end_time = candles[0]['from'] - 1
# # # #         time.sleep(0.2)
        
# # # #     return all_candles

# # # # # ============================================================
# # # # # INVERTED 4-CANDLE STREAK SIGNAL GENERATION (FADE THE STREAK)
# # # # # ============================================================

# # # # def generate_signals_for_pair(candles, pair_name):
# # # #     df = pd.DataFrame(candles)
# # # #     df = df.rename(columns={'min': 'low', 'max': 'high'})
# # # #     for col in ['open', 'close', 'high', 'low', 'from']:
# # # #         df[col] = df[col].astype(float)
        
# # # #     signals = []
# # # #     green_streak_active = False
# # # #     red_streak_active = False
    
# # # #     for i in range(3, len(df) - 1):
# # # #         c0 = df.iloc[i-3]
# # # #         c1 = df.iloc[i-2]
# # # #         c2 = df.iloc[i-1]
# # # #         c3 = df.iloc[i]
        
# # # #         is_c0_green = c0['close'] > c0['open']
# # # #         is_c1_green = c1['close'] > c1['open']
# # # #         is_c2_green = c2['close'] > c2['open']
# # # #         is_c3_green = c3['close'] > c3['open']
        
# # # #         is_c0_red = c0['close'] < c0['open']
# # # #         is_c1_red = c1['close'] < c1['open']
# # # #         is_c2_red = c2['close'] < c2['open']
# # # #         is_c3_red = c3['close'] < c3['open']
        
# # # #         entry_time = df.loc[i+1, 'from']
# # # #         entry_close = c3['close']
# # # #         exit_close = df.loc[i+1, 'close']
        
# # # #         # 4 Green Candles -> INVERTED TO PUT (Fade the bullish exhaustion)
# # # #         if is_c0_green and is_c1_green and is_c2_green and is_c3_green:
# # # #             if not green_streak_active:
# # # #                 signals.append({
# # # #                     "timestamp": entry_time,
# # # #                     "pair": pair_name,
# # # #                     "action": "put",
# # # #                     "entry_price": entry_close,
# # # #                     "exit_price": exit_close,
# # # #                     "is_win": exit_close < entry_close
# # # #                 })
# # # #                 green_streak_active = True
# # # #         else:
# # # #             green_streak_active = False
            
# # # #         # 4 Red Candles -> INVERTED TO CALL (Fade the bearish exhaustion)
# # # #         if is_c0_red and is_c1_red and is_c2_red and is_c3_red:
# # # #             if not red_streak_active:
# # # #                 signals.append({
# # # #                     "timestamp": entry_time,
# # # #                     "pair": pair_name,
# # # #                     "action": "call",
# # # #                     "entry_price": entry_close,
# # # #                     "exit_price": exit_close,
# # # #                     "is_win": exit_close > entry_close
# # # #                 })
# # # #                 red_streak_active = True
# # # #         else:
# # # #             red_streak_active = False
            
# # # #     return signals

# # # # def run_backtest():
# # # #     if not connect_iq_option():
# # # #         return
# # # #     refresh_otc_mappings()
    
# # # #     send_telegram_message("🔄 <b>5,000-Candle Inverted 4-Streak Backtest Started</b>\nStarting Balance: $10.00 | Stake: 10% Compounding | Fading Streaks...")

# # # #     report_lines = ["🔄 <b>INVERTED 4-STREAK BACKTEST RESULTS</b>\n"]

# # # #     for tf_sec, tf_name in TIMEFRAMES.items():
# # # #         logger.info("Evaluating Timeframe: %s (5k candles inverted)", tf_name)
        
# # # #         all_signals = []
# # # #         for pair in OTC_PAIRS:
# # # #             candles = fetch_candle_history(pair, tf_sec, total_needed=5000)
# # # #             if not candles or len(candles) < 100:
# # # #                 continue
# # # #             pair_signals = generate_signals_for_pair(candles, pair)
# # # #             all_signals.extend(pair_signals)
            
# # # #         # Sort chronologically across all pairs for global concurrency management
# # # #         all_signals.sort(key=lambda x: x["timestamp"])
        
# # # #         balance = STARTING_BALANCE
# # # #         trades_taken = 0
# # # #         wins = 0
# # # #         losses = 0
# # # #         active_trades = []
# # # #         duration_seconds = tf_sec
        
# # # #         for sig in all_signals:
# # # #             sig_time = sig["timestamp"]
            
# # # #             # Remove expired active trades
# # # #             active_trades = [exp for exp in active_trades if exp > sig_time]
            
# # # #             if len(active_trades) < 2 and balance > 0.5:
# # # #                 trades_taken += 1
# # # #                 active_trades.append(sig_time + duration_seconds)
                
# # # #                 stake = balance * STAKE_PERCENTAGE
# # # #                 if sig["is_win"]:
# # # #                     wins += 1
# # # #                     balance += stake * PAYOUT_RATE
# # # #                 else:
# # # #                     losses += 1
# # # #                     balance -= stake

# # # #         win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0.0
# # # #         profit = balance - STARTING_BALANCE
        
# # # #         report_lines.append(
# # # #             f"<b>Timeframe: {tf_name}</b>\n"
# # # #             f"• Trades Taken: {trades_taken} | Wins: {wins} | Losses: {losses}\n"
# # # #             f"• Win Rate: <b>{win_rate:.2f}%</b>\n"
# # # #             f"• Final Balance: <b>${balance:.2f}</b> (P/L: ${profit:+.2f})\n"
# # # #             f"-----------------------------------"
# # # #         )

# # # #     send_telegram_message("\n".join(report_lines))
# # # #     logger.info("Inverted 4-streak backtest complete. Dispatched to Telegram.")

# # # # if __name__ == "__main__":
# # # #     run_backtest()

# # # import os
# # # import sys
# # # import time
# # # import json
# # # import logging
# # # import urllib.parse
# # # import urllib.request

# # # import pandas as pd
# # # import numpy as np
# # # from dotenv import load_dotenv
# # # from iqoptionapi.stable_api import IQ_Option
# # # import iqoptionapi.stable_api as stable_api

# # # load_dotenv()

# # # OWNER_EMAIL = os.getenv("OWNER_EMAIL")
# # # OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
# # # TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# # # TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# # # STARTING_BALANCE = 10.0 
# # # BASE_STAKE = 1.00        # $1.00 base stake (10% of $10)
# # # MARTINGALE_MULTIPLIER = 2.2 # 2.2x multiplier to recover loss + profit at 82% payout
# # # MAX_MARTINGALE_STEP = 2  # Step 0 ($1.00), Step 1 ($2.20), Step 2 ($4.84)
# # # PAYOUT_RATE = 0.82

# # # OTC_PAIRS = [
# # #     "USDJPY-OTC",
# # #     "AUDUSD-OTC",
# # #     "EURJPY-OTC",
# # #     "GBPJPY-OTC",
# # # ]

# # # TIMEFRAMES = {
# # #     60: "1-Minute",
# # #     300: "5-Minute",
# # #     900: "15-Minute"
# # # }

# # # for var_name, val in [
# # #     ("OWNER_EMAIL", OWNER_EMAIL),
# # #     ("OWNER_PASSWORD", OWNER_PASSWORD),
# # #     ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
# # #     ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
# # # ]:
# # #     if not val:
# # #         print(f"ERROR: {var_name} is missing from .env")
# # #         sys.exit(1)

# # # logging.basicConfig(
# # #     level=logging.INFO,
# # #     format="%(asctime)s | %(levelname)s | %(message)s",
# # #     datefmt="%Y-%m-%d %H:%M:%S",
# # # )
# # # logger = logging.getLogger("FIREFLY-MARTINGALE")

# # # API = None

# # # def send_telegram_message(message):
# # #     url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
# # #     payload = urllib.parse.urlencode({
# # #         "chat_id": TELEGRAM_CHAT_ID,
# # #         "text": message,
# # #         "parse_mode": "HTML"
# # #     }).encode("utf-8")
# # #     try:
# # #         req = urllib.request.Request(url, data=payload, method="POST")
# # #         with urllib.request.urlopen(req, timeout=10) as response:
# # #             res = json.loads(response.read().decode("utf-8"))
# # #             if not res.get("ok"):
# # #                 logger.error("Telegram API rejection: %s", res)
# # #     except Exception as exc:
# # #         logger.error("Failed to send Telegram notification: %s", exc)

# # # def connect_iq_option():
# # #     global API
# # #     logger.info("Connecting to IQ Option...")
# # #     API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
# # #     check, reason = API.connect()
# # #     if not check:
# # #         logger.error("Connection failed: %s", reason)
# # #         return False
# # #     logger.info("Connected successfully.")
# # #     return True

# # # def refresh_otc_mappings():
# # #     if API is None:
# # #         return False
# # #     API.api.api_option_init_all_result = None
# # #     API.api.get_api_option_init_all()
# # #     start = time.time()
# # #     while API.api.api_option_init_all_result is None and time.time() - start < 30:
# # #         time.sleep(0.1)
        
# # #     result = API.api.api_option_init_all_result
# # #     if result and result.get("isSuccessful"):
# # #         result_data = result.get("result", {})
# # #         for market_type in ("binary", "turbo"):
# # #             actives = result_data.get(market_type, {}).get("actives", {})
# # #             for active_id, active_data in actives.items():
# # #                 raw_name = active_data.get("name", "")
# # #                 asset_name = raw_name.split(".", 1)[1] if "." in raw_name else raw_name
# # #                 if asset_name in OTC_PAIRS:
# # #                     stable_api.OP_code.ACTIVES[asset_name] = int(active_id)
# # #     return True

# # # def fetch_candle_history(pair, timeframe, total_needed=5000):
# # #     all_candles = []
# # #     end_time = time.time()
# # #     chunk_size = 1000
    
# # #     while len(all_candles) < total_needed:
# # #         remaining = total_needed - len(all_candles)
# # #         current_count = min(chunk_size, remaining)
        
# # #         logger.info(f"Fetching chunk for {pair} ({timeframe}s) - Current total: {len(all_candles)}/{total_needed}")
# # #         candles = API.get_candles(pair, timeframe, current_count, end_time)
# # #         if not candles:
# # #             break
            
# # #         all_candles = candles + all_candles
# # #         end_time = candles[0]['from'] - 1
# # #         time.sleep(0.2)
        
# # #     return all_candles

# # # # ============================================================
# # # # INVERTED 4-CANDLE STREAK SIGNAL GENERATION
# # # # ============================================================

# # # def generate_signals_for_pair(candles, pair_name):
# # #     df = pd.DataFrame(candles)
# # #     df = df.rename(columns={'min': 'low', 'max': 'high'})
# # #     for col in ['open', 'close', 'high', 'low', 'from']:
# # #         df[col] = df[col].astype(float)
        
# # #     signals = []
# # #     green_streak_active = False
# # #     red_streak_active = False
    
# # #     for i in range(3, len(df) - 1):
# # #         c0 = df.iloc[i-3]
# # #         c1 = df.iloc[i-2]
# # #         c2 = df.iloc[i-1]
# # #         c3 = df.iloc[i]
        
# # #         is_c0_green = c0['close'] > c0['open']
# # #         is_c1_green = c1['close'] > c1['open']
# # #         is_c2_green = c2['close'] > c2['open']
# # #         is_c3_green = c3['close'] > c3['open']
        
# # #         is_c0_red = c0['close'] < c0['open']
# # #         is_c1_red = c1['close'] < c1['open']
# # #         is_c2_red = c2['close'] < c2['open']
# # #         is_c3_red = c3['close'] < c3['open']
        
# # #         entry_time = df.loc[i+1, 'from']
# # #         entry_close = c3['close']
# # #         exit_close = df.loc[i+1, 'close']
        
# # #         # 4 Green Candles -> INVERTED TO PUT
# # #         if is_c0_green and is_c1_green and is_c2_green and is_c3_green:
# # #             if not green_streak_active:
# # #                 signals.append({
# # #                     "timestamp": entry_time,
# # #                     "pair": pair_name,
# # #                     "action": "put",
# # #                     "entry_price": entry_close,
# # #                     "exit_price": exit_close,
# # #                     "is_win": exit_close < entry_close
# # #                 })
# # #                 green_streak_active = True
# # #         else:
# # #             green_streak_active = False
            
# # #         # 4 Red Candles -> INVERTED TO CALL
# # #         if is_c0_red and is_c1_red and is_c2_red and is_c3_red:
# # #             if not red_streak_active:
# # #                 signals.append({
# # #                     "timestamp": entry_time,
# # #                     "pair": pair_name,
# # #                     "action": "call",
# # #                     "entry_price": entry_close,
# # #                     "exit_price": exit_close,
# # #                     "is_win": exit_close > entry_close
# # #                 })
# # #                 red_streak_active = True
# # #         else:
# # #             red_streak_active = False
            
# # #     return signals

# # # def run_backtest():
# # #     if not connect_iq_option():
# # #         return
# # #     refresh_otc_mappings()
    
# # #     send_telegram_message("📈 <b>5,000-Candle Inverted 4-Streak + Martingale Backtest Started</b>\nStarting Balance: $10.00 | Base Stake: $1.00 | Martingale Multiplier: 2.2x (Max 2 Steps)...")

# # #     report_lines = ["📈 <b>INVERTED 4-STREAK + MARTINGALE RESULTS</b>\n"]

# # #     for tf_sec, tf_name in TIMEFRAMES.items():
# # #         logger.info("Evaluating Timeframe: %s (Martingale backtest)", tf_name)
        
# # #         all_signals = []
# # #         for pair in OTC_PAIRS:
# # #             candles = fetch_candle_history(pair, tf_sec, total_needed=5000)
# # #             if not candles or len(candles) < 100:
# # #                 continue
# # #             pair_signals = generate_signals_for_pair(candles, pair)
# # #             all_signals.extend(pair_signals)
            
# # #         # Sort chronologically across all pairs for global concurrency management
# # #         all_signals.sort(key=lambda x: x["timestamp"])
        
# # #         balance = STARTING_BALANCE
# # #         trades_taken = 0
# # #         wins = 0
# # #         losses = 0
# # #         active_trades = []
# # #         duration_seconds = tf_sec
        
# # #         # Track martingale step per pair
# # #         pair_martingale_step = {pair: 0 for pair in OTC_PAIRS}
        
# # #         for sig in all_signals:
# # #             sig_time = sig["timestamp"]
# # #             pair = sig["pair"]
            
# # #             # Remove expired active trades
# # #             active_trades = [exp for exp in active_trades if exp > sig_time]
            
# # #             if len(active_trades) < 2 and balance > 0.5:
# # #                 step = pair_martingale_step[pair]
# # #                 stake = BASE_STAKE * (MARTINGALE_MULTIPLIER ** step)
                
# # #                 # Ensure stake doesn't exceed available balance
# # #                 if stake > balance:
# # #                     stake = balance
                
# # #                 trades_taken += 1
# # #                 active_trades.append(sig_time + duration_seconds)
                
# # #                 if sig["is_win"]:
# # #                     wins += 1
# # #                     balance += stake * PAYOUT_RATE
# # #                     pair_martingale_step[pair] = 0  # Reset martingale on win
# # #                 else:
# # #                     losses += 1
# # #                     balance -= stake
# # #                     # Increment martingale step up to max
# # #                     if pair_martingale_step[pair] < MAX_MARTINGALE_STEP:
# # #                         pair_martingale_step[pair] += 1
# # #                     else:
# # #                         pair_martingale_step[pair] = 0  # Reset after max step loss to protect capital

# # #         win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0.0
# # #         profit = balance - STARTING_BALANCE
        
# # #         report_lines.append(
# # #             f"<b>Timeframe: {tf_name}</b>\n"
# # #             f"• Trades Taken: {trades_taken} | Wins: {wins} | Losses: {losses}\n"
# # #             f"• Win Rate: <b>{win_rate:.2f}%</b>\n"
# # #             f"• Final Balance: <b>${balance:.2f}</b> (P/L: ${profit:+.2f})\n"
# # #             f"-----------------------------------"
# # #         )

# # #     send_telegram_message("\n".join(report_lines))
# # #     logger.info("Martingale backtest complete. Dispatched to Telegram.")

# # # if __name__ == "__main__":
# # #     run_backtest()

# # import os
# # import sys
# # import time
# # import json
# # import logging
# # import urllib.parse
# # import urllib.request

# # import pandas as pd
# # from dotenv import load_dotenv
# # from iqoptionapi.stable_api import IQ_Option
# # import iqoptionapi.stable_api as stable_api

# # load_dotenv()

# # OWNER_EMAIL = os.getenv("OWNER_EMAIL")
# # OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
# # TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# # TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# # STARTING_BALANCE = 10.0 
# # STAKE_PERCENTAGE = 0.10  # 10% compounding stake
# # PAYOUT_RATE = 0.82

# # OTC_PAIRS = [
# #     "USDJPY-OTC",
# #     "AUDUSD-OTC",
# #     "EURJPY-OTC",
# #     "GBPJPY-OTC",
# # ]

# # # Focusing specifically on the 5-minute timeframe (300 seconds) where you want to trade
# # TIMEFRAME_SEC = 300
# # TIMEFRAME_NAME = "5-Minute"

# # for var_name, val in [
# #     ("OWNER_EMAIL", OWNER_EMAIL),
# #     ("OWNER_PASSWORD", OWNER_PASSWORD),
# #     ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
# #     ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
# # ]:
# #     if not val:
# #         print(f"ERROR: {var_name} is missing from .env")
# #         sys.exit(1)

# # logging.basicConfig(
# #     level=logging.INFO,
# #     format="%(asctime)s | %(levelname)s | %(message)s",
# #     datefmt="%Y-%m-%d %H:%M:%S",
# # )
# # logger = logging.getLogger("FIREFLY-LONG-STREAK")

# # API = None

# # def send_telegram_message(message):
# #     url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
# #     payload = urllib.parse.urlencode({
# #         "chat_id": TELEGRAM_CHAT_ID,
# #         "text": message,
# #         "parse_mode": "HTML"
# #     }).encode("utf-8")
# #     try:
# #         req = urllib.request.Request(url, data=payload, method="POST")
# #         with urllib.request.urlopen(req, timeout=10) as response:
# #             res = json.loads(response.read().decode("utf-8"))
# #             if not res.get("ok"):
# #                 logger.error("Telegram API rejection: %s", res)
# #     except Exception as exc:
# #         logger.error("Failed to send Telegram notification: %s", exc)

# # def connect_iq_option():
# #     global API
# #     logger.info("Connecting to IQ Option...")
# #     API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
# #     check, reason = API.connect()
# #     if not check:
# #         logger.error("Connection failed: %s", reason)
# #         return False
# #     logger.info("Connected successfully.")
# #     return True

# # def refresh_otc_mappings():
# #     if API is None:
# #         return False
# #     API.api.api_option_init_all_result = None
# #     API.api.get_api_option_init_all()
# #     start = time.time()
# #     while API.api.api_option_init_all_result is None and time.time() - start < 30:
# #         time.sleep(0.1)
        
# #     result = API.api.api_option_init_all_result
# #     if result and result.get("isSuccessful"):
# #         result_data = result.get("result", {})
# #         for market_type in ("binary", "turbo"):
# #             actives = result_data.get(market_type, {}).get("actives", {})
# #             for active_id, active_data in actives.items():
# #                 raw_name = active_data.get("name", "")
# #                 asset_name = raw_name.split(".", 1)[1] if "." in raw_name else raw_name
# #                 if asset_name in OTC_PAIRS:
# #                     stable_api.OP_code.ACTIVES[asset_name] = int(active_id)
# #     return True

# # def fetch_candle_history(pair, timeframe, total_needed=5000):
# #     all_candles = []
# #     end_time = time.time()
# #     chunk_size = 1000
    
# #     while len(all_candles) < total_needed:
# #         remaining = total_needed - len(all_candles)
# #         current_count = min(chunk_size, remaining)
        
# #         logger.info(f"Fetching chunk for {pair} ({timeframe}s) - Current total: {len(all_candles)}/{total_needed}")
# #         candles = API.get_candles(pair, timeframe, current_count, end_time)
# #         if not candles:
# #             break
            
# #         all_candles = candles + all_candles
# #         end_time = candles[0]['from'] - 1
# #         time.sleep(0.2)
        
# #     return all_candles

# # def generate_signals(candles, pair_name, streak_length):
# #     df = pd.DataFrame(candles)
# #     df = df.rename(columns={'min': 'low', 'max': 'high'})
# #     for col in ['open', 'close', 'high', 'low', 'from']:
# #         df[col] = df[col].astype(float)
        
# #     signals = []
# #     streak_active = False
    
# #     # We need at least `streak_length` candles to check
# #     for i in range(streak_length - 1, len(df) - 1):
# #         # Grab the window of `streak_length` candles
# #         window = df.iloc[i - (streak_length - 1): i + 1]
        
# #         is_all_green = all(window['close'] > window['open'])
# #         is_all_red = all(window['close'] < window['open'])
        
# #         entry_time = df.loc[i+1, 'from']
# #         entry_close = df.loc[i, 'close']
# #         exit_close = df.loc[i+1, 'close']
        
# #         # Inverted logic: Green streak -> PUT, Red streak -> CALL
# #         if is_all_green:
# #             if not streak_active:
# #                 signals.append({
# #                     "timestamp": entry_time,
# #                     "pair": pair_name,
# #                     "action": "put",
# #                     "is_win": exit_close < entry_close
# #                 })
# #                 streak_active = True
# #         elif is_all_red:
# #             if not streak_active:
# #                 signals.append({
# #                     "timestamp": entry_time,
# #                     "pair": pair_name,
# #                     "action": "call",
# #                     "is_win": exit_close > entry_close
# #                 })
# #                 streak_active = True
# #         else:
# #             streak_active = False
            
# #     return signals

# # def run_backtest():
# #     if not connect_iq_option():
# #         return
# #     refresh_otc_mappings()
    
# #     send_telegram_message("🔎 <b>5,000-Candle Long-Streak (7 & 10) Backtest Started</b>\nTimeframe: 5-Minute | Testing Exhaustion Fades...")

# #     report_lines = ["🔎 <b>LONG-STREAK EXHAUSTION BACKTEST RESULTS (5M)</b>\n"]

# #     for streak_target in [7, 10]:
# #         logger.info(f"Running backtest for {streak_target}-candle streak on 5m...")
        
# #         all_signals = []
# #         for pair in OTC_PAIRS:
# #             candles = fetch_candle_history(pair, TIMEFRAME_SEC, total_needed=5000)
# #             if not candles or len(candles) < 200:
# #                 continue
# #             pair_signals = generate_signals(candles, pair, streak_target)
# #             all_signals.extend(pair_signals)
            
# #         all_signals.sort(key=lambda x: x["timestamp"])
        
# #         balance = STARTING_BALANCE
# #         trades_taken = 0
# #         wins = 0
# #         losses = 0
# #         active_trades = []
        
# #         for sig in all_signals:
# #             sig_time = sig["timestamp"]
# #             active_trades = [exp for exp in active_trades if exp > sig_time]
            
# #             if len(active_trades) < 2 and balance > 0.5:
# #                 trades_taken += 1
# #                 active_trades.append(sig_time + TIMEFRAME_SEC)
                
# #                 stake = balance * STAKE_PERCENTAGE
# #                 if sig["is_win"]:
# #                     wins += 1
# #                     balance += stake * PAYOUT_RATE
# #                 else:
# #                     losses += 1
# #                     balance -= stake

# #         win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0.0
# #         profit = balance - STARTING_BALANCE
        
# #         report_lines.append(
# #             f"<b>Streak Threshold: {streak_target}-Candle</b>\n"
# #             f"• Trades Taken: {trades_taken} | Wins: {wins} | Losses: {losses}\n"
# #             f"• Win Rate: <b>{win_rate:.2f}%</b>\n"
# #             f"• Final Balance: <b>${balance:.2f}</b> (P/L:${profit:+.2f})\n"
# #             f"-----------------------------------"
# #         )

# #     send_telegram_message("\n".join(report_lines))
# #     logger.info("Long-streak backtest complete.")

# # if __name__ == "__main__":
# #     run_backtest()

# import os
# import sys
# import time
# import json
# import logging
# import urllib.parse
# import urllib.request

# import pandas as pd
# from dotenv import load_dotenv
# from iqoptionapi.stable_api import IQ_Option
# import iqoptionapi.stable_api as stable_api

# load_dotenv()

# OWNER_EMAIL = os.getenv("OWNER_EMAIL")
# OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")
# TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# STARTING_BALANCE = 10.0 
# STAKE_PERCENTAGE = 0.10  # 10% compounding stake
# PAYOUT_RATE = 0.82

# OTC_PAIRS = [
#     "USDJPY-OTC",
#     "AUDUSD-OTC",
#     "EURJPY-OTC",
#     "GBPJPY-OTC",
# ]

# # Focusing specifically on the 5-minute timeframe (300 seconds) where you want to trade
# TIMEFRAME_SEC = 300
# TIMEFRAME_NAME = "5-Minute"

# for var_name, val in [
#     ("OWNER_EMAIL", OWNER_EMAIL),
#     ("OWNER_PASSWORD", OWNER_PASSWORD),
#     ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
#     ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
# ]:
#     if not val:
#         print(f"ERROR: {var_name} is missing from .env")
#         sys.exit(1)

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s | %(levelname)s | %(message)s",
#     datefmt="%Y-%m-%d %H:%M:%S",
# )
# logger = logging.getLogger("FIREFLY-LONG-STREAK")

# API = None

# def send_telegram_message(message):
#     url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
#     payload = urllib.parse.urlencode({
#         "chat_id": TELEGRAM_CHAT_ID,
#         "text": message,
#         "parse_mode": "HTML"
#     }).encode("utf-8")
#     try:
#         req = urllib.request.Request(url, data=payload, method="POST")
#         with urllib.request.urlopen(req, timeout=10) as response:
#             res = json.loads(response.read().decode("utf-8"))
#             if not res.get("ok"):
#                 logger.error("Telegram API rejection: %s", res)
#     except Exception as exc:
#         logger.error("Failed to send Telegram notification: %s", exc)

# def connect_iq_option():
#     global API
#     logger.info("Connecting to IQ Option...")
#     API = IQ_Option(OWNER_EMAIL, OWNER_PASSWORD)
#     check, reason = API.connect()
#     if not check:
#         logger.error("Connection failed: %s", reason)
#         return False
#     logger.info("Connected successfully.")
#     return True

# def refresh_otc_mappings():
#     if API is None:
#         return False
#     API.api.api_option_init_all_result = None
#     API.api.get_api_option_init_all()
#     start = time.time()
#     while API.api.api_option_init_all_result is None and time.time() - start < 30:
#         time.sleep(0.1)
        
#     result = API.api.api_option_init_all_result
#     if result and result.get("isSuccessful"):
#         result_data = result.get("result", {})
#         for market_type in ("binary", "turbo"):
#             actives = result_data.get(market_type, {}).get("actives", {})
#             for active_id, active_data in actives.items():
#                 raw_name = active_data.get("name", "")
#                 asset_name = raw_name.split(".", 1)[1] if "." in raw_name else raw_name
#                 if asset_name in OTC_PAIRS:
#                     stable_api.OP_code.ACTIVES[asset_name] = int(active_id)
#     return True

# def fetch_candle_history(pair, timeframe, total_needed=5000):
#     all_candles = []
#     end_time = time.time()
#     chunk_size = 1000
    
#     while len(all_candles) < total_needed:
#         remaining = total_needed - len(all_candles)
#         current_count = min(chunk_size, remaining)
        
#         logger.info(f"Fetching chunk for {pair} ({timeframe}s) - Current total: {len(all_candles)}/{total_needed}")
#         candles = API.get_candles(pair, timeframe, current_count, end_time)
#         if not candles:
#             break
            
#         all_candles = candles + all_candles
#         end_time = candles[0]['from'] - 1
#         time.sleep(0.2)
        
#     return all_candles

# def generate_signals(candles, pair_name, streak_length):
#     df = pd.DataFrame(candles)
#     df = df.rename(columns={'min': 'low', 'max': 'high'})
#     for col in ['open', 'close', 'high', 'low', 'from']:
#         df[col] = df[col].astype(float)
        
#     signals = []
#     streak_active = False
    
#     # We need at least `streak_length` candles to check
#     for i in range(streak_length - 1, len(df) - 1):
#         # Grab the window of `streak_length` candles
#         window = df.iloc[i - (streak_length - 1): i + 1]
        
#         is_all_green = all(window['close'] > window['open'])
#         is_all_red = all(window['close'] < window['open'])
        
#         entry_time = df.loc[i+1, 'from']
#         entry_close = df.loc[i, 'close']
#         exit_close = df.loc[i+1, 'close']
        
#         # Inverted logic: Green streak -> PUT, Red streak -> CALL
#         if is_all_green:
#             if not streak_active:
#                 signals.append({
#                     "timestamp": entry_time,
#                     "pair": pair_name,
#                     "action": "put",
#                     "is_win": exit_close < entry_close
#                 })
#                 streak_active = True
#         elif is_all_red:
#             if not streak_active:
#                 signals.append({
#                     "timestamp": entry_time,
#                     "pair": pair_name,
#                     "action": "call",
#                     "is_win": exit_close > entry_close
#                 })
#                 streak_active = True
#         else:
#             streak_active = False
            
#     return signals

# def run_backtest():
#     if not connect_iq_option():
#         return
#     refresh_otc_mappings()
    
#     send_telegram_message("🔎 <b>5,000-Candle Long-Streak (7 & 10) Backtest Started</b>\nTimeframe: 5-Minute | Testing Exhaustion Fades...")

#     report_lines = ["🔎 <b>LONG-STREAK EXHAUSTION BACKTEST RESULTS (5M)</b>\n"]

#     for streak_target in [7, 10]:
#         logger.info(f"Running backtest for {streak_target}-candle streak on 5m...")
        
#         all_signals = []
#         for pair in OTC_PAIRS:
#             candles = fetch_candle_history(pair, TIMEFRAME_SEC, total_needed=5000)
#             if not candles or len(candles) < 200:
#                 continue
#             pair_signals = generate_signals(candles, pair, streak_target)
#             all_signals.extend(pair_signals)
            
#         all_signals.sort(key=lambda x: x["timestamp"])
        
#         balance = STARTING_BALANCE
#         trades_taken = 0
#         wins = 0
#         losses = 0
#         active_trades = []
        
#         for sig in all_signals:
#             sig_time = sig["timestamp"]
#             active_trades = [exp for exp in active_trades if exp > sig_time]
            
#             if len(active_trades) < 2 and balance > 0.5:
#                 trades_taken += 1
#                 active_trades.append(sig_time + TIMEFRAME_SEC)
                
#                 stake = balance * STAKE_PERCENTAGE
#                 if sig["is_win"]:
#                     wins += 1
#                     balance += stake * PAYOUT_RATE
#                 else:
#                     losses += 1
#                     balance -= stake

#         win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0.0
#         profit = balance - STARTING_BALANCE
        
#         report_lines.append(
#             f"<b>Streak Threshold: {streak_target}-Candle</b>\n"
#             f"• Trades Taken: {trades_taken} | Wins: {wins} | Losses: {losses}\n"
#             f"• Win Rate: <b>{win_rate:.2f}%</b>\n"
#             f"• Final Balance: <b>${balance:.2f}</b> (P/L:${profit:+.2f})\n"
#             f"-----------------------------------"
#         )

#     send_telegram_message("\n".join(report_lines))
#     logger.info("Long-streak backtest complete.")

# if __name__ == "__main__":
#     run_backtest()
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
STAKE_PERCENTAGE = 0.10  # 10% compounding stake
PAYOUT_RATE = 0.82

OTC_PAIRS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "GBPJPY-OTC",
]

TIMEFRAME_SEC = 300
TIMEFRAME_NAME = "5-Minute"
STREAK_TARGET = 10

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
logger = logging.getLogger("FIREFLY-10STREAK-EMA200")

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

def generate_signals_with_ema(candles, pair_name):
    df = pd.DataFrame(candles)
    df = df.rename(columns={'min': 'low', 'max': 'high'})
    for col in ['open', 'close', 'high', 'low', 'from']:
        df[col] = df[col].astype(float)
        
    # Calculate 200-period EMA for higher timeframe trend filtering
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    signals = []
    streak_active = False
    
    # Start after EMA 200 has fully warmed up (index >= 200)
    for i in range(200, len(df) - 1):
        window = df.iloc[i - (STREAK_TARGET - 1): i + 1]
        
        is_all_green = all(window['close'] > window['open'])
        is_all_red = all(window['close'] < window['open'])
        
        current_close = df.loc[i, 'close']
        current_ema = df.loc[i, 'ema200']
        
        entry_time = df.loc[i+1, 'from']
        exit_close = df.loc[i+1, 'close']
        
        # 10 Green Candles -> Put Signal (Fading bullish exhaustion)
        # Filter: Only take if price is BELOW EMA 200 (pullback in a downtrend)
        if is_all_green:
            if not streak_active:
                if current_close < current_ema:
                    signals.append({
                        "timestamp": entry_time,
                        "pair": pair_name,
                        "action": "put",
                        "is_win": exit_close < current_close
                    })
                streak_active = True
                
        # 10 Red Candles -> Call Signal (Fading bearish exhaustion)
        # Filter: Only take if price is ABOVE EMA 200 (pullback in an uptrend)
        elif is_all_red:
            if not streak_active:
                if current_close > current_ema:
                    signals.append({
                        "timestamp": entry_time,
                        "pair": pair_name,
                        "action": "call",
                        "is_win": exit_close > current_close
                    })
                streak_active = True
        else:
            streak_active = False
            
    return signals

def run_backtest():
    if not connect_iq_option():
        return
    refresh_otc_mappings()
    
    send_telegram_message("🎯 <b>5,000-Candle 10-Streak + EMA 200 Filter Backtest Started</b>\nTimeframe: 5-Minute | Trend-Filtered Exhaustion Fades...")

    report_lines = ["🎯 <b>10-STREAK + EMA 200 FILTER RESULTS (5M)</b>\n"]

    all_signals = []
    for pair in OTC_PAIRS:
        candles = fetch_candle_history(pair, TIMEFRAME_SEC, total_needed=5000)
        if not candles or len(candles) < 300:
            continue
        pair_signals = generate_signals_with_ema(candles, pair)
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
        
        if len(active_trades) < 2 and balance > 0.5:
            trades_taken += 1
            active_trades.append(sig_time + TIMEFRAME_SEC)
            
            stake = balance * STAKE_PERCENTAGE
            if sig["is_win"]:
                wins += 1
                balance += stake * PAYOUT_RATE
            else:
                losses += 1
                balance -= stake

    win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0.0
    profit = balance - STARTING_BALANCE
    
    report_lines.append(
        f"<b>10-Streak + EMA 200 Strategy</b>\n"
        f"• Trades Taken: {trades_taken} | Wins: {wins} | Losses: {losses}\n"
        f"• Win Rate: <b>{win_rate:.2f}%</b>\n"
        f"• Final Balance: <b>${balance:.2f}</b> (P/L: ${profit:+.2f})\n"
        f"-----------------------------------"
    )

    send_telegram_message("\n".join(report_lines))
    logger.info("10-streak + EMA 200 backtest complete.")

if __name__ == "__main__":
    run_backtest()