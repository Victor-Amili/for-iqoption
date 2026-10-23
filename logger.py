import asyncio
import sqlite3
from datetime import datetime
from pocketoptionapi_async import AsyncPocketOptionClient

SSID_PAYLOAD = '42["auth",{"session": "itd3dnrfo38am7lbldeqklppph", "isDemo": 1, "uid": 131006989, "platform": 2, "isFastHistory": true}]'
ASSET = 'EURUSD_otc'
DB_NAME = 'market_data.db'

def init_db():
    """Initializes the SQLite database table for storing candles."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS candles (
            asset TEXT,
            time INTEGER PRIMARY KEY,
            open REAL,
            high REAL,
            low REAL,
            close REAL
        )
    ''')
    conn.commit()
    conn.close()

def save_candles_to_db(asset, df):
    """Saves fetched candles into SQLite, ignoring duplicates."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    saved_count = 0
    for _, row in df.iterrows():
        # Assuming dataframe index or a 'time' column holds the timestamp
        timestamp = int(row.name.timestamp()) if hasattr(row.name, 'timestamp') else int(row['time'])
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO candles (asset, time, open, high, low, close)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (asset, timestamp, row['open'], row['high'], row['low'], row['close']))
            if cursor.rowcount > 0:
                saved_count += 1
        except Exception as e:
            print(f"Error saving row: {e}")
            
    conn.commit()
    conn.close()
    return saved_count

async def main():
    init_db()
    print(f"Starting candle data logger for {ASSET}...")
    
    while True:
        client = AsyncPocketOptionClient(SSID_PAYLOAD, is_demo=True, enable_logging=False)
        try:
            await client.connect()
            print(f"[{datetime.now().strftime('%H:%M:%SConnected to broker. Fetching candles...' )}]")
            
            df = await client.get_candles_dataframe(asset=ASSET, timeframe=60)
            await client.disconnect()
            
            if df is not None and not df.empty:
                new_saved = save_candles_to_db(ASSET, df)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetched {len(df)} candles. Saved {new_saved} new unique candles to database.")
            else:
                print("No candle data returned.")
                
        except Exception as exc:
            print(f"Logger error: {exc}")
            try:
                await client.disconnect()
            except:
                pass
                
        # Wait 60 seconds before pulling the next candle update
        print("-" * 40)
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())