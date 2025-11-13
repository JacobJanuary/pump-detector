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
import argparse

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

    def __init__(self, historical_mode=False, once_mode=False):
        self.db_config = DATABASE
        self.conn = None
        self.running = True
        self.detection_config = DETECTION
        self.scoring_weights = SCORING
        self.historical_mode = historical_mode
        self.once_mode = once_mode

        # Set lookback period based on mode
        # Historical mode: 30 days (720 hours) for initial load
        # Monitoring mode: 4 hours for incremental updates
        self.lookback_hours = 720 if historical_mode else self.detection_config.get('lookback_hours', 4)

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

    def detect_futures_anomalies(self):
        """Detect FUTURES volume anomalies"""

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
              -- FILTERS: Exclude meme coins and low market cap
              AND NOT public.is_meme_coin(tp.id)  -- No meme coins
              AND EXISTS (
                  SELECT 1 FROM public.tokens t
                  JOIN public.cmc_crypto cmc ON t.cmc_token_id = cmc.cmc_token_id
                  WHERE t.id = tp.token_id AND cmc.market_cap >= 100000000  -- >= $100M market cap
              )
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
              -- Check if signal already exists (same pair, timestamp, signal_type)
              SELECT 1 FROM pump.signals s
              WHERE s.trading_pair_id = spike_data.trading_pair_id
              AND s.signal_timestamp = spike_data.candle_time
              AND s.signal_type = 'FUTURES'
          )
        ORDER BY spike_ratio_7d DESC
        """

        # No LIMIT - process all anomalies
        query = query % (
            self.lookback_hours,
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

                futures_count = 0
                if anomalies:
                    logger.info(f"Found {len(anomalies)} new FUTURES anomalies")

                    for anomaly in anomalies:
                        signal_id = self.save_signal(anomaly, signal_type='FUTURES')
                        if signal_id:
                            self.calculate_confidence_score(signal_id)
                            logger.info(f"FUTURES signal saved: {anomaly['pair_symbol']} - "
                                      f"{anomaly['spike_ratio_7d']:.1f}x spike - "
                                      f"{anomaly['signal_strength']}")
                            futures_count += 1

                return futures_count

        except Exception as e:
            logger.error(f"Error detecting FUTURES anomalies: {e}")
            return 0

    def detect_spot_anomalies(self):
        """Detect SPOT volume anomalies"""

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
              AND tp.contract_type_id = 2  -- Spot
              AND c.interval_id = 4  -- 4h
              AND to_timestamp(c.open_time / 1000) >= NOW() - INTERVAL '30 days'
              -- FILTERS: Exclude meme coins and low market cap
              AND NOT public.is_meme_coin(tp.id)  -- No meme coins
              AND EXISTS (
                  SELECT 1 FROM public.tokens t
                  JOIN public.cmc_crypto cmc ON t.cmc_token_id = cmc.cmc_token_id
                  WHERE t.id = tp.token_id AND cmc.market_cap >= 100000000  -- >= $100M market cap
              )
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
              -- Check if signal already exists (same pair, timestamp, signal_type)
              SELECT 1 FROM pump.signals s
              WHERE s.trading_pair_id = spike_data.trading_pair_id
              AND s.signal_timestamp = spike_data.candle_time
              AND s.signal_type = 'SPOT'
          )
        ORDER BY spike_ratio_7d DESC
        """

        # No LIMIT - process all anomalies
        query = query % (
            self.lookback_hours,
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

                spot_count = 0
                if anomalies:
                    logger.info(f"Found {len(anomalies)} new SPOT anomalies")

                    for anomaly in anomalies:
                        signal_id = self.save_signal(anomaly, signal_type='SPOT')
                        if signal_id:
                            self.calculate_confidence_score(signal_id)
                            logger.info(f"SPOT signal saved: {anomaly['pair_symbol']} - "
                                      f"{anomaly['spike_ratio_7d']:.1f}x spike - "
                                      f"{anomaly['signal_strength']}")
                            spot_count += 1

                return spot_count

        except Exception as e:
            logger.error(f"Error detecting SPOT anomalies: {e}")
            return 0

    def detect_anomalies(self):
        """Detect both FUTURES and SPOT anomalies"""

        # Ensure we have a database connection
        if not self.conn:
            self.connect()

        try:
            # Detect FUTURES anomalies
            futures_count = self.detect_futures_anomalies()

            # Detect SPOT anomalies
            spot_count = self.detect_spot_anomalies()

            total_count = futures_count + spot_count

            if total_count > 0:
                logger.info(f"Total new signals: {total_count} (FUTURES: {futures_count}, SPOT: {spot_count})")
                self.conn.commit()

            return total_count

        except Exception as e:
            logger.error(f"Error in detect_anomalies: {e}")
            if self.conn:
                self.conn.rollback()
            return 0

    def save_signal(self, anomaly, signal_type='FUTURES'):
        """Save detected signal to database"""

        insert_query = """
        INSERT INTO pump.signals (
            trading_pair_id,
            pair_symbol,
            signal_timestamp,
            detected_at,
            signal_type,
            volume,
            baseline_7d,
            baseline_14d,
            baseline_30d,
            spike_ratio_7d,
            spike_ratio_14d,
            spike_ratio_30d,
            signal_strength,
            initial_confidence,
            price_at_signal,
            status
        ) VALUES (
            %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'DETECTED'
        )
        RETURNING id
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(insert_query, (
                    anomaly['trading_pair_id'],
                    anomaly['pair_symbol'],
                    anomaly['candle_time'],
                    signal_type,
                    anomaly['volume'],
                    anomaly['baseline_7d'],
                    anomaly['baseline_14d'],
                    anomaly['baseline_30d'],
                    anomaly['spike_ratio_7d'],
                    anomaly['spike_ratio_14d'],
                    anomaly['spike_ratio_30d'],
                    anomaly['signal_strength'],
                    anomaly['initial_confidence'],
                    anomaly['close_price']
                ))

                result = cur.fetchone()
                return result['id'] if result else None

        except Exception as e:
            logger.error(f"Error saving {signal_type} signal: {e}")
            return None

    def calculate_confidence_score(self, signal_id):
        """Calculate and update confidence score for a signal"""

        try:
            with self.conn.cursor() as cur:
                # Call the stored function
                cur.execute("SELECT pump.calculate_confidence_score(%s) as score", (signal_id,))
                result = cur.fetchone()

                if result:
                    confidence_score = result['score']
                    logger.debug(f"Signal {signal_id} confidence: {confidence_score}%")
                    return confidence_score

        except Exception as e:
            logger.error(f"Error calculating confidence: {e}")
            return None

    def run(self):
        """Main daemon loop"""

        if self.historical_mode:
            mode_str = "HISTORICAL MODE"
        elif self.once_mode:
            mode_str = "ONCE MODE (cron)"
        else:
            mode_str = "MONITORING MODE"

        logger.info(f"Starting Pump Detector Daemon [{mode_str}]")
        logger.info(f"Lookback period: {self.lookback_hours} hours ({self.lookback_hours/24:.1f} days)")
        logger.info(f"Min spike ratio: {self.detection_config['min_spike_ratio']}x")

        if not self.historical_mode and not self.once_mode:
            logger.info(f"Detection interval: {self.detection_config['interval_minutes']} minutes")

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

                    # Check if any signals need urgent notification (only in monitoring mode)
                    if not self.historical_mode:
                        self.check_urgent_signals()
                else:
                    logger.debug(f"Cycle #{cycle_count} complete: No new signals")

                # In historical or once mode, run once and exit
                if self.historical_mode:
                    logger.info(f"Historical load complete. Total signals loaded: {new_signals}")
                    break

                if self.once_mode:
                    logger.info(f"Detection cycle complete. Total new signals: {new_signals}")
                    break

                # Sleep until next cycle (monitoring mode only)
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
                    # Проверяем соединение выполнением простого запроса
                    with self.conn.cursor() as cur:
                        cur.execute("SELECT 1")
                except (psycopg2.OperationalError, psycopg2.InterfaceError):
                    logger.info("Database connection lost, reconnecting...")
                    try:
                        self.conn.close()
                    except:
                        pass
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
            s.signal_type,
            s.spike_ratio_7d,
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
                        logger.warning(f"  🚨 {signal['pair_symbol']} [{signal['signal_type']}]: "
                                     f"{signal['spike_ratio_7d']:.1f}x spike "
                                     f"[{signal['signal_strength']}]")

                    # Here we would trigger immediate notifications
                    # self.send_urgent_notifications(urgent_signals)

        except Exception as e:
            logger.error(f"Error checking urgent signals: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Pump Detector Daemon')
    parser.add_argument('--historical', action='store_true',
                       help='Run in historical mode (load 30 days of signals, then exit)')
    parser.add_argument('--once', action='store_true',
                       help='Run once and exit (for cron scheduling)')
    args = parser.parse_args()

    daemon = PumpDetectorDaemon(historical_mode=args.historical, once_mode=args.once)

    try:
        daemon.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Daemon terminated")