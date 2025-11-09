#!/usr/bin/env python3
"""
Pump Detection Daemon V2.0 - Volume anomaly detector
Runs every 5 minutes to check for volume spikes and save to pump.raw_signals

Changes from V1:
- Writes to pump.raw_signals instead of pump.signals
- Removed confidence scoring (now done by PumpDetectionEngine)
- Simplified to focus on signal detection only
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

from config.settings import DATABASE, DETECTION

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/elcrypto/pump_detector/logs/detector_v2.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PumpDetectorDaemon:
    """V2.0 daemon for detecting volume anomalies"""

    def __init__(self, historical_mode=False, once_mode=False):
        self.db_config = DATABASE
        self.conn = None
        self.running = True
        self.detection_config = DETECTION
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
            logger.info("Database connection established (V2.0)")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def classify_signal_strength(self, spike_ratio_7d, spike_ratio_14d):
        """
        Classify signal strength based on spike ratios

        Based on research findings:
        - EXTREME: ≥5.0x (57.6% presence in actionable pumps)
        - VERY_STRONG: ≥3.0x
        - STRONG: ≥2.0x
        - MEDIUM: ≥1.5x
        """
        max_spike = max(spike_ratio_7d or 0, spike_ratio_14d or 0)

        if max_spike >= self.detection_config.get('extreme_spike_ratio', 5.0):
            return 'EXTREME'
        elif max_spike >= self.detection_config.get('very_strong_spike_ratio', 3.0):
            return 'VERY_STRONG'
        elif max_spike >= self.detection_config.get('strong_spike_ratio', 2.0):
            return 'STRONG'
        elif max_spike >= self.detection_config.get('medium_spike_ratio', 1.5):
            return 'MEDIUM'
        else:
            return 'WEAK'

    def detect_futures_anomalies(self, time_start=None, time_end=None):
        """Detect FUTURES volume anomalies

        Args:
            time_start: Start of time window (datetime) - for batch processing
            time_end: End of time window (datetime) - for batch processing
        """

        # Build time window conditions
        if time_start and time_end:
            # Batch mode: specific time window
            # We need to load candles from 30 days BEFORE batch start (for baselines)
            # up to batch end (for signals in this batch)
            from datetime import timedelta
            baseline_start = time_start - timedelta(days=30)

            time_window_condition = """
              AND to_timestamp(c.open_time / 1000) >= %s
              AND to_timestamp(c.open_time / 1000) < %s
            """
            signal_time_filter = "AND candle_time >= %s AND candle_time < %s"
            query_params = [baseline_start, time_end, time_start, time_end,
                           self.detection_config.get('min_spike_ratio', 1.5)]
        else:
            # Normal mode: relative lookback
            time_window_condition = ""
            signal_time_filter = "AND candle_time >= NOW() - INTERVAL '%s hours'"
            query_params = [self.detection_config.get('min_spike_ratio', 1.5)]

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
              AND NOT public.is_meme_coin(tp.id)
              AND EXISTS (
                  SELECT 1 FROM public.tokens t
                  JOIN public.cmc_crypto cmc ON t.cmc_token_id = cmc.cmc_token_id
                  WHERE t.id = tp.token_id AND cmc.market_cap >= 100000000  -- >= $100M
              )
              {time_window}
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
              {signal_filter}
        )
        SELECT *
        FROM spike_data
        WHERE spike_ratio_7d >= %s  -- Minimum threshold
          AND NOT EXISTS (
              -- Check if signal already exists
              SELECT 1 FROM pump.raw_signals s
              WHERE s.trading_pair_id = spike_data.trading_pair_id
              AND s.signal_timestamp = spike_data.candle_time
              AND s.signal_type = 'FUTURES'
          )
        ORDER BY spike_ratio_7d DESC
        """

        # Format query based on mode
        if time_start and time_end:
            query = query.format(
                time_window=time_window_condition,
                signal_filter=signal_time_filter
            )
        else:
            query = query.format(
                time_window=time_window_condition,
                signal_filter=signal_time_filter % self.lookback_hours
            )

        try:
            with self.conn.cursor() as cur:
                if time_start and time_end:
                    cur.execute(query, query_params)
                else:
                    cur.execute(query, query_params)

                anomalies = cur.fetchall()

                futures_count = 0
                if anomalies:
                    logger.info(f"Found {len(anomalies)} new FUTURES anomalies")

                    for anomaly in anomalies:
                        # Classify signal strength
                        signal_strength = self.classify_signal_strength(
                            anomaly['spike_ratio_7d'],
                            anomaly['spike_ratio_14d']
                        )

                        signal_id = self.save_raw_signal(anomaly, signal_type='FUTURES',
                                                        signal_strength=signal_strength)
                        if signal_id:
                            logger.info(f"FUTURES signal saved: {anomaly['pair_symbol']} - "
                                      f"{anomaly['spike_ratio_7d']:.1f}x spike - {signal_strength}")
                            futures_count += 1

                return futures_count

        except Exception as e:
            logger.error(f"Error detecting FUTURES anomalies: {e}")
            return 0

    def detect_spot_anomalies(self, time_start=None, time_end=None):
        """Detect SPOT volume anomalies

        Args:
            time_start: Start of time window (datetime) - for batch processing
            time_end: End of time window (datetime) - for batch processing
        """

        # Build time window conditions
        if time_start and time_end:
            # Batch mode: specific time window
            # We need to load candles from 30 days BEFORE batch start (for baselines)
            # up to batch end (for signals in this batch)
            from datetime import timedelta
            baseline_start = time_start - timedelta(days=30)

            time_window_condition = """
              AND to_timestamp(c.open_time / 1000) >= %s
              AND to_timestamp(c.open_time / 1000) < %s
            """
            signal_time_filter = "AND candle_time >= %s AND candle_time < %s"
            query_params = [baseline_start, time_end, time_start, time_end,
                           self.detection_config.get('min_spike_ratio', 1.5)]
        else:
            # Normal mode: relative lookback
            time_window_condition = ""
            signal_time_filter = "AND candle_time >= NOW() - INTERVAL '%s hours'"
            query_params = [self.detection_config.get('min_spike_ratio', 1.5)]

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
              AND NOT public.is_meme_coin(tp.id)
              AND EXISTS (
                  SELECT 1 FROM public.tokens t
                  JOIN public.cmc_crypto cmc ON t.cmc_token_id = cmc.cmc_token_id
                  WHERE t.id = tp.token_id AND cmc.market_cap >= 100000000  -- >= $100M
              )
              {time_window}
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
              {signal_filter}
        )
        SELECT *
        FROM spike_data
        WHERE spike_ratio_7d >= %s  -- Minimum threshold
          AND NOT EXISTS (
              -- Check if signal already exists
              SELECT 1 FROM pump.raw_signals s
              WHERE s.trading_pair_id = spike_data.trading_pair_id
              AND s.signal_timestamp = spike_data.candle_time
              AND s.signal_type = 'SPOT'
          )
        ORDER BY spike_ratio_7d DESC
        """

        # Format query based on mode
        if time_start and time_end:
            query = query.format(
                time_window=time_window_condition,
                signal_filter=signal_time_filter
            )
        else:
            query = query.format(
                time_window=time_window_condition,
                signal_filter=signal_time_filter % self.lookback_hours
            )

        try:
            with self.conn.cursor() as cur:
                if time_start and time_end:
                    cur.execute(query, query_params)
                else:
                    cur.execute(query, query_params)

                anomalies = cur.fetchall()

                spot_count = 0
                if anomalies:
                    logger.info(f"Found {len(anomalies)} new SPOT anomalies")

                    for anomaly in anomalies:
                        # Classify signal strength
                        signal_strength = self.classify_signal_strength(
                            anomaly['spike_ratio_7d'],
                            anomaly['spike_ratio_14d']
                        )

                        signal_id = self.save_raw_signal(anomaly, signal_type='SPOT',
                                                        signal_strength=signal_strength)
                        if signal_id:
                            logger.info(f"SPOT signal saved: {anomaly['pair_symbol']} - "
                                      f"{anomaly['spike_ratio_7d']:.1f}x spike - {signal_strength}")
                            spot_count += 1

                return spot_count

        except Exception as e:
            logger.error(f"Error detecting SPOT anomalies: {e}")
            return 0

    def detect_anomalies(self, time_start=None, time_end=None):
        """Detect both FUTURES and SPOT anomalies

        Args:
            time_start: Start of time window (datetime) - for batch processing
            time_end: End of time window (datetime) - for batch processing
        """

        # Ensure we have a database connection
        if not self.conn:
            self.connect()

        try:
            # Detect FUTURES anomalies
            futures_count = self.detect_futures_anomalies(time_start, time_end)

            # Detect SPOT anomalies
            spot_count = self.detect_spot_anomalies(time_start, time_end)

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

    def run_batched_historical_load(self):
        """
        Run historical data load in batches to prevent PostgreSQL from hanging

        Divides 30 days into smaller batches (48 hours each)
        For each batch:
        - Loads candles from that time period
        - Detects anomalies
        - Commits to database
        - Reports progress

        This prevents massive queries that hang PostgreSQL
        """
        from datetime import datetime, timedelta

        # Configuration
        batch_size_hours = 48  # Process 48 hours at a time (2 days)
        total_hours = self.lookback_hours  # 720 hours = 30 days
        num_batches = total_hours // batch_size_hours

        logger.info("="*70)
        logger.info("BATCHED HISTORICAL LOAD")
        logger.info(f"Total period: {total_hours} hours ({total_hours/24:.0f} days)")
        logger.info(f"Batch size: {batch_size_hours} hours ({batch_size_hours/24:.0f} days)")
        logger.info(f"Number of batches: {num_batches}")
        logger.info("="*70)

        # Start from oldest time and move forward
        current_time = datetime.now()
        start_time = current_time - timedelta(hours=total_hours)

        total_signals = 0

        for batch_num in range(num_batches):
            batch_start = start_time + timedelta(hours=batch_num * batch_size_hours)
            batch_end = batch_start + timedelta(hours=batch_size_hours)

            # Make sure we don't go beyond current time
            if batch_end > current_time:
                batch_end = current_time

            logger.info("")
            logger.info(f"Batch {batch_num + 1}/{num_batches}")
            logger.info(f"  Time window: {batch_start.strftime('%Y-%m-%d %H:%M')} to {batch_end.strftime('%Y-%m-%d %H:%M')}")
            logger.info(f"  Processing...")

            try:
                # Process this batch
                batch_signals = self.detect_anomalies(time_start=batch_start, time_end=batch_end)
                total_signals += batch_signals

                logger.info(f"  ✓ Batch {batch_num + 1} complete: {batch_signals} signals found")
                logger.info(f"  Total so far: {total_signals} signals")

                # Small delay between batches to reduce DB load
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"  ✗ Error in batch {batch_num + 1}: {e}")
                # Continue with next batch even if this one fails
                continue

        logger.info("="*70)
        logger.info(f"BATCHED HISTORICAL LOAD COMPLETE")
        logger.info(f"Total signals loaded: {total_signals}")
        logger.info("="*70)

        return total_signals

    def save_raw_signal(self, anomaly, signal_type='FUTURES', signal_strength='MEDIUM'):
        """
        Save detected signal to pump.raw_signals

        V2.0 Changes:
        - Writes to pump.raw_signals instead of pump.signals
        - No confidence calculation (done separately by PumpDetectionEngine)
        - Simplified schema
        """

        insert_query = """
        INSERT INTO pump.raw_signals (
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
            price_at_signal,
            detector_version
        ) VALUES (
            %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '2.0'
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
                    signal_strength,
                    anomaly['close_price']
                ))

                result = cur.fetchone()
                return result['id'] if result else None

        except Exception as e:
            logger.error(f"Error saving {signal_type} signal: {e}")
            return None

    def run(self):
        """Main daemon loop"""

        if self.historical_mode:
            mode_str = "HISTORICAL MODE (V2.0) - BATCHED"
        elif self.once_mode:
            mode_str = "ONCE MODE (cron) (V2.0)"
        else:
            mode_str = "MONITORING MODE (V2.0)"

        logger.info(f"Starting Pump Detector Daemon [{mode_str}]")
        logger.info(f"Lookback period: {self.lookback_hours} hours ({self.lookback_hours/24:.1f} days)")
        logger.info(f"Min spike ratio: {self.detection_config.get('min_spike_ratio', 1.5)}x")
        logger.info(f"Writing to: pump.raw_signals")

        if not self.historical_mode and not self.once_mode:
            logger.info(f"Detection interval: {self.detection_config.get('interval_minutes', 5)} minutes")

        self.connect()

        cycle_count = 0

        # Historical mode uses batched loading
        if self.historical_mode:
            try:
                logger.info("Using BATCHED processing to prevent database overload")
                new_signals = self.run_batched_historical_load()
                logger.info(f"Historical load complete. Total signals loaded: {new_signals}")
                return
            except Exception as e:
                logger.error(f"Error in batched historical load: {e}")
                return
            finally:
                if self.conn:
                    self.conn.close()
                logger.info("Pump Detector Daemon V2.0 stopped")

        # Normal monitoring and once modes
        while self.running:
            try:
                cycle_count += 1
                logger.info(f"Starting detection cycle #{cycle_count}")

                # Detect anomalies
                new_signals = self.detect_anomalies()

                if new_signals > 0:
                    logger.info(f"Cycle #{cycle_count} complete: {new_signals} new signals detected")
                else:
                    logger.debug(f"Cycle #{cycle_count} complete: No new signals")

                # In once mode, run once and exit
                if self.once_mode:
                    logger.info(f"Detection cycle complete. Total new signals: {new_signals}")
                    break

                # Sleep until next cycle (monitoring mode only)
                sleep_seconds = self.detection_config.get('interval_minutes', 5) * 60
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
        logger.info("Pump Detector Daemon V2.0 stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Pump Detector Daemon V2.0')
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
        logger.info("Daemon V2.0 terminated")
