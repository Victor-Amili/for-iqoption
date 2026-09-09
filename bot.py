import os
import sys
import time
import logging
import threading
from datetime import datetime

import requests
from dotenv import load_dotenv

from iqoptionapi.stable_api import IQ_Option
import iqoptionapi.stable_api as stable_api


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()


IQ_EMAIL = os.getenv("IQ_EMAIL")
IQ_PASSWORD = os.getenv("IQ_PASSWORD")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


TIMEFRAME = 60
CANDLE_COUNT = 15

POLL_INTERVAL = 15

ASSET_REFRESH_TIMEOUT = 15

RECONNECT_DELAY = 5

MIN_STREAK = 9


# ============================================================
# OTC PAIRS
# ============================================================

OTC_PAIRS = [
    "USDJPY-OTC",
    "AUDUSD-OTC",
    "EURJPY-OTC",
    "AUDJPY-OTC",
    "GBPJPY-OTC",
    "GBPAUD-OTC",
    "GBPCAD-OTC",
    "CADJPY-OTC",
]


# ============================================================
# VALIDATION
# ============================================================

if not IQ_EMAIL:
    print("ERROR: IQ_EMAIL is missing from .env")
    sys.exit(1)

if not IQ_PASSWORD:
    print("ERROR: IQ_PASSWORD is missing from .env")
    sys.exit(1)

if not TELEGRAM_BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN is missing from .env")
    sys.exit(1)

if not TELEGRAM_CHAT_ID:
    print("ERROR: TELEGRAM_CHAT_ID is missing from .env")
    sys.exit(1)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("OTC-BOT")


# ============================================================
# GLOBAL STATE
# ============================================================

API = None

# Stores the last candle that generated a signal for each pair.
LAST_SIGNAL_CANDLE = {}

# Prevents multiple threads from refreshing asset mappings.
ASSET_LOCK = threading.Lock()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    """
    Send a Telegram message.

    Returns:
        True  -> successful
        False -> failed
    """

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=10,
        )

        if response.ok:
            logger.info("Telegram signal sent.")
            return True

        logger.error(
            "Telegram error: %s",
            response.text,
        )

    except requests.RequestException as exc:
        logger.error(
            "Telegram request failed: %s",
            exc,
        )

    return False


# ============================================================
# TIME FORMATTING
# ============================================================

def format_time(timestamp):
    """
    Windows-safe time formatting.
    """

    return datetime.fromtimestamp(timestamp).strftime(
        "%I:%M %p"
    ).lstrip("0")


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():
    """
    Attempt to use IQ Option's server timestamp.

    Falls back to local Unix time if unavailable.
    """

    try:
        server_timestamp = API.api.timesync.server_timestamp

        if server_timestamp:
            return float(server_timestamp)

    except Exception:
        pass

    return time.time()


# ============================================================
# CONNECTION
# ============================================================

def connect_iq_option():
    """
    Establish the IQ Option connection.
    """

    global API

    while True:

        try:

            logger.info("=" * 65)
            logger.info("CONNECTING TO IQ OPTION")
            logger.info("=" * 65)

            API = IQ_Option(
                IQ_EMAIL,
                IQ_PASSWORD,
            )

            check, reason = API.connect()

            if check:

                logger.info(
                    "IQ Option connection successful."
                )

                try:
                    API.change_balance("PRACTICE")

                    balance = API.get_balance()

                    logger.info(
                        "Practice balance: $%.2f",
                        balance,
                    )

                except Exception as exc:

                    logger.warning(
                        "Could not retrieve practice balance: %s",
                        exc,
                    )

                return True

            logger.error(
                "IQ Option connection failed: %s",
                reason,
            )

        except Exception as exc:

            logger.exception(
                "Connection exception: %s",
                exc,
            )

        logger.info(
            "Retrying connection in %s seconds...",
            RECONNECT_DELAY,
        )

        time.sleep(RECONNECT_DELAY)


# ============================================================
# CONNECTION CHECK
# ============================================================

def connection_alive():
    """
    Check whether the websocket connection appears alive.
    """

    try:
        return API.check_connect()

    except Exception:
        return False


# ============================================================
# DYNAMIC OTC ASSET MAPPING
# ============================================================

def refresh_otc_asset_mappings():
    """
    Dynamically obtain the current IQ Option binary/turbo
    asset IDs.

    IMPORTANT:
        This deliberately does NOT call:

            API.update_ACTIVES_OPCODE()
            API.get_all_open_time()

        Those functions perform additional network requests
        that are unnecessary for our candle scanner.

    Instead, we directly request:

        api_option_init_all

    and extract the binary/turbo asset IDs.
    """

    global API

    with ASSET_LOCK:

        logger.info("=" * 65)
        logger.info("REFRESHING OTC ASSET MAPPINGS")
        logger.info("=" * 65)

        missing_before = [
            pair
            for pair in OTC_PAIRS
            if stable_api.OP_code.ACTIVES.get(pair) is None
        ]

        if not missing_before:

            logger.info(
                "All OTC asset IDs are already available."
            )

            return True

        logger.info(
            "Missing OTC mappings: %s",
            ", ".join(missing_before),
        )

        try:

            # Clear the previous result.
            API.api.api_option_init_all_result = None

            start_time = time.time()

            logger.info(
                "Requesting binary/turbo initialization data..."
            )

            # Direct websocket request.
            API.api.get_api_option_init_all()

            # Bounded wait.
            while (
                API.api.api_option_init_all_result is None
                and time.time() - start_time
                < ASSET_REFRESH_TIMEOUT
            ):

                time.sleep(0.1)

            result = API.api.api_option_init_all_result

            elapsed = time.time() - start_time

            if result is None:

                logger.error(
                    "Asset initialization timed out after %.1f seconds.",
                    elapsed,
                )

                return False

            logger.info(
                "Asset initialization received in %.2f seconds.",
                elapsed,
            )

            if not result.get("isSuccessful"):

                logger.error(
                    "IQ Option returned unsuccessful asset initialization."
                )

                return False

            result_data = result.get("result", {})

            found = {}

            # ------------------------------------------------
            # BINARY + TURBO
            # ------------------------------------------------

            for market_type in ("binary", "turbo"):

                market_data = result_data.get(
                    market_type,
                    {},
                )

                actives = market_data.get(
                    "actives",
                    {},
                )

                for active_id, active_data in actives.items():

                    try:

                        raw_name = active_data.get(
                            "name",
                            "",
                        )

                        if "." in raw_name:

                            asset_name = raw_name.split(
                                ".",
                                1,
                            )[1]

                        else:

                            asset_name = raw_name

                        if asset_name in OTC_PAIRS:

                            numeric_id = int(active_id)

                            # Update the exact dictionary used by
                            # stable_api.get_candles().
                            stable_api.OP_code.ACTIVES[
                                asset_name
                            ] = numeric_id

                            found[asset_name] = numeric_id

                    except Exception as exc:

                        logger.debug(
                            "Could not process active %s: %s",
                            active_id,
                            exc,
                        )

            # ------------------------------------------------
            # RESULTS
            # ------------------------------------------------

            logger.info("")
            logger.info("CURRENT OTC ASSET MAPPINGS")
            logger.info("-" * 65)

            all_found = True

            for pair in OTC_PAIRS:

                active_id = stable_api.OP_code.ACTIVES.get(
                    pair
                )

                if active_id is not None:

                    logger.info(
                        "  %-15s -> %s",
                        pair,
                        active_id,
                    )

                else:

                    logger.error(
                        "  %-15s -> NOT FOUND",
                        pair,
                    )

                    all_found = False

            logger.info("-" * 65)

            if all_found:

                logger.info(
                    "All 8 OTC pairs successfully mapped."
                )

            else:

                logger.warning(
                    "One or more OTC pairs were not returned "
                    "by IQ Option."
                )

            return all_found

        except Exception as exc:

            logger.exception(
                "OTC asset refresh failed: %s",
                exc,
            )

            return False


# ============================================================
# VERIFY REQUIRED ASSETS
# ============================================================

def verify_required_assets():
    """
    Make sure all 8 requested OTC assets exist in the
    runtime ACTIVES dictionary.
    """

    logger.info("")
    logger.info("VERIFYING REQUIRED OTC ASSETS")
    logger.info("-" * 65)

    missing = []

    for pair in OTC_PAIRS:

        active_id = stable_api.OP_code.ACTIVES.get(
            pair
        )

        if active_id is None:

            logger.error(
                "MISSING: %s",
                pair,
            )

            missing.append(pair)

        else:

            logger.info(
                "READY:   %-15s -> %s",
                pair,
                active_id,
            )

    logger.info("-" * 65)

    if missing:

        logger.error(
            "Missing assets: %s",
            ", ".join(missing),
        )

        return False

    logger.info(
        "All 8 OTC pairs are ready."
    )

    return True


# ============================================================
# GET COMPLETED CANDLES
# ============================================================

def get_completed_candles(pair):
    """
    Retrieve 15 one-minute candles and remove the currently
    forming candle.

    Returns:
        list of completed candles
    """

    try:

        if stable_api.OP_code.ACTIVES.get(pair) is None:

            logger.warning(
                "%s has no active ID.",
                pair,
            )

            return []

        end_time = get_server_time()

        candles = API.get_candles(
            pair,
            TIMEFRAME,
            CANDLE_COUNT,
            end_time,
        )

        if not candles:

            return []

        completed = []

        for candle in candles:

            candle_from = float(
                candle.get("from", 0)
            )

            candle_to = float(
                candle.get(
                    "to",
                    candle_from + TIMEFRAME,
                )
            )

            # A candle is completed only when its ending
            # timestamp has passed.
            if candle_to <= end_time:

                completed.append(candle)

        completed.sort(
            key=lambda x: float(x["from"])
        )

        return completed[-CANDLE_COUNT:]

    except Exception as exc:

        logger.error(
            "%s candle error: %s",
            pair,
            exc,
        )

        return []


# ============================================================
# CANDLE COLOR
# ============================================================

def candle_color(candle):
    """
    Determine candle direction.

    Returns:
        GREEN
        RED
        DOJI
    """

    open_price = float(
        candle["open"]
    )

    close_price = float(
        candle["close"]
    )

    if close_price > open_price:

        return "GREEN"

    if close_price < open_price:

        return "RED"

    return "DOJI"


# ============================================================
# STREAK ANALYSIS
# ============================================================

def analyze_streak(candles):
    """
    Analyze the most recent completed candles.

    Returns:

        color
        streak_count
        last_candle

    A DOJI breaks the streak.
    """

    if not candles:

        return None, 0, None

    last_candle = candles[-1]

    last_color = candle_color(
        last_candle
    )

    if last_color == "DOJI":

        return "DOJI", 0, last_candle

    streak = 0

    for candle in reversed(candles):

        color = candle_color(candle)

        if color != last_color:

            break

        streak += 1

    return (
        last_color,
        streak,
        last_candle,
    )


# ============================================================
# BUILD SIGNAL
# ============================================================

def build_signal(
    pair,
    color,
    streak,
    candle,
):
    """
    Build the Telegram reversal signal.
    """

    candle_time = float(
        candle["from"]
    )

    entry_time = candle_time + TIMEFRAME

    if color == "GREEN":

        prediction = "REVERSAL DOWN"
        direction = "SELL / LOWER"

    else:

        prediction = "REVERSAL UP"
        direction = "BUY / HIGHER"

    level_1 = entry_time + 60
    level_2 = entry_time + 120
    level_3 = entry_time + 180

    message = (
        "🚨 <b>OTC REVERSAL SIGNAL</b>\n"
        "\n"
        f"📊 <b>Pair:</b> {pair}\n"
        f"⏱ <b>Timeframe:</b> 1 Minute\n"
        f"🔥 <b>Streak:</b> {streak} {color} candles\n"
        f"🔄 <b>Prediction:</b> {prediction}\n"
        f"🎯 <b>Direction:</b> {direction}\n"
        "\n"
        f"🕐 <b>Entry:</b> {format_time(entry_time)}\n"
        "\n"
        "💰 <b>Martingale Schedule</b>\n"
        f"Level 1: {format_time(level_1)}\n"
        f"Level 2: {format_time(level_2)}\n"
        f"Level 3: {format_time(level_3)}\n"
        "\n"
        f"🕯 <b>Signal candle:</b> "
        f"{format_time(candle_time)}\n"
    )

    return message


# ============================================================
# PROCESS ONE PAIR
# ============================================================

def process_pair(pair):
    """
    Analyze one OTC pair.
    """

    try:

        candles = get_completed_candles(
            pair
        )

        if len(candles) < MIN_STREAK:

            return

        color, streak, last_candle = analyze_streak(
            candles
        )

        if color not in ("GREEN", "RED"):

            return

        logger.info(
            "%-15s | %s streak = %d",
            pair,
            color,
            streak,
        )

        # We trigger specifically when the streak reaches
        # seven candles.
        if streak != MIN_STREAK:

            return

        candle_id = int(
            float(last_candle["from"])
        )

        # Prevent duplicate alerts.
        if LAST_SIGNAL_CANDLE.get(pair) == candle_id:

            return

        message = build_signal(
            pair,
            color,
            streak,
            last_candle,
        )

        sent = send_telegram(
            message
        )

        if sent:

            LAST_SIGNAL_CANDLE[pair] = candle_id

            logger.info(
                "SIGNAL GENERATED: %s",
                pair,
            )

    except Exception as exc:

        logger.exception(
            "Error processing %s: %s",
            pair,
            exc,
        )


# ============================================================
# SCAN ALL PAIRS
# ============================================================

def scan_all_pairs():
    """
    Sequentially scan all 8 OTC pairs.

    Sequential scanning is intentional because it avoids
    sending 8 simultaneous websocket candle requests through
    this older iqoptionapi implementation.
    """

    for pair in OTC_PAIRS:

        process_pair(pair)


# ============================================================
# MAIN BOT LOOP
# ============================================================

def run_bot():

    global API

    logger.info("")
    logger.info("=" * 65)
    logger.info("IQ OPTION OTC REVERSAL SCANNER")
    logger.info("=" * 65)
    logger.info(
        "Pairs: %d",
        len(OTC_PAIRS),
    )
    logger.info(
        "Timeframe: 1 minute"
    )
    logger.info(
        "Candles: %d",
        CANDLE_COUNT,
    )
    logger.info(
        "Required streak: %d",
        MIN_STREAK,
    )
    logger.info(
        "Polling interval: %d seconds",
        POLL_INTERVAL,
    )
    logger.info("=" * 65)

    # --------------------------------------------------------
    # CONNECT
    # --------------------------------------------------------

    if not connect_iq_option():

        logger.error(
            "Unable to establish IQ Option connection."
        )

        return

    # --------------------------------------------------------
    # REFRESH OTC ASSET IDS
    # --------------------------------------------------------

    if not refresh_otc_asset_mappings():

        logger.error(
            "Could not obtain all required OTC asset IDs."
        )

        logger.error(
            "The bot will not start with incomplete mappings."
        )

        return

    # --------------------------------------------------------
    # VERIFY
    # --------------------------------------------------------

    if not verify_required_assets():

        logger.error(
            "Required OTC assets are missing."
        )

        return

    # --------------------------------------------------------
    # START SCANNER
    # --------------------------------------------------------

    logger.info("")
    logger.info("=" * 65)
    logger.info("OTC SCANNER STARTED")
    logger.info("=" * 65)

    send_telegram(
        "🤖 <b>OTC Scanner Started</b>\n\n"
        "Monitoring 8 IQ Option OTC pairs.\n"
        "Timeframe: 1 minute\n"
        "Strategy: 7-candle reversal\n"
        "Mode: SIGNAL ONLY"
    )

    while True:

        try:

            # ------------------------------------------------
            # CONNECTION CHECK
            # ------------------------------------------------

            if not connection_alive():

                logger.warning(
                    "IQ Option connection lost."
                )

                logger.info(
                    "Reconnecting..."
                )

                connect_iq_option()

                # Refresh IDs after reconnect because the
                # websocket/session may have changed.
                refresh_otc_asset_mappings()

                if not verify_required_assets():

                    logger.warning(
                        "Asset mapping incomplete after reconnect."
                    )

                    time.sleep(
                        RECONNECT_DELAY
                    )

                    continue

            # ------------------------------------------------
            # SCAN
            # ------------------------------------------------

            cycle_start = time.time()

            logger.info("")
            logger.info(
                "========== SCAN CYCLE =========="
            )

            scan_all_pairs()

            elapsed = time.time() - cycle_start

            logger.info(
                "Scan completed in %.2f seconds.",
                elapsed,
            )

            # ------------------------------------------------
            # WAIT
            # ------------------------------------------------

            sleep_time = max(
                1,
                POLL_INTERVAL - elapsed,
            )

            logger.info(
                "Next scan in %d seconds...",
                sleep_time,
            )

            time.sleep(
                sleep_time
            )

        except KeyboardInterrupt:

            logger.info("")
            logger.info(
                "Bot stopped by user."
            )

            break

        except Exception as exc:

            logger.exception(
                "Main loop error: %s",
                exc,
            )

            time.sleep(
                RECONNECT_DELAY
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        run_bot()

    except KeyboardInterrupt:

        print(
            "\nBot stopped."
        )

    except Exception as exc:

        logger.exception(
            "Fatal error: %s",
            exc,
        )

