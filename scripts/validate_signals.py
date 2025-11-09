#!/usr/bin/env python3
"""
Signal Validation Script
========================
Independently verifies all calculations for pump detection signals.
Takes a signal_id and recalculates all metrics from source data to validate accuracy.

Usage:
    python validate_signals.py <signal_id>
    python validate_signals.py --all  # Validate all signals
    python validate_signals.py --random 10  # Validate 10 random signals
"""

import sys
import argparse
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE

class SignalValidator:
    """Validates signal calculations by recalculating from source data"""

    def __init__(self):
        self.conn = None
        self.connect()

    def connect(self):
        """Connect to database"""
        try:
            if not DATABASE.get('password'):
                conn_params = {
                    'dbname': DATABASE['dbname'],
                    'cursor_factory': RealDictCursor
                }
            else:
                conn_params = {
                    'dbname': DATABASE['dbname'],
                    'user': DATABASE.get('user'),
                    'password': DATABASE.get('password'),
                    'host': DATABASE.get('host', 'localhost'),
                    'port': DATABASE.get('port', 5432),
                    'cursor_factory': RealDictCursor
                }

            self.conn = psycopg2.connect(**conn_params)
            self.conn.autocommit = True
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            sys.exit(1)

    def get_signal(self, signal_id: int) -> Optional[Dict]:
        """Retrieve signal data from database"""
        query = """
        SELECT
            s.*,
            tp.exchange_id,
            tp.contract_type_id,
            tp.is_active
        FROM pump.signals s
        INNER JOIN public.trading_pairs tp ON s.trading_pair_id = tp.id
        WHERE s.id = %s
        """

        with self.conn.cursor() as cur:
            cur.execute(query, (signal_id,))
            return cur.fetchone()

    def get_candles_for_baseline(self, trading_pair_id: int, signal_timestamp: datetime,
                                  lookback_candles: int) -> List[Dict]:
        """Get candles needed for baseline calculation"""
        query = """
        SELECT
            to_timestamp(open_time / 1000) as candle_time,
            open_time,
            close_price,
            high_price,
            low_price,
            quote_asset_volume as volume
        FROM public.candles
        WHERE trading_pair_id = %s
          AND interval_id = 4  -- 4h candles
          AND to_timestamp(open_time / 1000) <= %s
        ORDER BY open_time DESC
        LIMIT %s
        """

        with self.conn.cursor() as cur:
            cur.execute(query, (trading_pair_id, signal_timestamp, lookback_candles + 1))
            return list(reversed(cur.fetchall()))  # Oldest to newest

    def get_price_movement_after_signal(self, trading_pair_id: int,
                                        signal_timestamp: datetime,
                                        entry_price: float) -> Dict:
        """Get price movement data after signal"""
        query = """
        SELECT
            MAX(high_price) as max_price,
            MIN(low_price) as min_price,
            (SELECT close_price FROM public.candles c2
             WHERE c2.trading_pair_id = %s AND c2.interval_id = 4
             ORDER BY c2.open_time DESC LIMIT 1) as current_price,
            COUNT(*) as candles_count
        FROM public.candles
        WHERE trading_pair_id = %s
          AND interval_id = 4
          AND to_timestamp(open_time / 1000) >= %s
        """

        with self.conn.cursor() as cur:
            cur.execute(query, (trading_pair_id, trading_pair_id, signal_timestamp))
            result = cur.fetchone()

            if result and entry_price > 0:
                result['max_gain_pct'] = ((result['max_price'] - entry_price) / entry_price * 100) if result['max_price'] else 0
                result['current_gain_pct'] = ((result['current_price'] - entry_price) / entry_price * 100) if result['current_price'] else 0
                result['max_drawdown_pct'] = ((entry_price - result['min_price']) / entry_price * 100) if result['min_price'] else 0

            return result

    def calculate_baseline_and_spike(self, candles: List[Dict]) -> Dict:
        """Calculate baseline and spike ratios from candle data"""
        if len(candles) < 2:
            return None

        # Last candle is the signal candle
        signal_candle = candles[-1]
        signal_volume = signal_candle['volume']

        # Calculate baselines
        # 7-day baseline: 42 candles (7 days * 6 candles per day for 4h)
        baseline_7d_candles = candles[-43:-1] if len(candles) >= 43 else candles[:-1]
        baseline_7d = sum(c['volume'] for c in baseline_7d_candles) / len(baseline_7d_candles) if baseline_7d_candles else 0

        # 14-day baseline: 84 candles
        baseline_14d_candles = candles[-85:-1] if len(candles) >= 85 else candles[:-1]
        baseline_14d = sum(c['volume'] for c in baseline_14d_candles) / len(baseline_14d_candles) if baseline_14d_candles else 0

        # 30-day baseline: 180 candles
        baseline_30d_candles = candles[-181:-1] if len(candles) >= 181 else candles[:-1]
        baseline_30d = sum(c['volume'] for c in baseline_30d_candles) / len(baseline_30d_candles) if baseline_30d_candles else 0

        # Calculate spike ratios
        spike_ratio_7d = signal_volume / baseline_7d if baseline_7d > 0 else 0
        spike_ratio_14d = signal_volume / baseline_14d if baseline_14d > 0 else 0
        spike_ratio_30d = signal_volume / baseline_30d if baseline_30d > 0 else 0

        return {
            'signal_volume': signal_volume,
            'baseline_7d': baseline_7d,
            'baseline_14d': baseline_14d,
            'baseline_30d': baseline_30d,
            'spike_ratio_7d': spike_ratio_7d,
            'spike_ratio_14d': spike_ratio_14d,
            'spike_ratio_30d': spike_ratio_30d,
            'signal_price': signal_candle['close_price'],
            'baseline_7d_candle_count': len(baseline_7d_candles),
            'baseline_14d_candle_count': len(baseline_14d_candles),
            'baseline_30d_candle_count': len(baseline_30d_candles)
        }

    def validate_confidence_score(self, signal: Dict) -> Dict:
        """Validate confidence score calculation"""
        # Recalculate confidence score components
        volume_score = 0
        if signal['futures_spike_ratio_7d'] >= 5.0:
            volume_score = 25
        elif signal['futures_spike_ratio_7d'] >= 3.0:
            volume_score = 20
        elif signal['futures_spike_ratio_7d'] >= 2.0:
            volume_score = 15
        else:
            volume_score = 10

        # OI Score
        oi_score = 0
        if signal.get('oi_change_pct'):
            if signal['oi_change_pct'] >= 50:
                oi_score = 25
            elif signal['oi_change_pct'] >= 30:
                oi_score = 20
            elif signal['oi_change_pct'] >= 15:
                oi_score = 15
            elif signal['oi_change_pct'] >= 5:
                oi_score = 10

        # Spot Sync Score
        spot_score = 0
        if signal.get('has_spot_sync'):
            if signal.get('spot_spike_ratio_7d', 0) >= 2.0:
                spot_score = 20
            elif signal.get('spot_spike_ratio_7d', 0) >= 1.5:
                spot_score = 10

        # Confirmation Score (from database)
        confirmation_query = """
        SELECT COUNT(*) as count
        FROM pump.signal_confirmations
        WHERE signal_id = %s
        """
        with self.conn.cursor() as cur:
            cur.execute(confirmation_query, (signal['id'],))
            confirmations = cur.fetchone()['count']

        confirmation_score = min(20, confirmations * 5)

        # Timing Score
        # Handle timezone-aware datetime
        detected_at = signal['detected_at']
        if detected_at.tzinfo is None:
            # If database returns naive datetime, assume UTC
            from datetime import timezone
            detected_at = detected_at.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
        else:
            from datetime import timezone
            now_utc = datetime.now(timezone.utc)

        hours_since = (now_utc - detected_at).total_seconds() / 3600
        if hours_since <= 4:
            timing_score = 10
        elif hours_since <= 12:
            timing_score = 7
        elif hours_since <= 24:
            timing_score = 5
        elif hours_since <= 48:
            timing_score = 3
        else:
            timing_score = 0

        total_score = volume_score + oi_score + spot_score + confirmation_score + timing_score

        # Get actual score from database
        score_query = """
        SELECT *
        FROM pump.signal_scores
        WHERE signal_id = %s
        """
        with self.conn.cursor() as cur:
            cur.execute(score_query, (signal['id'],))
            actual_score = cur.fetchone()

        return {
            'calculated': {
                'volume_score': volume_score,
                'oi_score': oi_score,
                'spot_score': spot_score,
                'confirmation_score': confirmation_score,
                'timing_score': timing_score,
                'total_score': total_score
            },
            'actual': actual_score,
            'confirmations_count': confirmations
        }

    def validate_signal(self, signal_id: int, verbose: bool = True) -> Dict:
        """Main validation function - validates all calculations for a signal"""

        if verbose:
            print(f"\n{'='*80}")
            print(f"VALIDATING SIGNAL ID: {signal_id}")
            print(f"{'='*80}")

        # Get signal data
        signal = self.get_signal(signal_id)
        if not signal:
            print(f"❌ Signal {signal_id} not found")
            return {'valid': False, 'error': 'Signal not found'}

        if verbose:
            print(f"\n📊 SIGNAL INFO:")
            print(f"   Pair: {signal['pair_symbol']}")
            print(f"   Status: {signal['status']}")
            print(f"   Strength: {signal['signal_strength']}")
            print(f"   Timestamp: {signal['signal_timestamp']}")
            print(f"   Detected at: {signal['detected_at']}")

        # Get candles for validation (need 181 candles: 180 for baseline + 1 signal)
        candles = self.get_candles_for_baseline(
            signal['trading_pair_id'],
            signal['signal_timestamp'],
            181
        )

        if len(candles) < 43:  # Minimum for 7-day baseline
            print(f"❌ Insufficient candle data: got {len(candles)}, need at least 43")
            return {'valid': False, 'error': 'Insufficient candle data'}

        # Recalculate metrics
        calculated = self.calculate_baseline_and_spike(candles)

        if verbose:
            print(f"\n📈 VOLUME & BASELINE VALIDATION:")
            print(f"   Signal Volume:")
            print(f"      Database: {signal['futures_volume']:,.2f}")
            print(f"      Calculated: {calculated['signal_volume']:,.2f}")
            print(f"      Match: {'✅' if abs(signal['futures_volume'] - calculated['signal_volume']) < 1 else '❌'}")

            print(f"\n   7-Day Baseline:")
            print(f"      Database: {signal['futures_baseline_7d']:,.2f} (from {signal.get('baseline_7d_candle_count', 'N/A')} candles)")
            print(f"      Calculated: {calculated['baseline_7d']:,.2f} (from {calculated['baseline_7d_candle_count']} candles)")
            diff_pct = abs(signal['futures_baseline_7d'] - calculated['baseline_7d']) / signal['futures_baseline_7d'] * 100 if signal['futures_baseline_7d'] > 0 else 0
            print(f"      Difference: {diff_pct:.2f}%")
            print(f"      Match: {'✅' if diff_pct < 1 else '⚠️' if diff_pct < 5 else '❌'}")

            print(f"\n   14-Day Baseline:")
            print(f"      Database: {signal['futures_baseline_14d']:,.2f}")
            print(f"      Calculated: {calculated['baseline_14d']:,.2f}")
            diff_pct = abs(signal['futures_baseline_14d'] - calculated['baseline_14d']) / signal['futures_baseline_14d'] * 100 if signal['futures_baseline_14d'] > 0 else 0
            print(f"      Difference: {diff_pct:.2f}%")
            print(f"      Match: {'✅' if diff_pct < 1 else '⚠️' if diff_pct < 5 else '❌'}")

            print(f"\n   30-Day Baseline:")
            print(f"      Database: {signal['futures_baseline_30d']:,.2f}")
            print(f"      Calculated: {calculated['baseline_30d']:,.2f}")
            diff_pct = abs(signal['futures_baseline_30d'] - calculated['baseline_30d']) / signal['futures_baseline_30d'] * 100 if signal['futures_baseline_30d'] > 0 else 0
            print(f"      Difference: {diff_pct:.2f}%")
            print(f"      Match: {'✅' if diff_pct < 1 else '⚠️' if diff_pct < 5 else '❌'}")

        # Validate spike ratios
        if verbose:
            print(f"\n🚀 SPIKE RATIO VALIDATION:")
            print(f"   7-Day Spike Ratio:")
            print(f"      Database: {signal['futures_spike_ratio_7d']:.4f}x")
            print(f"      Calculated: {calculated['spike_ratio_7d']:.4f}x")
            diff_pct = abs(signal['futures_spike_ratio_7d'] - calculated['spike_ratio_7d']) / signal['futures_spike_ratio_7d'] * 100 if signal['futures_spike_ratio_7d'] > 0 else 0
            print(f"      Difference: {diff_pct:.2f}%")
            print(f"      Match: {'✅' if diff_pct < 1 else '⚠️' if diff_pct < 5 else '❌'}")

            print(f"\n   14-Day Spike Ratio:")
            print(f"      Database: {signal['futures_spike_ratio_14d']:.4f}x")
            print(f"      Calculated: {calculated['spike_ratio_14d']:.4f}x")
            diff_pct = abs(signal['futures_spike_ratio_14d'] - calculated['spike_ratio_14d']) / signal['futures_spike_ratio_14d'] * 100 if signal['futures_spike_ratio_14d'] > 0 else 0
            print(f"      Difference: {diff_pct:.2f}%")
            print(f"      Match: {'✅' if diff_pct < 1 else '⚠️' if diff_pct < 5 else '❌'}")

        # Validate signal strength classification
        max_spike = max(calculated['spike_ratio_7d'], calculated['spike_ratio_14d'])
        if max_spike >= 5.0:
            expected_strength = 'EXTREME'
        elif max_spike >= 3.0:
            expected_strength = 'STRONG'
        elif max_spike >= 2.0:
            expected_strength = 'MEDIUM'
        elif max_spike >= 1.5:
            expected_strength = 'WEAK'
        else:
            expected_strength = 'BELOW_THRESHOLD'

        if verbose:
            print(f"\n💪 SIGNAL STRENGTH VALIDATION:")
            print(f"   Database: {signal['signal_strength']}")
            print(f"   Expected: {expected_strength}")
            print(f"   Match: {'✅' if signal['signal_strength'] == expected_strength else '❌'}")

        # Validate price movement (if signal is old enough)
        price_movement = self.get_price_movement_after_signal(
            signal['trading_pair_id'],
            signal['signal_timestamp'],
            calculated['signal_price']
        )

        if verbose:
            print(f"\n💰 PRICE MOVEMENT VALIDATION:")
            print(f"   Entry Price: ${calculated['signal_price']:.8f}")
            print(f"   Current Price: ${price_movement['current_price']:.8f}")
            print(f"   Max Price: ${price_movement['max_price']:.8f}")
            print(f"   Max Gain: {price_movement['max_gain_pct']:.2f}%")
            print(f"   Current Gain: {price_movement['current_gain_pct']:.2f}%")
            print(f"   Max Drawdown: {price_movement['max_drawdown_pct']:.2f}%")

            if signal['max_price_increase'] is not None:
                print(f"\n   Database Max Increase: {signal['max_price_increase']:.2f}%")
                print(f"   Calculated Max Gain: {price_movement['max_gain_pct']:.2f}%")
                diff = abs(signal['max_price_increase'] - price_movement['max_gain_pct'])
                print(f"   Difference: {diff:.2f}%")
                print(f"   Match: {'✅' if diff < 1 else '⚠️' if diff < 5 else '❌'}")

        # Validate confidence score
        confidence_validation = self.validate_confidence_score(signal)

        if verbose:
            print(f"\n🎯 CONFIDENCE SCORE VALIDATION:")
            print(f"   Calculated Breakdown:")
            print(f"      Volume Score: {confidence_validation['calculated']['volume_score']}/25")
            print(f"      OI Score: {confidence_validation['calculated']['oi_score']}/25")
            print(f"      Spot Sync Score: {confidence_validation['calculated']['spot_score']}/20")
            print(f"      Confirmation Score: {confidence_validation['calculated']['confirmation_score']}/20 ({confidence_validation['confirmations_count']} confirmations)")
            print(f"      Timing Score: {confidence_validation['calculated']['timing_score']}/10")
            print(f"      Total: {confidence_validation['calculated']['total_score']}/100")

            if confidence_validation['actual']:
                print(f"\n   Database Breakdown:")
                print(f"      Volume Score: {confidence_validation['actual']['volume_score']}/25")
                print(f"      OI Score: {confidence_validation['actual']['oi_score']}/25")
                print(f"      Spot Sync Score: {confidence_validation['actual']['spot_sync_score']}/20")
                print(f"      Confirmation Score: {confidence_validation['actual']['confirmation_score']}/20")
                print(f"      Timing Score: {confidence_validation['actual']['timing_score']}/10")
                print(f"      Total: {confidence_validation['actual']['total_score']}/100")
                print(f"      Confidence Level: {confidence_validation['actual']['confidence_level']}")

                # Note: timing score will differ because it's time-based
                non_timing_calc = (confidence_validation['calculated']['total_score'] -
                                  confidence_validation['calculated']['timing_score'])
                non_timing_actual = (confidence_validation['actual']['total_score'] -
                                    confidence_validation['actual']['timing_score'])

                print(f"\n   Total Match (excluding timing): {'✅' if non_timing_calc == non_timing_actual else '❌'}")

        # Calculate overall validation result
        baseline_7d_match = abs(signal['futures_baseline_7d'] - calculated['baseline_7d']) / signal['futures_baseline_7d'] * 100 < 5 if signal['futures_baseline_7d'] > 0 else False
        spike_7d_match = abs(signal['futures_spike_ratio_7d'] - calculated['spike_ratio_7d']) / signal['futures_spike_ratio_7d'] * 100 < 5 if signal['futures_spike_ratio_7d'] > 0 else False
        strength_match = signal['signal_strength'] == expected_strength

        validation_result = {
            'signal_id': signal_id,
            'pair_symbol': signal['pair_symbol'],
            'valid': baseline_7d_match and spike_7d_match and strength_match,
            'baseline_7d_match': baseline_7d_match,
            'spike_7d_match': spike_7d_match,
            'strength_match': strength_match,
            'calculated_metrics': calculated,
            'database_metrics': {
                'volume': signal['futures_volume'],
                'baseline_7d': signal['futures_baseline_7d'],
                'baseline_14d': signal['futures_baseline_14d'],
                'baseline_30d': signal['futures_baseline_30d'],
                'spike_ratio_7d': signal['futures_spike_ratio_7d'],
                'spike_ratio_14d': signal['futures_spike_ratio_14d'],
                'spike_ratio_30d': signal['futures_spike_ratio_30d'],
                'signal_strength': signal['signal_strength']
            },
            'price_movement': price_movement,
            'confidence': confidence_validation
        }

        if verbose:
            print(f"\n{'='*80}")
            print(f"VALIDATION RESULT: {'✅ PASS' if validation_result['valid'] else '❌ FAIL'}")
            print(f"{'='*80}\n")

        return validation_result

    def validate_multiple(self, signal_ids: List[int]) -> Dict:
        """Validate multiple signals and provide summary"""
        results = []

        print(f"\n{'='*80}")
        print(f"BATCH VALIDATION: {len(signal_ids)} signals")
        print(f"{'='*80}\n")

        for signal_id in signal_ids:
            try:
                result = self.validate_signal(signal_id, verbose=False)
                results.append(result)
                status = '✅' if result['valid'] else '❌'
                print(f"{status} Signal {signal_id:4d} - {result['pair_symbol']:15s} - "
                      f"{result['database_metrics']['spike_ratio_7d']:.2f}x - "
                      f"{result['database_metrics']['signal_strength']}")
            except Exception as e:
                print(f"❌ Signal {signal_id}: Error - {e}")
                results.append({'signal_id': signal_id, 'valid': False, 'error': str(e)})

        # Summary
        valid_count = sum(1 for r in results if r.get('valid', False))
        total = len(results)

        print(f"\n{'='*80}")
        print(f"BATCH VALIDATION SUMMARY")
        print(f"{'='*80}")
        print(f"Total Signals: {total}")
        print(f"Valid: {valid_count} ({valid_count/total*100:.1f}%)")
        print(f"Invalid: {total - valid_count} ({(total-valid_count)/total*100:.1f}%)")
        print(f"{'='*80}\n")

        return {
            'total': total,
            'valid': valid_count,
            'invalid': total - valid_count,
            'results': results
        }

    def get_random_signals(self, count: int = 10) -> List[int]:
        """Get random signal IDs from database"""
        query = """
        SELECT id
        FROM pump.signals
        ORDER BY RANDOM()
        LIMIT %s
        """

        with self.conn.cursor() as cur:
            cur.execute(query, (count,))
            return [row['id'] for row in cur.fetchall()]

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


def main():
    parser = argparse.ArgumentParser(
        description='Validate pump detection signal calculations',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('signal_id', nargs='?', type=int,
                       help='Signal ID to validate')
    parser.add_argument('--all', action='store_true',
                       help='Validate all signals (WARNING: may take a long time)')
    parser.add_argument('--random', type=int, metavar='N',
                       help='Validate N random signals')
    parser.add_argument('--ids', nargs='+', type=int, metavar='ID',
                       help='Validate specific signal IDs (space-separated)')

    args = parser.parse_args()

    validator = SignalValidator()

    try:
        if args.all:
            # Get all signal IDs
            with validator.conn.cursor() as cur:
                cur.execute("SELECT id FROM pump.signals ORDER BY id")
                signal_ids = [row['id'] for row in cur.fetchall()]

            print(f"⚠️  WARNING: Validating ALL {len(signal_ids)} signals. This may take a while...")
            response = input("Continue? (yes/no): ")
            if response.lower() != 'yes':
                print("Aborted.")
                return

            validator.validate_multiple(signal_ids)

        elif args.random:
            signal_ids = validator.get_random_signals(args.random)
            validator.validate_multiple(signal_ids)

        elif args.ids:
            validator.validate_multiple(args.ids)

        elif args.signal_id:
            validator.validate_signal(args.signal_id, verbose=True)

        else:
            parser.print_help()
            print("\nExample usage:")
            print("  python validate_signals.py 716")
            print("  python validate_signals.py --random 10")
            print("  python validate_signals.py --ids 716 252 125")

    finally:
        validator.close()


if __name__ == "__main__":
    main()
