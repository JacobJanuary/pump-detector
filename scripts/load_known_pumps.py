#!/usr/bin/env python3
"""
Load known pump events from JSON into database
136 historical pumps for backtesting
"""

import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DATABASE

def load_pumps_from_json(json_file):
    """Load pump events from JSON file"""
    with open(json_file, 'r') as f:
        pumps = json.load(f)
    return pumps

def convert_timestamp_to_datetime(timestamp_ms):
    """Convert Unix timestamp in milliseconds to datetime"""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

def get_symbol_from_trading_pair_id(conn, trading_pair_id):
    """Get symbol from trading_pair_id"""
    with conn.cursor() as cur:
        cur.execute("SELECT pair_symbol FROM trading_pairs WHERE id = %s", (trading_pair_id,))
        result = cur.fetchone()
        return result['pair_symbol'] if result else None

def insert_known_pumps(conn, pumps):
    """Insert pump events into database"""

    inserted = 0
    skipped = 0
    errors = []

    for pump in pumps:
        try:
            trading_pair_id = pump['trading_pair_id']
            symbol = pump['symbol']
            pump_start = convert_timestamp_to_datetime(pump['pump_start_time'])
            start_price = pump['start_price']
            high_price = pump['high_price']
            price_after_24h = pump['price_after_24h']
            max_gain_24h = pump['max_gain_24h']

            # Calculate pump duration (24h is typical)
            pump_duration_hours = 24

            with conn.cursor() as cur:
                # Check if already exists
                cur.execute("""
                    SELECT id FROM pump.known_pump_events
                    WHERE pair_symbol = %s AND pump_start = %s
                """, (symbol, pump_start))

                if cur.fetchone():
                    skipped += 1
                    continue

                # Insert
                cur.execute("""
                    INSERT INTO pump.known_pump_events (
                        trading_pair_id,
                        pair_symbol,
                        pump_start,
                        start_price,
                        high_price,
                        price_after_24h,
                        max_gain_24h,
                        pump_duration_hours,
                        data_source
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    trading_pair_id,
                    symbol,
                    pump_start,
                    start_price,
                    high_price,
                    price_after_24h,
                    max_gain_24h,
                    pump_duration_hours,
                    'historical_analysis'
                ))

                inserted += 1

        except Exception as e:
            errors.append(f"{symbol} @ {pump_start}: {e}")
            continue

    conn.commit()

    return inserted, skipped, errors

def main():
    print("="*80)
    print("LOADING KNOWN PUMP EVENTS")
    print("="*80)
    print()

    # Load from JSON
    json_file = '/tmp/pump_analysis/pumps_found.json'
    print(f"Loading pumps from: {json_file}")

    try:
        pumps = load_pumps_from_json(json_file)
        print(f"✓ Loaded {len(pumps)} pumps from JSON")
        print()
    except Exception as e:
        print(f"❌ Error loading JSON: {e}")
        return 1

    # Connect to database
    print("Connecting to database...")
    try:
        conn = psycopg2.connect(**DATABASE, cursor_factory=RealDictCursor)
        print("✓ Connected")
        print()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1

    try:
        # Insert pumps
        print("Inserting pumps into database...")
        inserted, skipped, errors = insert_known_pumps(conn, pumps)

        print()
        print("="*80)
        print("RESULTS")
        print("="*80)
        print(f"Total pumps in JSON: {len(pumps)}")
        print(f"Inserted: {inserted}")
        print(f"Skipped (already exist): {skipped}")
        print(f"Errors: {len(errors)}")

        if errors:
            print()
            print("ERRORS:")
            for error in errors[:10]:  # Show first 10
                print(f"  - {error}")
            if len(errors) > 10:
                print(f"  ... and {len(errors) - 10} more")

        print()
        print("="*80)

        # Verify
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as total FROM pump.known_pump_events")
            total = cur.fetchone()['total']
            print(f"✓ Total known_pump_events in database: {total}")

            cur.execute("""
                SELECT
                    COUNT(DISTINCT pair_symbol) as unique_symbols,
                    MIN(pump_start) as earliest,
                    MAX(pump_start) as latest,
                    AVG(max_gain_24h) as avg_gain,
                    MAX(max_gain_24h) as max_gain
                FROM pump.known_pump_events
            """)
            stats = cur.fetchone()

            print(f"✓ Unique symbols: {stats['unique_symbols']}")
            print(f"✓ Period: {stats['earliest'].date()} to {stats['latest'].date()}")
            print(f"✓ Average gain: +{float(stats['avg_gain']):.1f}%")
            print(f"✓ Max gain: +{float(stats['max_gain']):.1f}%")

        print()
        print("="*80)
        print("✅ Done!")
        print("="*80)

    finally:
        conn.close()

    return 0

if __name__ == "__main__":
    sys.exit(main())
