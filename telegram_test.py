import os
import json
import urllib.parse
import urllib.request

from dotenv import load_dotenv



# ============================================================
# FIREFLY AI - TELEGRAM CONNECTION TEST
# ============================================================

print("=" * 60)
print("FIREFLY AI - TELEGRAM CONNECTION TEST")
print("=" * 60)


# ------------------------------------------------------------
# Load .env
# ------------------------------------------------------------

print("\nLoading environment variables...")

load_dotenv()


bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")


# ------------------------------------------------------------
# Validate configuration
# ------------------------------------------------------------

if not bot_token:

    print("\nERROR: TELEGRAM_BOT_TOKEN is missing.")

    print(
        "Check your .env file."
    )

    exit(1)


if not chat_id:

    print("\nERROR: TELEGRAM_CHAT_ID is missing.")

    print(
        "Check your .env file."
    )

    exit(1)


print("Telegram Bot Token: LOADED")
print("Telegram Chat ID: LOADED")


# ------------------------------------------------------------
# Create Telegram API URL
# ------------------------------------------------------------

url = (
    f"https://api.telegram.org/"
    f"bot{bot_token}/sendMessage"
)


# ------------------------------------------------------------
# Message
# ------------------------------------------------------------

message = (
    "🚨 FIREFLY AI TEST MESSAGE\n"
    "\n"
    "Telegram connection is working successfully.\n"
    "\n"
    "Firefly AI is ready to send trading signals."
)


# ------------------------------------------------------------
# Prepare request
# ------------------------------------------------------------

data = urllib.parse.urlencode(
    {
        "chat_id": chat_id,
        "text": message
    }
).encode("utf-8")


request = urllib.request.Request(
    url,
    data=data,
    method="POST"
)


# ------------------------------------------------------------
# Send message
# ------------------------------------------------------------

print("\nSending test message to Telegram...")


try:

    with urllib.request.urlopen(
        request,
        timeout=10
    ) as response:

        response_data = response.read().decode(
            "utf-8"
        )


    result = json.loads(response_data)


    # --------------------------------------------------------
    # Check Telegram response
    # --------------------------------------------------------

    if result.get("ok"):

        print(
            "\nSUCCESS!"
        )

        print(
            "Telegram accepted the message."
        )


        print(
            "\nTelegram API response:"
        )

        print(
            response_data
        )


        print(
            "\nCheck your Telegram app."
        )

        print(
            "You should have received the Firefly AI test message."
        )


    else:

        print(
            "\nTelegram returned an error:"
        )

        print(
            response_data
        )


except Exception as e:

    print(
        "\nTelegram connection failed:"
    )

    print(
        type(e).__name__,
        "-",
        str(e)
    )


print("\n" + "=" * 60)
print("TELEGRAM TEST COMPLETED")
print("=" * 60)