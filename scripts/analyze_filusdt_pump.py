#!/usr/bin/env python3
"""
FILUSDT Pump Analysis Script
Analyzes all signals for FILUSDT to identify precursors to the Nov 6, 2025 pump
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

# Add parent directory to path to import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DATABASE

def get_db_connection():
    """Establish database connection"""
    return psycopg2.connect(**DATABASE, cursor_factory=RealDictCursor)

def get_filusdt_signals_with_prices(conn):
    """
    Retrieve all FILUSDT signals
    """
    query = """
    SELECT
        s.id,
        s.trading_pair_id,
        s.pair_symbol,
        s.signal_type,
        s.detected_at,
        s.signal_timestamp,
        s.spike_ratio_7d,
        s.spike_ratio_14d,
        s.spike_ratio_30d,
        s.signal_strength,
        s.baseline_7d,
        s.baseline_14d,
        s.baseline_30d,
        s.volume,
        s.price_at_signal,
        s.initial_confidence,
        s.status,
        s.pump_realized,
        s.max_price_increase,
        s.time_to_pump_hours
    FROM pump.signals s
    WHERE s.pair_symbol = 'FILUSDT'
    ORDER BY s.detected_at ASC
    """

    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()

def get_price_at_time(conn, trading_pair_id, timestamp_ms):
    """
    Get price from candles table at specific time
    timestamp_ms: Unix timestamp in milliseconds
    """
    query = """
    SELECT
        open_time,
        open_price,
        close_price,
        high_price,
        low_price
    FROM candles
    WHERE trading_pair_id = %s
      AND interval_id = 4  -- 4h candles
      AND open_time <= %s
    ORDER BY open_time DESC
    LIMIT 1
    """

    with conn.cursor() as cur:
        cur.execute(query, (trading_pair_id, timestamp_ms))
        result = cur.fetchone()
        return result if result else None

def get_price_range_after_signal(conn, trading_pair_id, start_time_ms, hours=48):
    """
    Get price range after signal for specified hours
    """
    end_time_ms = start_time_ms + (hours * 3600 * 1000)

    query = """
    SELECT
        open_time,
        close_price,
        high_price,
        low_price
    FROM candles
    WHERE trading_pair_id = %s
      AND interval_id = 4  -- 4h candles
      AND open_time >= %s
      AND open_time <= %s
    ORDER BY open_time ASC
    """

    with conn.cursor() as cur:
        cur.execute(query, (trading_pair_id, start_time_ms, end_time_ms))
        return cur.fetchall()

def analyze_price_movement(signal, price_candles):
    """
    Calculate price changes after signal
    """
    if not price_candles or not signal['price_at_signal']:
        return None

    signal_price = float(signal['price_at_signal'])

    max_gain = 0
    max_gain_time = None

    for candle in price_candles:
        high = float(candle['high_price'])
        pct_gain = ((high - signal_price) / signal_price) * 100

        if pct_gain > max_gain:
            max_gain = pct_gain
            max_gain_time = candle['open_time']

    return {
        'max_gain_pct': max_gain,
        'max_gain_time_ms': max_gain_time,
        'max_gain_time_dt': datetime.fromtimestamp(max_gain_time / 1000) if max_gain_time else None
    }

def main():
    print("=" * 80)
    print("FILUSDT PUMP ANALYSIS")
    print("Analyzing signals as precursors to Nov 6, 2025 pump")
    print("=" * 80)
    print()

    # Connect to database
    conn = get_db_connection()

    try:
        # Get all FILUSDT signals
        print("📊 Retrieving all FILUSDT signals...")
        signals = get_filusdt_signals_with_prices(conn)
        print(f"✓ Found {len(signals)} signals for FILUSDT")
        print()

        if not signals:
            print("❌ No signals found for FILUSDT. Exiting.")
            return

        # Pump start time: Nov 6, 2025 around 11-12:00 UTC
        pump_start = datetime(2025, 11, 6, 11, 30, 0, tzinfo=timezone.utc)
        pump_start_ms = int(pump_start.timestamp() * 1000)

        # Analyze each signal
        print("💰 Analyzing price movements for each signal...")
        print()

        precursors = []  # Signals within 48h before pump

        for signal in signals:
            # Convert signal_timestamp to datetime if it's string
            if isinstance(signal['signal_timestamp'], str):
                signal_time = datetime.fromisoformat(signal['signal_timestamp'].replace('Z', '+00:00'))
            else:
                signal_time = signal['signal_timestamp']

            signal_time_ms = int(signal_time.timestamp() * 1000)

            # Get price movements after signal
            price_candles = get_price_range_after_signal(
                conn,
                signal['trading_pair_id'],
                signal_time_ms,
                hours=48
            )

            price_analysis = analyze_price_movement(signal, price_candles)

            # Calculate hours before pump
            hours_before_pump = (pump_start - signal_time).total_seconds() / 3600

            # Add to signal data
            signal['signal_time'] = signal_time
            signal['hours_before_pump'] = hours_before_pump
            signal['price_analysis'] = price_analysis

            # Identify precursors (0-48h before pump)
            if 0 <= hours_before_pump <= 48:
                precursors.append(signal)

        # Display all signals
        print("=" * 80)
        print(f"ALL FILUSDT SIGNALS ({len(signals)} total)")
        print("=" * 80)
        print()

        for idx, signal in enumerate(signals, 1):
            signal_time = signal['signal_time'] if 'signal_time' in signal else signal['signal_timestamp']

            print(f"[{idx}/{len(signals)}] Signal ID: {signal['id']}")
            print(f"  Type: {signal['signal_type']}")
            print(f"  Time: {signal_time}")
            print(f"  Strength: {signal['signal_strength']}")
            print(f"  Spike Ratios: 7d={float(signal['spike_ratio_7d']):.1f}x, 14d={float(signal['spike_ratio_14d']):.1f}x, 30d={float(signal['spike_ratio_30d']):.1f}x")
            print(f"  Price at Signal: ${float(signal['price_at_signal']) if signal['price_at_signal'] else 'N/A'}")
            print(f"  Volume: {float(signal['volume']):,.0f}")

            if signal['price_analysis'] and signal['price_analysis']['max_gain_pct'] > 0:
                print(f"  Max Gain (48h): +{signal['price_analysis']['max_gain_pct']:.2f}%")
                print(f"    Reached at: {signal['price_analysis']['max_gain_time_dt']}")

            if signal['pump_realized']:
                print(f"  ✅ PUMP REALIZED: +{float(signal['max_price_increase']):.2f}% in {signal['time_to_pump_hours']}h")

            if 'hours_before_pump' in signal:
                print(f"  ⏰ Hours before Nov 6 pump: {signal['hours_before_pump']:.1f}h")

            print()

        # Display precursors
        if precursors:
            print("=" * 80)
            print(f"PUMP PRECURSORS - Signals within 48h before Nov 6, 2025 pump ({len(precursors)} signals)")
            print("=" * 80)
            print()

            # Sort by proximity to pump
            precursors_sorted = sorted(precursors, key=lambda x: x['hours_before_pump'])

            for signal in precursors_sorted:
                print(f"⚠️  Signal ID: {signal['id']} ({signal['signal_type']})")
                print(f"    Time: {signal['signal_time']}")
                print(f"    Hours before pump: {signal['hours_before_pump']:.1f}h")
                print(f"    Strength: {signal['signal_strength']}")
                print(f"    Spike Ratio (7d): {float(signal['spike_ratio_7d']):.1f}x")
                print(f"    Price: ${float(signal['price_at_signal']):.4f}")

                if signal['price_analysis'] and signal['price_analysis']['max_gain_pct'] > 0:
                    print(f"    Max Gain (48h): +{signal['price_analysis']['max_gain_pct']:.2f}%")

                print()

        # Summary
        print("=" * 80)
        print("SUMMARY STATISTICS")
        print("=" * 80)
        print()

        futures_signals = [s for s in signals if s['signal_type'] == 'FUTURES']
        spot_signals = [s for s in signals if s['signal_type'] == 'SPOT']

        print(f"Total Signals: {len(signals)}")
        print(f"  FUTURES: {len(futures_signals)}")
        print(f"  SPOT: {len(spot_signals)}")
        print()

        extreme_signals = [s for s in signals if s['signal_strength'] == 'EXTREME']
        strong_signals = [s for s in signals if s['signal_strength'] == 'STRONG']
        medium_signals = [s for s in signals if s['signal_strength'] == 'MEDIUM']

        print("Signal Strength Distribution:")
        print(f"  EXTREME: {len(extreme_signals)}")
        print(f"  STRONG: {len(strong_signals)}")
        print(f"  MEDIUM: {len(medium_signals)}")
        print()

        realized_pumps = [s for s in signals if s['pump_realized']]
        print(f"Realized Pumps: {len(realized_pumps)}")
        print()

        print(f"Precursor Signals (48h before Nov 6 pump): {len(precursors)}")
        if precursors:
            precursor_extreme = [s for s in precursors if s['signal_strength'] == 'EXTREME']
            precursor_strong = [s for s in precursors if s['signal_strength'] == 'STRONG']
            print(f"  EXTREME: {len(precursor_extreme)}")
            print(f"  STRONG: {len(precursor_strong)}")
        print()

        print("=" * 80)
        print("✅ Analysis complete!")
        print("=" * 80)

    finally:
        conn.close()

if __name__ == "__main__":
    main()
