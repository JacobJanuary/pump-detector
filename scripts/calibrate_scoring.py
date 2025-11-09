#!/usr/bin/env python3
"""
Calibration System for Adaptive Scoring Weights
Analyzes historical signal performance and adjusts scoring weights
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import numpy as np
from datetime import datetime, timedelta
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DATABASE

class ScoringCalibrator:
    """Calibrates scoring weights based on historical performance"""

    def __init__(self):
        self.conn = self.connect()
        self.current_weights = self.get_current_weights()
        self.performance_data = []

    def connect(self):
        """Connect to database"""
        if not DATABASE.get('password'):
            conn_params = {
                'dbname': DATABASE['dbname'],
                'cursor_factory': RealDictCursor
            }
        else:
            conn_params = DATABASE.copy()
            conn_params['cursor_factory'] = RealDictCursor

        return psycopg2.connect(**conn_params)

    def get_current_weights(self):
        """Get current scoring weights from config"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT key, value::float as weight_value
                FROM pump.config
                WHERE key LIKE '%_weight'
            """)

            weights = {}
            for row in cur.fetchall():
                weights[row['key']] = row['weight_value']

            # Default weights if not in DB
            if not weights:
                weights = {
                    'volume_weight': 30,
                    'oi_weight': 25,
                    'spot_weight': 20,
                    'confirmation_weight': 15,
                    'timing_weight': 10
                }

            return weights

    def analyze_signal_components(self):
        """Analyze which components correlate best with successful pumps"""

        query = """
        WITH signal_analysis AS (
            SELECT
                s.id,
                s.pump_realized,
                s.max_price_increase,
                s.futures_spike_ratio_7d,
                s.futures_spike_ratio_14d,
                s.initial_confidence,
                -- Calculate component scores
                CASE
                    WHEN s.futures_spike_ratio_7d >= 5 THEN 100
                    WHEN s.futures_spike_ratio_7d >= 3 THEN 75
                    WHEN s.futures_spike_ratio_7d >= 2 THEN 50
                    WHEN s.futures_spike_ratio_7d >= 1.5 THEN 25
                    ELSE 0
                END as volume_score,

                -- OI component (based on OI change %)
                CASE
                    WHEN s.oi_change_pct >= 50 THEN 100
                    WHEN s.oi_change_pct >= 30 THEN 80
                    WHEN s.oi_change_pct >= 20 THEN 60
                    WHEN s.oi_change_pct >= 10 THEN 40
                    WHEN s.oi_change_pct >= 5 THEN 20
                    WHEN s.oi_change_pct IS NULL THEN 0
                    ELSE 0
                END as oi_score,

                -- Spot sync component (based on spot spike ratio and sync flag)
                CASE
                    WHEN s.has_spot_sync = TRUE AND s.spot_spike_ratio_7d >= 5.0 THEN 100
                    WHEN s.has_spot_sync = TRUE AND s.spot_spike_ratio_7d >= 3.0 THEN 80
                    WHEN s.has_spot_sync = TRUE AND s.spot_spike_ratio_7d >= 2.0 THEN 60
                    WHEN s.has_spot_sync = TRUE AND s.spot_spike_ratio_7d >= 1.5 THEN 40
                    WHEN s.has_spot_sync = TRUE THEN 20
                    ELSE 0
                END as spot_score,

                -- Confirmation count
                (SELECT COUNT(*) FROM pump.signal_confirmations sc
                 WHERE sc.signal_id = s.id) * 20 as confirmation_score,

                -- Timing score (freshness)
                CASE
                    WHEN EXTRACT(HOUR FROM (NOW() - s.signal_timestamp)) < 1 THEN 100
                    WHEN EXTRACT(HOUR FROM (NOW() - s.signal_timestamp)) < 4 THEN 75
                    WHEN EXTRACT(HOUR FROM (NOW() - s.signal_timestamp)) < 12 THEN 50
                    WHEN EXTRACT(HOUR FROM (NOW() - s.signal_timestamp)) < 24 THEN 25
                    ELSE 0
                END as timing_score

            FROM pump.signals s
            WHERE s.status IN ('CONFIRMED', 'FAILED')
              AND s.detected_at >= NOW() - INTERVAL '30 days'
        )
        SELECT
            pump_realized,
            AVG(volume_score) as avg_volume_score,
            AVG(oi_score) as avg_oi_score,
            AVG(spot_score) as avg_spot_score,
            AVG(confirmation_score) as avg_confirmation_score,
            AVG(timing_score) as avg_timing_score,
            AVG(max_price_increase) as avg_price_increase,
            COUNT(*) as signal_count
        FROM signal_analysis
        GROUP BY pump_realized
        """

        with self.conn.cursor() as cur:
            cur.execute(query)
            results = cur.fetchall()

            print("\n📊 COMPONENT PERFORMANCE ANALYSIS")
            print("="*60)

            successful = None
            failed = None

            for row in results:
                if row['pump_realized']:
                    successful = row
                else:
                    failed = row

            if successful and failed:
                # Calculate effectiveness ratios
                components = {
                    'volume': (successful['avg_volume_score'] - failed['avg_volume_score']) / 100,
                    'oi': (successful['avg_oi_score'] - failed['avg_oi_score']) / 100,
                    'spot': (successful['avg_spot_score'] - failed['avg_spot_score']) / 100,
                    'confirmation': (successful['avg_confirmation_score'] - failed['avg_confirmation_score']) / 100,
                    'timing': (successful['avg_timing_score'] - failed['avg_timing_score']) / 100
                }

                print(f"\nSuccessful Pumps ({successful['signal_count']} signals):")
                print(f"  Volume Score: {successful['avg_volume_score']:.1f}")
                print(f"  OI Score: {successful['avg_oi_score']:.1f}")
                print(f"  Spot Score: {successful['avg_spot_score']:.1f}")
                print(f"  Confirmation Score: {successful['avg_confirmation_score']:.1f}")
                print(f"  Timing Score: {successful['avg_timing_score']:.1f}")
                print(f"  Avg Price Increase: {successful['avg_price_increase']:.1f}%")

                print(f"\nFailed Signals ({failed['signal_count']} signals):")
                print(f"  Volume Score: {failed['avg_volume_score']:.1f}")
                print(f"  OI Score: {failed['avg_oi_score']:.1f}")
                print(f"  Spot Score: {failed['avg_spot_score']:.1f}")
                print(f"  Confirmation Score: {failed['avg_confirmation_score']:.1f}")
                print(f"  Timing Score: {failed['avg_timing_score']:.1f}")
                print(f"  Avg Price Increase: {failed['avg_price_increase']:.1f}%")

                return components

        return None

    def calculate_correlation_weights(self):
        """Calculate optimal weights based on correlation with success"""

        query = """
        WITH signal_features AS (
            SELECT
                s.pump_realized::int as success,
                s.futures_spike_ratio_7d,
                s.futures_spike_ratio_14d,
                COALESCE(s.futures_spike_ratio_30d, s.futures_spike_ratio_14d) as futures_spike_ratio_30d,
                s.initial_confidence,
                (SELECT COUNT(*) FROM pump.signal_confirmations WHERE signal_id = s.id) as confirmations,
                EXTRACT(HOUR FROM (s.detected_at - s.signal_timestamp)) as detection_lag
            FROM pump.signals s
            WHERE s.status IN ('CONFIRMED', 'FAILED')
              AND s.detected_at >= NOW() - INTERVAL '30 days'
        )
        SELECT
            CORR(success, futures_spike_ratio_7d) as corr_spike_7d,
            CORR(success, futures_spike_ratio_14d) as corr_spike_14d,
            CORR(success, futures_spike_ratio_30d) as corr_spike_30d,
            CORR(success, initial_confidence) as corr_confidence,
            CORR(success, confirmations) as corr_confirmations,
            CORR(success, detection_lag) as corr_timing
        FROM signal_features
        """

        with self.conn.cursor() as cur:
            cur.execute(query)
            correlations = cur.fetchone()

            if correlations:
                print("\n📈 CORRELATION ANALYSIS")
                print("="*60)
                print(f"7-day spike correlation: {correlations['corr_spike_7d']:.3f}")
                print(f"14-day spike correlation: {correlations['corr_spike_14d']:.3f}")
                print(f"30-day spike correlation: {correlations['corr_spike_30d']:.3f}")
                print(f"Initial confidence correlation: {correlations['corr_confidence']:.3f}")
                print(f"Confirmations correlation: {correlations['corr_confirmations']:.3f}")
                print(f"Timing correlation: {correlations['corr_timing']:.3f}")

                # Calculate weights based on correlations
                total_corr = abs(correlations['corr_spike_7d']) + \
                           abs(correlations['corr_spike_14d']) + \
                           abs(correlations['corr_confirmations']) + \
                           abs(correlations['corr_timing'])

                if total_corr > 0:
                    weights = {
                        'volume_weight': max(10, min(50, int(100 * abs(correlations['corr_spike_7d']) / total_corr))),
                        'oi_weight': 20,  # Fixed for now since we don't have OI data
                        'spot_weight': 15,  # Fixed for now
                        'confirmation_weight': max(5, min(30, int(100 * abs(correlations['corr_confirmations']) / total_corr))),
                        'timing_weight': max(5, min(20, int(100 * abs(correlations['corr_timing']) / total_corr)))
                    }

                    # Normalize to 100
                    total_weight = sum(weights.values())
                    for key in weights:
                        weights[key] = int(weights[key] * 100 / total_weight)

                    return weights

        return None

    def optimize_thresholds(self):
        """Optimize spike ratio thresholds based on performance"""

        query = """
        WITH threshold_analysis AS (
            SELECT
                futures_spike_ratio_7d as spike_ratio,
                pump_realized,
                max_price_increase
            FROM pump.signals
            WHERE status IN ('CONFIRMED', 'FAILED')
              AND detected_at >= NOW() - INTERVAL '30 days'
              AND futures_spike_ratio_7d IS NOT NULL
        ),
        threshold_performance AS (
            SELECT
                threshold,
                COUNT(*) FILTER (WHERE spike_ratio >= threshold) as total_signals,
                COUNT(*) FILTER (WHERE spike_ratio >= threshold AND pump_realized) as successful,
                AVG(max_price_increase) FILTER (WHERE spike_ratio >= threshold AND pump_realized) as avg_gain
            FROM threshold_analysis,
                 (VALUES (1.5), (2.0), (2.5), (3.0), (4.0), (5.0), (7.0), (10.0)) as t(threshold)
            GROUP BY threshold
        )
        SELECT
            threshold,
            total_signals,
            successful,
            ROUND(successful::numeric / NULLIF(total_signals, 0) * 100, 1) as accuracy,
            ROUND(avg_gain::numeric, 1) as avg_gain
        FROM threshold_performance
        ORDER BY threshold
        """

        with self.conn.cursor() as cur:
            cur.execute(query)
            results = cur.fetchall()

            print("\n🎯 OPTIMAL THRESHOLD ANALYSIS")
            print("="*60)
            print(f"{'Threshold':>10} {'Signals':>10} {'Success':>10} {'Accuracy':>10} {'Avg Gain':>10}")
            print("-"*60)

            best_threshold = None
            best_score = 0

            for row in results:
                print(f"{row['threshold']:>10.1f}x {row['total_signals']:>10} "
                      f"{row['successful']:>10} {row['accuracy']:>9.1f}% "
                      f"{row['avg_gain'] or 0:>9.1f}%")

                # Calculate score (balance between accuracy and volume)
                if row['total_signals'] >= 10:  # Minimum sample size
                    score = (row['accuracy'] or 0) * np.log1p(row['total_signals'])
                    if score > best_score:
                        best_score = score
                        best_threshold = row

            if best_threshold:
                print(f"\n✅ Recommended thresholds:")
                print(f"  WEAK: {best_threshold['threshold']:.1f}x")
                print(f"  MEDIUM: {best_threshold['threshold'] * 1.3:.1f}x")
                print(f"  STRONG: {best_threshold['threshold'] * 2:.1f}x")
                print(f"  EXTREME: {best_threshold['threshold'] * 3:.1f}x")

                return {
                    'min_spike_ratio': best_threshold['threshold'],
                    'medium_spike_ratio': best_threshold['threshold'] * 1.3,
                    'strong_spike_ratio': best_threshold['threshold'] * 2,
                    'extreme_spike_ratio': best_threshold['threshold'] * 3
                }

        return None

    def update_config(self, weights, thresholds):
        """Update configuration in database"""

        try:
            with self.conn.cursor() as cur:
                # Update weights
                for key_name, value in weights.items():
                    cur.execute("""
                        INSERT INTO pump.config (key, value, description, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (key)
                        DO UPDATE SET
                            value = EXCLUDED.value,
                            updated_at = NOW()
                    """, (key_name, str(value), f"Auto-calibrated weight for {key_name.replace('_weight', '')}"))

                # Update thresholds
                if thresholds:
                    for key_name, value in thresholds.items():
                        cur.execute("""
                            INSERT INTO pump.config (key, value, description, updated_at)
                            VALUES (%s, %s, %s, NOW())
                            ON CONFLICT (key)
                            DO UPDATE SET
                                value = EXCLUDED.value,
                                updated_at = NOW()
                        """, (key_name, str(value), f"Auto-calibrated threshold"))

                self.conn.commit()
                print("\n✅ Configuration updated successfully!")

        except Exception as e:
            print(f"❌ Error updating config: {e}")
            self.conn.rollback()

    def generate_calibration_report(self):
        """Generate detailed calibration report"""

        report = {
            'timestamp': datetime.now().isoformat(),
            'period': '30 days',
            'metrics': {}
        }

        # Overall performance
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_signals,
                    COUNT(*) FILTER (WHERE pump_realized) as successful_pumps,
                    ROUND(COUNT(*) FILTER (WHERE pump_realized)::numeric /
                          NULLIF(COUNT(*), 0) * 100, 1) as success_rate,
                    ROUND(AVG(max_price_increase), 1) as avg_gain
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL '30 days'
            """)

            overall = cur.fetchone()
            report['metrics']['overall'] = dict(overall)

            # By signal strength
            cur.execute("""
                SELECT
                    signal_strength,
                    COUNT(*) as count,
                    ROUND(COUNT(*) FILTER (WHERE pump_realized)::numeric /
                          NULLIF(COUNT(*), 0) * 100, 1) as accuracy
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL '30 days'
                  AND signal_strength IS NOT NULL
                GROUP BY signal_strength
                ORDER BY signal_strength
            """)

            report['metrics']['by_strength'] = [dict(row) for row in cur.fetchall()]

        # Save report
        report_path = f"/tmp/pump_detector/reports/calibration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        os.makedirs(os.path.dirname(report_path), exist_ok=True)

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        print(f"\n📄 Report saved to: {report_path}")

        return report

    def run_calibration(self):
        """Run full calibration process"""

        print("🔧 STARTING CALIBRATION PROCESS")
        print("="*60)

        # Analyze components
        component_diffs = self.analyze_signal_components()

        # Calculate correlation-based weights
        new_weights = self.calculate_correlation_weights()

        if new_weights:
            print("\n🎯 RECOMMENDED WEIGHTS")
            print("="*60)
            print(f"Current weights: {self.current_weights}")
            print(f"Recommended weights: {new_weights}")

            # Optimize thresholds
            new_thresholds = self.optimize_thresholds()

            # Update configuration
            response = input("\n💾 Apply new calibration? (y/n): ")
            if response.lower() == 'y':
                self.update_config(new_weights, new_thresholds)

        # Generate report
        report = self.generate_calibration_report()

        print("\n✅ CALIBRATION COMPLETE")
        print(f"Total signals analyzed: {report['metrics']['overall']['total_signals']}")
        print(f"Current success rate: {report['metrics']['overall']['success_rate']}%")

        self.conn.close()

def main():
    """Main function"""
    calibrator = ScoringCalibrator()
    calibrator.run_calibration()

if __name__ == "__main__":
    main()