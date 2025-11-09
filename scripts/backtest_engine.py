#!/usr/bin/env python3
"""
Backtest Engine for Pump Detection V2.0
Tests the detection engine on 136 known historical pump events

Features:
- Time-travel analysis (run engine at different times before pump)
- Tests at multiple time windows: 72h, 60h, 48h, 36h, 24h before pump
- Calculates TP/FP/FN/TN metrics
- Stores results in pump.backtest_results
- Generates comprehensive metrics report
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, timezone
import sys
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATABASE
from engine.pump_detection_engine import PumpDetectionEngine
from engine.database_helper import PumpDatabaseHelper

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Backtesting framework for pump detection engine

    Tests engine performance on known historical pump events
    """

    def __init__(self):
        self.db_config = DATABASE
        self.conn = None
        self.db_helper = None
        self.engine = None

        # Time windows to test (hours before pump)
        self.test_windows = [72, 60, 48, 36, 24]

    def connect(self):
        """Initialize database connections"""
        try:
            self.conn = psycopg2.connect(**self.db_config, cursor_factory=RealDictCursor)
            self.db_helper = PumpDatabaseHelper(self.db_config)
            self.db_helper.connect()
            self.engine = PumpDetectionEngine(self.db_helper)

            logger.info("Backtest Engine initialized")
            logger.info(f"Engine config: min_signals={self.engine.min_signal_count}, "
                       f"HIGH≥{self.engine.high_conf_threshold}, "
                       f"MEDIUM≥{self.engine.medium_conf_threshold}")
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            raise

    def get_known_pumps(self) -> List[Dict]:
        """Get all known pump events for backtesting"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        id,
                        trading_pair_id,
                        pair_symbol,
                        pump_start,
                        start_price,
                        high_price,
                        price_after_24h,
                        max_gain_24h,
                        pump_duration_hours
                    FROM pump.known_pump_events
                    ORDER BY pump_start
                """)
                pumps = cur.fetchall()

            logger.info(f"Loaded {len(pumps)} known pump events for backtesting")
            return pumps

        except Exception as e:
            logger.error(f"Error loading known pumps: {e}")
            return []

    def run_time_travel_analysis(self, pump: Dict, hours_before: int) -> Optional[Dict]:
        """
        Run detection engine at specific time before pump (time travel)

        Args:
            pump: Known pump event dict
            hours_before: How many hours before pump start to analyze

        Returns:
            Detection result dict or None
        """
        try:
            symbol = pump['pair_symbol']
            pump_start = pump['pump_start']

            # Calculate analysis time (time-travel)
            analysis_time = pump_start - timedelta(hours=hours_before)

            # Run engine at that point in time
            result = self.engine.analyze_symbol(symbol, current_time=analysis_time)

            return result

        except Exception as e:
            logger.error(f"Time-travel analysis failed for {pump['pair_symbol']} "
                        f"at -{hours_before}h: {e}")
            return None

    def classify_result(self, detected: bool, is_known_pump: bool) -> str:
        """
        Classify detection result for metrics

        Args:
            detected: Was pump detected by engine?
            is_known_pump: Is this a known pump event?

        Returns:
            Classification: TP, FP, FN, or TN
        """
        # For backtesting, all events are known pumps
        # So we only have TP (detected) or FN (not detected)
        if is_known_pump:
            if detected:
                return 'TP'  # True Positive: detected a real pump
            else:
                return 'FN'  # False Negative: missed a real pump
        else:
            # This shouldn't happen in our backtest (all events are real pumps)
            if detected:
                return 'FP'  # False Positive: detected non-pump
            else:
                return 'TN'  # True Negative: correctly didn't detect non-pump

    def save_backtest_result(self, pump: Dict, hours_before: int,
                            detection_result: Optional[Dict]):
        """
        Save backtest result to database

        Args:
            pump: Known pump event
            hours_before: Hours before pump when analysis was done
            detection_result: Detection engine result (or None if not detected)
        """
        try:
            known_pump_id = pump['id']
            pair_symbol = pump['pair_symbol']
            pump_start = pump['pump_start']
            analysis_time = pump_start - timedelta(hours=hours_before)

            # Determine detection status
            was_detected = detection_result is not None

            # Extract detection details
            if was_detected:
                confidence = detection_result['confidence']
                score = detection_result['score']
                pattern_type = detection_result['pattern_type']
                is_actionable = detection_result['is_actionable']
                total_signals = detection_result['total_signals']
                extreme_signals = detection_result['extreme_signals']
                critical_window_signals = detection_result['critical_window_signals']
                eta_hours = detection_result['eta_hours']
            else:
                confidence = None
                score = None
                pattern_type = None
                is_actionable = False
                total_signals = 0
                extreme_signals = 0
                critical_window_signals = 0
                eta_hours = None

            # Classify for metrics
            classification = self.classify_result(was_detected, True)

            # Get current engine config
            config_snapshot = {
                'min_signal_count': self.engine.min_signal_count,
                'high_conf_threshold': self.engine.high_conf_threshold,
                'medium_conf_threshold': self.engine.medium_conf_threshold,
                'critical_window_min_signals': self.engine.critical_window_min_signals
            }

            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO pump.backtest_results (
                        known_pump_id,
                        pair_symbol,
                        analysis_time,
                        hours_before_pump,
                        was_detected,
                        confidence,
                        score,
                        pattern_type,
                        is_actionable,
                        total_signals,
                        extreme_signals,
                        critical_window_signals,
                        eta_hours,
                        classification,
                        config_snapshot
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT DO NOTHING
                """, (
                    known_pump_id,
                    pair_symbol,
                    analysis_time,
                    hours_before,
                    was_detected,
                    confidence,
                    score,
                    pattern_type,
                    is_actionable,
                    total_signals,
                    extreme_signals,
                    critical_window_signals,
                    eta_hours,
                    classification,
                    json.dumps(config_snapshot)
                ))

            self.conn.commit()

        except Exception as e:
            logger.error(f"Error saving backtest result: {e}")
            self.conn.rollback()

    def run_backtest(self, pump: Dict):
        """
        Run complete backtest for one pump event

        Tests detection at multiple time windows before pump
        """
        symbol = pump['pair_symbol']
        pump_start = pump['pump_start']

        logger.info(f"Testing {symbol} (pump at {pump_start})")

        results = {}

        for hours_before in self.test_windows:
            try:
                # Run time-travel analysis
                result = self.run_time_travel_analysis(pump, hours_before)

                # Save result
                self.save_backtest_result(pump, hours_before, result)

                # Track for summary
                results[hours_before] = result

                if result:
                    logger.info(f"  -{hours_before}h: ✓ DETECTED - "
                              f"{result['confidence']} confidence, "
                              f"score={result['score']:.1f}, "
                              f"actionable={result['is_actionable']}")
                else:
                    logger.info(f"  -{hours_before}h: ✗ NOT DETECTED")

            except Exception as e:
                logger.error(f"  -{hours_before}h: ERROR - {e}")
                continue

        return results

    def calculate_metrics(self) -> Dict:
        """
        Calculate performance metrics from backtest results

        Returns:
            Dict with Precision, Recall, F1, Accuracy metrics
        """
        try:
            with self.conn.cursor() as cur:
                # Overall metrics
                cur.execute("""
                    SELECT
                        classification,
                        COUNT(*) as count
                    FROM pump.backtest_results
                    GROUP BY classification
                """)

                classification_counts = {row['classification']: row['count']
                                       for row in cur.fetchall()}

                tp = classification_counts.get('TP', 0)
                fp = classification_counts.get('FP', 0)
                fn = classification_counts.get('FN', 0)
                tn = classification_counts.get('TN', 0)

                # Calculate metrics
                precision = tp / (tp + fp) if (tp + fp) > 0 else 0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0
                f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
                accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0

                # Metrics by time window
                cur.execute("""
                    SELECT
                        hours_before_pump,
                        COUNT(*) as total,
                        SUM(CASE WHEN was_detected THEN 1 ELSE 0 END) as detected,
                        SUM(CASE WHEN is_actionable THEN 1 ELSE 0 END) as actionable
                    FROM pump.backtest_results
                    GROUP BY hours_before_pump
                    ORDER BY hours_before_pump DESC
                """)

                window_metrics = []
                for row in cur.fetchall():
                    window_metrics.append({
                        'hours_before': row['hours_before_pump'],
                        'total': row['total'],
                        'detected': row['detected'],
                        'actionable': row['actionable'],
                        'detection_rate': row['detected'] / row['total'] if row['total'] > 0 else 0
                    })

                # Metrics by confidence level
                cur.execute("""
                    SELECT
                        confidence,
                        COUNT(*) as count,
                        AVG(score) as avg_score,
                        SUM(CASE WHEN is_actionable THEN 1 ELSE 0 END) as actionable_count
                    FROM pump.backtest_results
                    WHERE was_detected = true
                    GROUP BY confidence
                    ORDER BY
                        CASE confidence
                            WHEN 'HIGH' THEN 1
                            WHEN 'MEDIUM' THEN 2
                            WHEN 'LOW' THEN 3
                        END
                """)

                confidence_metrics = []
                for row in cur.fetchall():
                    confidence_metrics.append({
                        'confidence': row['confidence'],
                        'count': row['count'],
                        'avg_score': float(row['avg_score']) if row['avg_score'] else 0,
                        'actionable_count': row['actionable_count']
                    })

                # Metrics by pattern type
                cur.execute("""
                    SELECT
                        pattern_type,
                        COUNT(*) as count,
                        AVG(score) as avg_score
                    FROM pump.backtest_results
                    WHERE was_detected = true
                    GROUP BY pattern_type
                    ORDER BY count DESC
                """)

                pattern_metrics = []
                for row in cur.fetchall():
                    pattern_metrics.append({
                        'pattern_type': row['pattern_type'],
                        'count': row['count'],
                        'avg_score': float(row['avg_score']) if row['avg_score'] else 0
                    })

                return {
                    'overall': {
                        'tp': tp,
                        'fp': fp,
                        'fn': fn,
                        'tn': tn,
                        'precision': precision,
                        'recall': recall,
                        'f1_score': f1,
                        'accuracy': accuracy
                    },
                    'by_time_window': window_metrics,
                    'by_confidence': confidence_metrics,
                    'by_pattern': pattern_metrics
                }

        except Exception as e:
            logger.error(f"Error calculating metrics: {e}")
            return {}

    def print_metrics_report(self, metrics: Dict):
        """Print formatted metrics report"""
        print("\n" + "="*80)
        print("BACKTEST RESULTS - PERFORMANCE METRICS")
        print("="*80)
        print()

        overall = metrics['overall']
        print("OVERALL PERFORMANCE:")
        print(f"  True Positives (TP):  {overall['tp']}")
        print(f"  False Positives (FP): {overall['fp']}")
        print(f"  False Negatives (FN): {overall['fn']}")
        print(f"  True Negatives (TN):  {overall['tn']}")
        print()
        print(f"  Precision: {overall['precision']:.2%}")
        print(f"  Recall:    {overall['recall']:.2%}")
        print(f"  F1 Score:  {overall['f1_score']:.2%}")
        print(f"  Accuracy:  {overall['accuracy']:.2%}")
        print()

        print("DETECTION RATE BY TIME WINDOW:")
        for window in metrics['by_time_window']:
            print(f"  {window['hours_before']}h before pump: "
                  f"{window['detected']}/{window['total']} detected "
                  f"({window['detection_rate']:.1%}), "
                  f"{window['actionable']} actionable")
        print()

        if metrics['by_confidence']:
            print("DETECTION BY CONFIDENCE LEVEL:")
            for conf in metrics['by_confidence']:
                print(f"  {conf['confidence']:6s}: {conf['count']:3d} detections, "
                      f"avg score={conf['avg_score']:5.1f}, "
                      f"{conf['actionable_count']} actionable")
            print()

        if metrics['by_pattern']:
            print("DETECTION BY PATTERN TYPE:")
            for pattern in metrics['by_pattern']:
                print(f"  {pattern['pattern_type']:20s}: {pattern['count']:3d} detections, "
                      f"avg score={pattern['avg_score']:5.1f}")
            print()

        print("="*80)

    def run(self):
        """Main backtest execution"""
        logger.info("="*80)
        logger.info("PUMP DETECTION ENGINE V2.0 - BACKTESTING")
        logger.info("="*80)
        logger.info("")

        self.connect()

        # Get known pump events
        pumps = self.get_known_pumps()

        if not pumps:
            logger.error("No known pump events found!")
            return

        logger.info(f"Testing engine on {len(pumps)} known pump events")
        logger.info(f"Time windows: {self.test_windows} hours before pump")
        logger.info("")

        # Clear previous backtest results (optional)
        logger.info("Clearing previous backtest results...")
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM pump.backtest_results")
            self.conn.commit()
        logger.info("✓ Cleared")
        logger.info("")

        # Run backtest for each pump
        logger.info("Running backtest...")
        logger.info("")

        for idx, pump in enumerate(pumps, 1):
            logger.info(f"[{idx}/{len(pumps)}] {pump['pair_symbol']}")
            self.run_backtest(pump)
            logger.info("")

        # Calculate and display metrics
        logger.info("="*80)
        logger.info("CALCULATING METRICS...")
        logger.info("="*80)
        logger.info("")

        metrics = self.calculate_metrics()
        self.print_metrics_report(metrics)

        # Save metrics to JSON
        output_file = Path('/tmp/pump_analysis/backtest_metrics.json')
        output_file.parent.mkdir(exist_ok=True)

        with open(output_file, 'w') as f:
            json.dump(metrics, f, indent=2, default=str)

        logger.info(f"✓ Metrics saved to: {output_file}")
        logger.info("")
        logger.info("="*80)
        logger.info("✅ BACKTEST COMPLETE")
        logger.info("="*80)

    def close(self):
        """Clean up connections"""
        if self.conn:
            self.conn.close()
        if self.db_helper:
            self.db_helper.close()


def main():
    engine = BacktestEngine()

    try:
        engine.run()
    except KeyboardInterrupt:
        logger.info("\n\nBacktest interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        engine.close()

if __name__ == "__main__":
    main()
