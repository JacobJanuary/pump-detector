#!/usr/bin/env python3
"""
Pump Detection Daemon - Main anomaly detector
Runs every 5 minutes to check for volume spikes
"""

import time
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import sys
import os
import signal

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE, DETECTION, SCORING

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/elcrypto/pump_detector/logs/detector.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PumpDetectorDaemon:
    """Main daemon for detecting volume anomalies"""

    def __init__(self):
        self.db_config = DATABASE
        self.conn = None
        self.running = True
        self.detection_config = DETECTION
        self.scoring_weights = SCORING

        # Signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def connect(self):
        """Connect to database"""
        try:
            # Use peer authentication if no password
            if not self.db_config.get('password'):
                conn_params = {
                    'dbname': self.db_config['dbname'],
                    'cursor_factory': RealDictCursor
                }
            else:
                conn_params = {
                    'dbname': self.db_config['dbname'],
                    'user': self.db_config.get('user'),
                    'password': self.db_config.get('password'),
                    'host': self.db_config.get('host', 'localhost'),
                    'port': self.db_config.get('port', 5432),
                    'cursor_factory': RealDictCursor
                }

            self.conn = psycopg2.connect(**conn_params)
            self.conn.autocommit = False
            logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def detect_anomalies(self):
        """Detect new volume anomalies"""

        # Ensure we have a database connection
        if not self.conn:
            self.connect()

        query = """
        WITH recent_candles AS (
            SELECT
                c.trading_pair_id,
                tp.pair_symbol,
                to_timestamp(c.open_time / 1000) as candle_time,
                c.close_price,
                c.quote_asset_volume as volume,
                -- 7-day baseline (42 candles for 4h)
                AVG(c.quote_asset_volume) OVER (
                    PARTITION BY c.trading_pair_id
                    ORDER BY c.open_time
                    ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING
                ) as baseline_7d,
                -- 14-day baseline
                AVG(c.quote_asset_volume) OVER (
                    PARTITION BY c.trading_pair_id
                    ORDER BY c.open_time
                    ROWS BETWEEN 84 PRECEDING AND 1 PRECEDING
                ) as baseline_14d,
                -- 30-day baseline
                AVG(c.quote_asset_volume) OVER (
                    PARTITION BY c.trading_pair_id
                    ORDER BY c.open_time
                    ROWS BETWEEN 180 PRECEDING AND 1 PRECEDING
                ) as baseline_30d
            FROM public.candles c
            INNER JOIN public.trading_pairs tp ON c.trading_pair_id = tp.id
            WHERE tp.exchange_id = 1  -- Binance
              AND tp.is_active = true
              AND tp.contract_type_id = 1  -- Futures
              AND c.interval_id = 4  -- 4h
              AND to_timestamp(c.open_time / 1000) >= NOW() - INTERVAL '30 days'
        ),
        spike_data AS (
            SELECT
                trading_pair_id,
                pair_symbol,
                candle_time,
                close_price,
                volume,
                baseline_7d,
                baseline_14d,
                baseline_30d,
                CASE WHEN baseline_7d > 0 THEN volume / baseline_7d ELSE 0 END as spike_ratio_7d,
                CASE WHEN baseline_14d > 0 THEN volume / baseline_14d ELSE 0 END as spike_ratio_14d,
                CASE WHEN baseline_30d > 0 THEN volume / baseline_30d ELSE 0 END as spike_ratio_30d
            FROM recent_candles
            WHERE baseline_7d IS NOT NULL
              AND candle_time >= NOW() - INTERVAL '%s hours'
        )
        SELECT
            *,
            -- Classify signal strength
            CASE
                WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= %s THEN 'EXTREME'
                WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= %s THEN 'STRONG'
                WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= %s THEN 'MEDIUM'
                WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= %s THEN 'WEAK'
                ELSE NULL
            END as signal_strength,
            -- Calculate initial confidence
            CASE
                WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= %s THEN 75
                WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= %s THEN 60
                WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= %s THEN 45
                WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= %s THEN 30
                ELSE 0
            END as initial_confidence
        FROM spike_data
        WHERE spike_ratio_7d >= %s  -- Minimum threshold
          AND NOT EXISTS (
              -- Check if signal already exists
              SELECT 1 FROM pump.signals s
              WHERE s.trading_pair_id = spike_data.trading_pair_id
              AND s.signal_timestamp = spike_data.candle_time
          )
        ORDER BY spike_ratio_7d DESC
        LIMIT 50  -- Process top 50 anomalies per cycle
        """ % (
            self.detection_config['lookback_hours'],
            self.detection_config['extreme_spike_ratio'],
            self.detection_config['strong_spike_ratio'],
            self.detection_config['medium_spike_ratio'],
            self.detection_config['min_spike_ratio'],
            self.detection_config['extreme_spike_ratio'],
            self.detection_config['strong_spike_ratio'],
            self.detection_config['medium_spike_ratio'],
            self.detection_config['min_spike_ratio'],
            self.detection_config['min_spike_ratio']
        )

        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                anomalies = cur.fetchall()

                if anomalies:
                    logger.info(f"Found {len(anomalies)} new anomalies")

                    for anomaly in anomalies:
                        signal_id = self.save_signal(anomaly)
                        if signal_id:
                            self.calculate_confidence_score(signal_id)
                            logger.info(f"Signal saved: {anomaly['pair_symbol']} - "
                                      f"{anomaly['spike_ratio_7d']:.1f}x spike - "
                                      f"{anomaly['signal_strength']}")

                    self.conn.commit()
                    return len(anomalies)
                else:
                    return 0

        except Exception as e:
            logger.error(f"Error detecting anomalies: {e}")
            if self.conn:
                self.conn.rollback()
            return 0

    def save_signal(self, anomaly):
        """Save detected signal to database"""

        insert_query = """
        INSERT INTO pump.signals (
            trading_pair_id,
            pair_symbol,
            signal_timestamp,
            detected_at,
            futures_volume,
            futures_baseline_7d,
            futures_baseline_14d,
            futures_baseline_30d,
            futures_spike_ratio_7d,
            futures_spike_ratio_14d,
            futures_spike_ratio_30d,
            signal_strength,
            initial_confidence,
            status
        ) VALUES (
            %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, 'DETECTED'
        )
        RETURNING id
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(insert_query, (
                    anomaly['trading_pair_id'],
                    anomaly['pair_symbol'],
                    anomaly['candle_time'],
                    anomaly['volume'],
                    anomaly['baseline_7d'],
                    anomaly['baseline_14d'],
                    anomaly['baseline_30d'],
                    anomaly['spike_ratio_7d'],
                    anomaly['spike_ratio_14d'],
                    anomaly['spike_ratio_30d'],
                    anomaly['signal_strength'],
                    anomaly['initial_confidence']
                ))

                result = cur.fetchone()
                return result['id'] if result else None

        except Exception as e:
            logger.error(f"Error saving signal: {e}")
            return None

    def calculate_confidence_score(self, signal_id):
        """Calculate and update confidence score for a signal"""

        try:
            with self.conn.cursor() as cur:
                # Call the stored function
                cur.execute("SELECT pump.calculate_confidence_score(%s)", (signal_id,))
                confidence = cur.fetchone()

                if confidence:
                    logger.debug(f"Signal {signal_id} confidence: {confidence[0]}%")
                    return confidence[0]

        except Exception as e:
            logger.error(f"Error calculating confidence: {e}")
            return None

    def run(self):
        """Main daemon loop"""

        logger.info("Starting Pump Detector Daemon")
        logger.info(f"Detection interval: {self.detection_config['interval_minutes']} minutes")
        logger.info(f"Lookback period: {self.detection_config['lookback_hours']} hours")
        logger.info(f"Min spike ratio: {self.detection_config['min_spike_ratio']}x")

        self.connect()

        cycle_count = 0

        while self.running:
            try:
                cycle_count += 1
                logger.info(f"Starting detection cycle #{cycle_count}")

                # Detect anomalies
                new_signals = self.detect_anomalies()

                if new_signals > 0:
                    logger.info(f"Cycle #{cycle_count} complete: {new_signals} new signals detected")

                    # Check if any signals need urgent notification
                    self.check_urgent_signals()
                else:
                    logger.debug(f"Cycle #{cycle_count} complete: No new signals")

                # Sleep until next cycle
                sleep_seconds = self.detection_config['interval_minutes'] * 60
                logger.debug(f"Sleeping for {sleep_seconds} seconds until next cycle...")

                # Use interruptible sleep
                for _ in range(sleep_seconds):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Error in detection cycle: {e}")
                time.sleep(60)  # Wait 1 minute before retry

                # Reconnect if needed
                try:
                    self.conn.ping()
                except:
                    logger.info("Reconnecting to database...")
                    self.connect()

        # Cleanup
        if self.conn:
            self.conn.close()
        logger.info("Pump Detector Daemon stopped")

    def check_urgent_signals(self):
        """Check for signals that need immediate attention"""

        query = """
        SELECT
            s.id,
            s.pair_symbol,
            s.futures_spike_ratio_7d,
            s.signal_strength,
            sc.total_score
        FROM pump.signals s
        LEFT JOIN pump.signal_scores sc ON s.id = sc.signal_id
        WHERE s.status = 'DETECTED'
          AND s.detected_at >= NOW() - INTERVAL '5 minutes'
          AND (s.signal_strength = 'EXTREME' OR sc.total_score >= 80)
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                urgent_signals = cur.fetchall()

                if urgent_signals:
                    logger.warning(f"⚠️ {len(urgent_signals)} URGENT signals detected!")
                    for signal in urgent_signals:
                        logger.warning(f"  🚨 {signal['pair_symbol']}: "
                                     f"{signal['futures_spike_ratio_7d']:.1f}x spike "
                                     f"[{signal['signal_strength']}]")

                    # Here we would trigger immediate notifications
                    # self.send_urgent_notifications(urgent_signals)

        except Exception as e:
            logger.error(f"Error checking urgent signals: {e}")


if __name__ == "__main__":
    daemon = PumpDetectorDaemon()

    try:
        daemon.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Daemon terminated")