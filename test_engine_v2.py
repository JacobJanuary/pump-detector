#!/usr/bin/env python3
"""
Test PumpDetectionEngine V2.0 on real data
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from engine.database_helper import PumpDatabaseHelper
from engine.pump_detection_engine import PumpDetectionEngine
from config.settings import DATABASE

def test_single_symbol(symbol='ICPUSDT'):
    """Test engine on a single symbol"""

    print(f"\n{'='*60}")
    print(f"Testing PumpDetectionEngine V2.0 on {symbol}")
    print(f"{'='*60}\n")

    # Connect
    db = PumpDatabaseHelper(DATABASE)
    db.connect()

    # Create engine
    engine = PumpDetectionEngine(db)

    print(f"Engine initialized with config:")
    print(f"  Min signals: {engine.min_signal_count}")
    print(f"  HIGH confidence: ≥{engine.high_conf_threshold}")
    print(f"  MEDIUM confidence: ≥{engine.medium_conf_threshold}")
    print(f"  Critical window: {engine.critical_window_start}-{engine.critical_window_end}h")
    print(f"  EXTREME threshold: ≥{engine.extreme_threshold}x")
    print(f"  VERY_STRONG threshold: ≥{engine.very_strong_threshold}x")
    print(f"  STRONG threshold: ≥{engine.strong_threshold}x\n")

    # Analyze
    print(f"Analyzing {symbol}...")
    result = engine.analyze_symbol(symbol)

    if result:
        print(f"\n🚨 PUMP PATTERN DETECTED for {symbol}!")
        print(f"{'='*60}")
        print(f"Confidence:     {result['confidence']}")
        print(f"Score:          {result['score']}/100")
        print(f"Pattern Type:   {result['pattern_type']}")
        print(f"Actionable:     {'✅ YES' if result['is_actionable'] else '❌ NO'}")
        print(f"ETA:            ~{result['eta_hours']} hours")
        print(f"\nSignals:")
        print(f"  Total signals:            {result['total_signals']}")
        print(f"  EXTREME signals:          {result['extreme_signals']}")
        print(f"  Critical window (48-72h): {result['critical_window_signals']}")

        print(f"\nFactor Scores:")
        for factor, score in result['analysis_details']['factor_scores'].items():
            print(f"  {factor:25s}: {score:.2f}/100")

        print(f"\nSignal Strength Distribution:")
        for strength, count in result['analysis_details']['strength_distribution'].items():
            print(f"  {strength:15s}: {count}")

        print(f"\nSignal Type Distribution:")
        for sig_type, count in result['analysis_details']['signal_type_distribution'].items():
            print(f"  {sig_type:15s}: {count}")

        print(f"\n{'='*60}\n")

    else:
        print(f"\n❌ No pump pattern detected for {symbol}")
        print(f"   (Fewer than {engine.min_signal_count} signals or score too low)\n")

    db.close()
    return result

def test_top_symbols():
    """Test engine on top symbols from database"""

    print(f"\n{'='*60}")
    print(f"Testing PumpDetectionEngine V2.0 on TOP symbols")
    print(f"{'='*60}\n")

    # Connect
    db = PumpDatabaseHelper(DATABASE)
    db.connect()

    # Get top symbols with most EXTREME signals
    import psycopg2
    from psycopg2.extras import RealDictCursor

    with db.conn.cursor() as cur:
        cur.execute("""
            SELECT
                pair_symbol,
                COUNT(*) as total_signals,
                COUNT(*) FILTER (WHERE signal_strength = 'EXTREME') as extreme_signals
            FROM pump.raw_signals
            WHERE signal_timestamp >= NOW() - INTERVAL '7 days'
            GROUP BY pair_symbol
            HAVING COUNT(*) >= 10
            ORDER BY extreme_signals DESC, total_signals DESC
            LIMIT 5
        """)

        top_symbols = cur.fetchall()

    print(f"Found {len(top_symbols)} top symbols to analyze\n")

    # Create engine
    engine = PumpDetectionEngine(db)

    detections = []

    for symbol_data in top_symbols:
        symbol = symbol_data['pair_symbol']
        total = symbol_data['total_signals']
        extreme = symbol_data['extreme_signals']

        print(f"Analyzing {symbol} ({total} signals, {extreme} EXTREME)...")

        result = engine.analyze_symbol(symbol)

        if result:
            detections.append(result)
            print(f"  ✅ DETECTED: {result['confidence']} confidence, score={result['score']:.2f}, "
                  f"pattern={result['pattern_type']}, actionable={result['is_actionable']}")
        else:
            print(f"  ❌ No pattern")

    print(f"\n{'='*60}")
    print(f"SUMMARY: {len(detections)}/{len(top_symbols)} symbols show pump patterns")
    print(f"{'='*60}\n")

    if detections:
        print("Actionable candidates:")
        for d in detections:
            if d['is_actionable']:
                print(f"  🎯 {d['pair_symbol']:12s} - {d['confidence']:6s} - Score: {d['score']:5.2f} - "
                      f"ETA: {d['eta_hours']:3d}h - Pattern: {d['pattern_type']}")

        print("\nOther detections:")
        for d in detections:
            if not d['is_actionable']:
                print(f"  📊 {d['pair_symbol']:12s} - {d['confidence']:6s} - Score: {d['score']:5.2f} - "
                      f"Pattern: {d['pattern_type']}")

    print()
    db.close()
    return detections

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Test PumpDetectionEngine V2.0')
    parser.add_argument('--symbol', type=str, help='Test specific symbol (e.g., ICPUSDT)')
    parser.add_argument('--top', action='store_true', help='Test top 5 symbols')

    args = parser.parse_args()

    if args.symbol:
        test_single_symbol(args.symbol)
    elif args.top:
        test_top_symbols()
    else:
        # Default: test ICPUSDT
        test_single_symbol('ICPUSDT')
