import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

from iqoptionapi.stable_api import IQ_Option
import iqoptionapi.stable_api as stable_api


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

OWNER_EMAIL = os.getenv("OWNER_EMAIL")
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD")

TIMEFRAME = 60

# We need 1,440 one-minute candles for one complete day.
CANDLES_PER_DAY = 24 * 60

# Number of candles requested in each API call.
# Using 500 keeps the requests comfortably below common
# API limits and allows us to retrieve the entire day in
# multiple batches.
CANDLE_BATCH_SIZE = 500

# Date we are analyzing.
REPORT_DATE = "2026-09-05"

# Nigeria / West Africa timezone = UTC+1.
# This makes 00:00:00 and 23:59:00 correspond to
# the user's local Nigerian time.
LOCAL_TIMEZONE = timezone(timedelta(hours=1))


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

if not OWNER_EMAIL:
    print("ERROR: OWNER_EMAIL is missing from .env")
    sys.exit(1)

if not OWNER_PASSWORD:
    print("ERROR: OWNER_PASSWORD is missing from .env")
    sys.exit(1)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("OTC-REPORT")


# ============================================================
# GLOBAL
# ============================================================

API = None


# ============================================================
# CONNECTION
# ============================================================

def connect_iq_option():
    """
    Connect to IQ Option.
    """

    global API

    logger.info("=" * 70)
    logger.info("CONNECTING TO IQ OPTION")
    logger.info("=" * 70)

    try:

        API = IQ_Option(
            OWNER_EMAIL,
            OWNER_PASSWORD,
        )

        check, reason = API.connect()

        if not check:

            logger.error(
                "IQ Option connection failed: %s",
                reason,
            )

            return False

        logger.info(
            "IQ Option connection successful."
        )

        # Use PRACTICE account.
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

    except Exception as exc:

        logger.exception(
            "Connection exception: %s",
            exc,
        )

        return False


# ============================================================
# REFRESH OTC ASSET MAPPINGS
# ============================================================

def refresh_otc_asset_mappings():
    """
    Obtain the IQ Option asset IDs for the eight OTC pairs.

    First checks whether the IDs are already available in
    stable_api.OP_code.ACTIVES.

    Only requests api_option_init_all when required.
    """

    logger.info("")
    logger.info("=" * 70)
    logger.info("REFRESHING OTC ASSET MAPPINGS")
    logger.info("=" * 70)

    # --------------------------------------------------------
    # FIRST: Check existing mappings
    # --------------------------------------------------------

    missing = [
        pair
        for pair in OTC_PAIRS
        if stable_api.OP_code.ACTIVES.get(pair) is None
    ]

    if not missing:

        logger.info(
            "All OTC asset mappings are already available."
        )

        logger.info("")
        logger.info("CURRENT OTC ASSET MAPPINGS")
        logger.info("-" * 70)

        for pair in OTC_PAIRS:

            active_id = stable_api.OP_code.ACTIVES.get(pair)

            logger.info(
                "READY: %-15s -> %s",
                pair,
                active_id,
            )

        logger.info("-" * 70)

        return True

    logger.info(
        "Missing OTC mappings: %s",
        ", ".join(missing),
    )

    # --------------------------------------------------------
    # SECOND: Request fresh mappings
    # --------------------------------------------------------

    try:

        API.api.api_option_init_all_result = None

        start_time = time.time()

        logger.info(
            "Requesting binary/turbo initialization data..."
        )

        API.api.get_api_option_init_all()

        while (
            API.api.api_option_init_all_result is None
            and time.time() - start_time < 30
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

        result_data = result.get(
            "result",
            {},
        )

        # ----------------------------------------------------
        # Extract binary + turbo assets
        # ----------------------------------------------------

        for market_type in (
            "binary",
            "turbo",
        ):

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

                        stable_api.OP_code.ACTIVES[
                            asset_name
                        ] = numeric_id

                except Exception:

                    continue

        # ----------------------------------------------------
        # Verify mappings
        # ----------------------------------------------------

        logger.info("")
        logger.info("CURRENT OTC ASSET MAPPINGS")
        logger.info("-" * 70)

        all_found = True

        for pair in OTC_PAIRS:

            active_id = stable_api.OP_code.ACTIVES.get(
                pair
            )

            if active_id is not None:

                logger.info(
                    "READY: %-15s -> %s",
                    pair,
                    active_id,
                )

            else:

                logger.error(
                    "MISSING: %-15s -> NOT FOUND",
                    pair,
                )

                all_found = False

        logger.info("-" * 70)

        return all_found

    except Exception as exc:

        logger.exception(
            "OTC asset refresh failed: %s",
            exc,
        )

        return False

# ============================================================
# DATE RANGE
# ============================================================

def get_report_range():
    """
    Convert the requested Nigerian local date into Unix
    timestamps.

    Report period:

        06 September 2026 00:00:00
        through
        06 September 2026 23:59:00

    The end boundary is the start of the next day.
    """

    year, month, day = map(
        int,
        REPORT_DATE.split("-"),
    )

    local_start = datetime(
        year,
        month,
        day,
        0,
        0,
        0,
        tzinfo=LOCAL_TIMEZONE,
    )

    local_end = local_start + timedelta(
        days=1
    )

    start_timestamp = int(
        local_start.timestamp()
    )

    end_timestamp = int(
        local_end.timestamp()
    )

    return (
        start_timestamp,
        end_timestamp,
        local_start,
        local_end,
    )


# ============================================================
# FETCH HISTORICAL CANDLES
# ============================================================

def get_historical_candles(pair):
    """
    Retrieve all one-minute candles for the requested date.

    Because one day contains 1,440 one-minute candles, the
    candles are retrieved in multiple batches.

    Returns:
        list of candles covering the requested date.
    """

    if stable_api.OP_code.ACTIVES.get(pair) is None:

        logger.error(
            "%s has no active ID.",
            pair,
        )

        return []

    (
        start_timestamp,
        end_timestamp,
        local_start,
        local_end,
    ) = get_report_range()

    logger.info("")
    logger.info(
        "Fetching %s",
        pair,
    )

    logger.info(
        "Period: %s to %s",
        local_start.strftime("%Y-%m-%d %H:%M:%S"),
        (
            local_end - timedelta(seconds=60)
        ).strftime("%Y-%m-%d %H:%M:%S"),
    )

    all_candles = []

    # Start from the end of the requested period.
    cursor = end_timestamp

    batch_number = 0

    while cursor > start_timestamp:

        batch_number += 1

        try:

            logger.info(
                "  Batch %d: requesting up to %d candles...",
                batch_number,
                CANDLE_BATCH_SIZE,
            )

            candles = API.get_candles(
                pair,
                TIMEFRAME,
                CANDLE_BATCH_SIZE,
                cursor,
            )

            if not candles:

                logger.warning(
                    "  No candles returned."
                )

                break

            logger.info(
                "  Received %d candles.",
                len(candles),
            )

            # ------------------------------------------------
            # Add only candles belonging to requested period.
            # ------------------------------------------------

            oldest_timestamp = None

            for candle in candles:

                candle_from = float(
                    candle.get(
                        "from",
                        0,
                    )
                )

                candle_to = float(
                    candle.get(
                        "to",
                        candle_from + TIMEFRAME,
                    )
                )

                if (
                    candle_from >= start_timestamp
                    and candle_from < end_timestamp
                    and candle_to <= end_timestamp
                ):

                    all_candles.append(
                        candle
                    )

                if oldest_timestamp is None:

                    oldest_timestamp = candle_from

                else:

                    oldest_timestamp = min(
                        oldest_timestamp,
                        candle_from,
                    )

            # ------------------------------------------------
            # Move cursor backwards.
            # ------------------------------------------------

            if oldest_timestamp is None:

                break

            next_cursor = int(
                oldest_timestamp
            ) - 1

            # Protect against cursor not moving.
            if next_cursor >= cursor:

                logger.warning(
                    "Cursor did not move backwards. Stopping."
                )

                break

            cursor = next_cursor

            # Safety limit.
            if batch_number > 10:

                logger.warning(
                    "Too many batches. Stopping for safety."
                )

                break

        except Exception as exc:

            logger.error(
                "%s batch error: %s",
                pair,
                exc,
            )

            break

    # --------------------------------------------------------
    # Remove duplicates.
    # --------------------------------------------------------

    unique_candles = {}

    for candle in all_candles:

        candle_from = int(
            float(candle["from"])
        )

        unique_candles[candle_from] = candle

    # --------------------------------------------------------
    # Sort chronologically.
    # --------------------------------------------------------

    candles = sorted(
        unique_candles.values(),
        key=lambda x: float(x["from"]),
    )

    logger.info(
        "  Total unique candles collected: %d",
        len(candles),
    )

    return candles


# ============================================================
# CANDLE COLOR
# ============================================================

def candle_color(candle):
    """
    Determine whether a candle is GREEN, RED or DOJI.
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

def calculate_max_streaks(candles):
    """
    Calculate the maximum consecutive GREEN and RED streaks
    across the entire requested period.

    A DOJI breaks both streaks.
    """

    highest_green = 0
    highest_red = 0

    current_green = 0
    current_red = 0

    for candle in candles:

        color = candle_color(
            candle
        )

        if color == "GREEN":

            current_green += 1
            current_red = 0

            highest_green = max(
                highest_green,
                current_green,
            )

        elif color == "RED":

            current_red += 1
            current_green = 0

            highest_red = max(
                highest_red,
                current_red,
            )

        else:

            # DOJI breaks both streaks.
            current_green = 0
            current_red = 0

    return (
        highest_green,
        highest_red,
    )


# ============================================================
# FIND STREAK DETAILS
# ============================================================

def find_highest_streak_details(candles):
    """
    Find the highest GREEN and RED streaks and their
    start/end times.

    Returns:

        green_count
        green_start
        green_end
        red_count
        red_start
        red_end
    """

    highest_green = 0
    highest_red = 0

    current_green = 0
    current_red = 0

    current_green_start = None
    current_red_start = None

    highest_green_start = None
    highest_green_end = None

    highest_red_start = None
    highest_red_end = None

    for candle in candles:

        candle_from = float(
            candle["from"]
        )

        candle_to = float(
            candle.get(
                "to",
                candle_from + TIMEFRAME,
            )
        )

        color = candle_color(
            candle
        )

        # ----------------------------------------------------
        # GREEN
        # ----------------------------------------------------

        if color == "GREEN":

            current_green += 1
            current_red = 0

            if current_green == 1:

                current_green_start = candle_from

            if current_green > highest_green:

                highest_green = current_green

                highest_green_start = (
                    current_green_start
                )

                highest_green_end = (
                    candle_to
                )

        # ----------------------------------------------------
        # RED
        # ----------------------------------------------------

        elif color == "RED":

            current_red += 1
            current_green = 0

            if current_red == 1:

                current_red_start = candle_from

            if current_red > highest_red:

                highest_red = current_red

                highest_red_start = (
                    current_red_start
                )

                highest_red_end = (
                    candle_to
                )

        # ----------------------------------------------------
        # DOJI
        # ----------------------------------------------------

        else:

            current_green = 0
            current_red = 0

    return (
        highest_green,
        highest_green_start,
        highest_green_end,
        highest_red,
        highest_red_start,
        highest_red_end,
    )


# ============================================================
# FORMAT LOCAL TIME
# ============================================================

def format_report_time(timestamp):
    """
    Convert Unix timestamp to Nigerian local time.
    """

    if timestamp is None:

        return "-"

    return datetime.fromtimestamp(
        timestamp,
        tz=LOCAL_TIMEZONE,
    ).strftime(
        "%H:%M"
    )


# ============================================================
# DISPLAY TABLE
# ============================================================

def display_report(results):
    """
    Display the final report in table format.
    """

    print("")
    print("")
    print("=" * 90)
    print(
        "FIREFLY AI - OTC CANDLESTICK STREAK REPORT"
    )
    print("=" * 90)

    print(
        f"DATE: {REPORT_DATE}"
    )

    print(
        "PERIOD: 00:00:00 - 23:59:00"
    )

    print(
        "TIMEFRAME: 1 MINUTE"
    )

    print("=" * 90)

    # --------------------------------------------------------
    # Main requested table.
    # --------------------------------------------------------

    print("")
    print(
        f"{'CURRENCY PAIR':<20}"
        f"{'CANDLES':>10}"
        f"{'MAX GREEN':>15}"
        f"{'MAX RED':>15}"
    )

    print("-" * 60)

    for result in results:

        print(
            f"{result['pair']:<20}"
            f"{result['candles']:>10}"
            f"{result['highest_green']:>15}"
            f"{result['highest_red']:>15}"
        )

    print("-" * 60)

    print("")
    print(
        "MAXIMUM GREEN = highest number of consecutive GREEN candles"
    )

    print(
        "MAXIMUM RED   = highest number of consecutive RED candles"
    )

    print("")


# ============================================================
# DISPLAY DETAILED STREAK INFORMATION
# ============================================================

def display_detailed_streaks(results):
    """
    Display the times at which the maximum streaks occurred.

    This is additional information to make the report useful
    for analyzing the 7-candle reversal strategy.
    """

    print("")
    print("=" * 90)
    print("HIGHEST STREAK DETAILS")
    print("=" * 90)

    print(
        f"{'PAIR':<18}"
        f"{'GREEN STREAK':>15}"
        f"{'GREEN TIME':>22}"
        f"{'RED STREAK':>15}"
        f"{'RED TIME':>22}"
    )

    print("-" * 95)

    for result in results:

        green_time = "-"

        if result["green_start"] is not None:

            green_time = (
                f"{format_report_time(result['green_start'])}"
                f" - "
                f"{format_report_time(result['green_end'])}"
            )

        red_time = "-"

        if result["red_start"] is not None:

            red_time = (
                f"{format_report_time(result['red_start'])}"
                f" - "
                f"{format_report_time(result['red_end'])}"
            )

        print(
            f"{result['pair']:<18}"
            f"{result['highest_green']:>15}"
            f"{green_time:>22}"
            f"{result['highest_red']:>15}"
            f"{red_time:>22}"
        )

    print("-" * 95)
    print("")


# ============================================================
# GENERATE REPORT
# ============================================================

def generate_report():

    global API

    logger.info("")
    logger.info("=" * 70)
    logger.info("FIREFLY AI HISTORICAL OTC REPORT")
    logger.info("=" * 70)

    logger.info(
        "Report date: %s",
        REPORT_DATE,
    )

    logger.info(
        "Timeframe: 1 minute",
    )

    logger.info(
        "Expected candles per pair: %d",
        CANDLES_PER_DAY,
    )

    logger.info("=" * 70)

    # --------------------------------------------------------
    # CONNECT
    # --------------------------------------------------------

    if not connect_iq_option():

        logger.error(
            "Unable to connect to IQ Option."
        )

        return

    # --------------------------------------------------------
    # REFRESH ASSETS
    # --------------------------------------------------------

    if not refresh_otc_asset_mappings():

        logger.error(
            "Could not obtain OTC asset mappings."
        )

        return

    # --------------------------------------------------------
    # PROCESS ALL PAIRS
    # --------------------------------------------------------

    results = []

    for pair in OTC_PAIRS:

        candles = get_historical_candles(
            pair
        )

        if not candles:

            logger.error(
                "No historical data available for %s",
                pair,
            )

            results.append(
                {
                    "pair": pair,
                    "candles": 0,
                    "highest_green": 0,
                    "highest_red": 0,
                    "green_start": None,
                    "green_end": None,
                    "red_start": None,
                    "red_end": None,
                }
            )

            continue

        (
            highest_green,
            green_start,
            green_end,
            highest_red,
            red_start,
            red_end,
        ) = find_highest_streak_details(
            candles
        )

        results.append(
            {
                "pair": pair,
                "candles": len(candles),
                "highest_green": highest_green,
                "highest_red": highest_red,
                "green_start": green_start,
                "green_end": green_end,
                "red_start": red_start,
                "red_end": red_end,
            }
        )

        logger.info(
            "%-15s | Candles: %4d | "
            "Max GREEN: %2d | Max RED: %2d",
            pair,
            len(candles),
            highest_green,
            highest_red,
        )

    # --------------------------------------------------------
    # DISPLAY
    # --------------------------------------------------------

    display_report(
        results
    )

    display_detailed_streaks(
        results
    )

    logger.info(
        "Historical report completed."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        generate_report()

    except KeyboardInterrupt:

        print(
            "\nReport generation stopped by user."
        )

    except Exception as exc:

        logger.exception(
            "Fatal error: %s",
            exc,
        )