import os
import time
import threading
import concurrent.futures
from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option

load_dotenv()
API = IQ_Option(os.getenv("OWNER_EMAIL"), os.getenv("OWNER_PASSWORD"))
API.connect()

# All target assets to scan simultaneously
ASSETS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "AUDJPY-OTC",
    "GBPJPY-OTC",
    "GBPAUD-OTC",
    "GBPCAD-OTC",
    "CADJPY-OTC"
]

def calculate_indicators(candles, period=14):
    closes = [c["close"] for c in candles]
    highs = [c["max"] for c in candles]
    lows = [c["min"] for c in candles]

    if len(closes) < 30:
        return None

    # 1. RSI (14 Period)
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    rsi = 100 - (100 / (1 + rs))

    # 2. Bollinger Bands (20 Period, 2 StdDev)
    bb_period = 20
    sma = sum(closes[-bb_period:]) / bb_period
    variance = sum((x - sma) ** 2 for x in closes[-bb_period:]) / bb_period
    std_dev = variance**0.5
    upper_band = sma + (2 * std_dev)
    lower_band = sma - (2 * std_dev)

    # 3. EMA Crossover (Fast 9, Slow 21)
    def calc_ema(data, span):
        multiplier = 2 / (span + 1)
        ema = data[0]
        for price in data[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    ema_fast = calc_ema(closes[-9:], 9)
    ema_slow = calc_ema(closes[-21:], 21)

    # 4. Support & Resistance
    support = min(lows[-30:-1])
    resistance = max(highs[-30:-1])

    return {
        "rsi": rsi,
        "upper_band": upper_band,
        "lower_band": lower_band,
        "sma": sma,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "support": support,
        "resistance": resistance,
    }

def monitor_asset(asset):
    """Dedicated background loop for each currency pair."""
    amount = 10
    timeframe = 60
    print(f"[*] Scanner thread active for: {asset}")

    while True:
        if not API.check_connect():
            time.sleep(5)
            continue

        # Fetch candles with a strict 5-second timeout using threading to prevent terminal lockups
        candles = None
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(API.get_candles, asset, timeframe, 50, time.time())
                candles = future.result(timeout=5)
        except concurrent.futures.TimeoutError:
            print(f"[{asset}] API request timed out. Reconnecting...")
            API.connect()
            time.sleep(5)
            continue
        except Exception:
            time.sleep(5)
            continue

        if not candles:
            time.sleep(15)
            continue

        ind = calculate_indicators(candles)
        if not ind:
            time.sleep(10)
            continue

        last_candle = candles[-2]  # Completed candle
        current_close = last_candle["close"]
        is_green = current_close > last_candle["open"]
        is_red = current_close < last_candle["open"]

        signal = None
        matched_strategy = None

        # --- STRATEGY 1: Bollinger Band Reversion ---
        if current_close <= ind["lower_band"] and is_green:
            signal = "call"
            matched_strategy = "Strategy 1: Bollinger Lower Band Bounce"
        elif current_close >= ind["upper_band"] and is_red:
            signal = "put"
            matched_strategy = "Strategy 1: Bollinger Upper Band Rejection"

        # --- STRATEGY 2: RSI Exhaustion + Trend Filter ---
        elif ind["rsi"] < 28 and is_green and current_close > ind["sma"]:
            signal = "call"
            matched_strategy = "Strategy 2: RSI Oversold + SMA Support"
        elif ind["rsi"] > 72 and is_red and current_close < ind["sma"]:
            signal = "put"
            matched_strategy = "Strategy 2: RSI Overbought + SMA Resistance"

        # --- STRATEGY 3: Support & Resistance Bounce ---
        elif current_close <= ind["support"] and is_green:
            signal = "call"
            matched_strategy = "Strategy 3: Support Zone Rejection Bounce"
        elif current_close >= ind["resistance"] and is_red:
            signal = "put"
            matched_strategy = "Strategy 3: Resistance Zone Rejection Drop"

        # --- STRATEGY 4: Filtered EMA Momentum (Preserving your exact RSI bounds) ---
        ema_spread = abs(ind["ema_fast"] - ind["ema_slow"])
        min_spread_threshold = 0.0003

        if (
            ind["ema_fast"] > ind["ema_slow"]
            and is_green
            and ema_spread > min_spread_threshold
            and ind["rsi"] < 58
        ):
            signal = "call"
            matched_strategy = "Strategy 4: Validated Bullish Momentum"
        elif (
            ind["ema_fast"] < ind["ema_slow"]
            and is_red
            and ema_spread > min_spread_threshold
            and ind["rsi"] > 45
        ):
            signal = "put"
            matched_strategy = "Strategy 4: Validated Bearish Momentum"

        # If a strategy triggers, execute trade for this specific asset thread
        if signal:
            print(f"[{asset}] TRIGGERED [{matched_strategy}] | RSI: {ind['rsi']:.1f} | Placing {signal.upper()}...")
            check, order_id = API.buy(amount, asset, signal, 1)

            if check:
                print(f"[{asset}] Order Success! ID: {order_id}. Waiting for settlement...")
                time.sleep(65)
                print(f"[{asset}] Updated Balance: ${API.get_balance():.2f}")
                
                # Cooldown break: skip consecutive triggers for this asset
                print(f"[{asset}] Cooling down for 45s...")
                time.sleep(45)
            else:
                print(f"[{asset}] Order rejected by broker.")

        time.sleep(15)

if API.check_connect():
    API.change_balance("PRACTICE")
    print(f"Multi-Asset 4-Strategy Decision Engine active. Monitoring {len(ASSETS)} assets concurrently...")

    # Spawn an isolated daemon thread for every asset in your list
    for asset in ASSETS:
        t = threading.Thread(target=monitor_asset, args=(asset,))
        t.daemon = True
        t.start()
        time.sleep(1)  # Stagger thread startup slightly to prevent API packet collisions

    # Keep the master process alive indefinitely
    while True:
        time.sleep(1)
else:
    print("Connection failed.")