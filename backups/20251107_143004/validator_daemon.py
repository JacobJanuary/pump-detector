#!/usr/bin/env python3
"""
Signal Validator Daemon - Monitors active signals for pump confirmation
Runs every 15 minutes to check price movements after signals
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

from config.settings import DATABASE, DETECTION

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/pump_detector/logs/validator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SignalValidatorDaemon:
    """Daemon for validating and updating signal statuses"""

    def __init__(self):
        self.db_config = DATABASE
        self.conn = None
        self.running = True
        self.detection_config = DETECTION
        self.validation_interval = 15  # Check every 15 minutes
        self.pump_threshold = DETECTION['pump_threshold_pct']
        self.monitoring_hours = DETECTION['monitoring_hours']

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

    def get_active_signals(self):
        """Get all signals that need validation"""

        query = """
        SELECT
            s.id,
            s.trading_pair_id,
            s.pair_symbol,
            s.signal_timestamp,
            s.detected_at,
            s.status,
            s.signal_strength,
            s.initial_confidence,
            s.futures_spike_ratio_7d,
            s.max_price_increase,
            -- Get initial candle price as reference
            (
                SELECT c.close_price
                FROM public.candles c
                WHERE c.trading_pair_id = s.trading_pair_id
                  AND c.interval_id = 4  -- 4h
                  AND to_timestamp(c.open_time / 1000) = s.signal_timestamp
                LIMIT 1
            ) as reference_price,
            -- Hours since signal
            EXTRACT(HOUR FROM (NOW() - s.signal_timestamp)) as hours_since_signal
        FROM pump.signals s
        WHERE s.status IN ('DETECTED', 'MONITORING')
          AND s.signal_timestamp >= NOW() - INTERVAL '%s hours'
        ORDER BY s.signal_timestamp DESC
        """ % self.monitoring_hours

        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Error fetching active signals: {e}")
            return []

    def check_price_movement(self, signal):
        """Check price movement since signal detection"""

        query = """
        WITH price_data AS (
            SELECT
                MAX(c.high_price) as max_price,
                MIN(c.low_price) as min_price,
                -- Latest price
                (SELECT close_price
                 FROM public.candles c2
                 WHERE c2.trading_pair_id = %s
                   AND c2.interval_id = 4
                 ORDER BY c2.open_time DESC
                 LIMIT 1) as current_price
            FROM public.candles c
            WHERE c.trading_pair_id = %s
              AND c.interval_id = 4  -- 4h
              AND to_timestamp(c.open_time / 1000) >= %s
        )
        SELECT
            max_price,
            min_price,
            current_price,
            CASE
                WHEN %s > 0 THEN ((max_price - %s) / %s * 100)
                ELSE 0
            END as max_gain_pct,
            CASE
                WHEN %s > 0 THEN ((current_price - %s) / %s * 100)
                ELSE 0
            END as current_gain_pct,
            CASE
                WHEN %s > 0 THEN ((%s - min_price) / %s * 100)
                ELSE 0
            END as max_drawdown_pct
        FROM price_data
        """

        try:
            with self.conn.cursor() as cur:
                reference_price = signal['reference_price']

                cur.execute(query, (
                    signal['trading_pair_id'],
                    signal['trading_pair_id'],
                    signal['signal_timestamp'],
                    reference_price, reference_price, reference_price,
                    reference_price, reference_price, reference_price,
                    reference_price, reference_price, reference_price
                ))

                result = cur.fetchone()
                if result:
                    return {
                        'max_price': result['max_price'],
                        'min_price': result['min_price'],
                        'current_price': result['current_price'],
                        'max_gain_pct': result['max_gain_pct'],
                        'current_gain_pct': result['current_gain_pct'],
                        'max_drawdown_pct': result['max_drawdown_pct']
                    }

        except Exception as e:
            logger.error(f"Error checking price for {signal['pair_symbol']}: {e}")

        return None

    def update_signal_status(self, signal, price_data):
        """Update signal status based on price movement"""

        new_status = signal['status']
        pump_realized = False
        notes = []

        # Check if pump threshold reached
        if price_data['max_gain_pct'] >= self.pump_threshold:
            new_status = 'CONFIRMED'
            pump_realized = True
            notes.append(f"Pump confirmed: {price_data['max_gain_pct']:.1f}% gain")
            logger.info(f"✅ PUMP CONFIRMED: {signal['pair_symbol']} reached {price_data['max_gain_pct']:.1f}% gain")

        # Check if signal expired (7 days without pump)
        elif signal['hours_since_signal'] >= self.monitoring_hours:
            new_status = 'FAILED'
            notes.append(f"Signal expired after {self.monitoring_hours} hours. Max gain: {price_data['max_gain_pct']:.1f}%")
            logger.info(f"❌ Signal expired: {signal['pair_symbol']} max gain was {price_data['max_gain_pct']:.1f}%")

        # Check for stop loss (significant drawdown)
        elif price_data['max_drawdown_pct'] >= 15:
            new_status = 'FAILED'
            notes.append(f"Stop loss triggered: -{price_data['max_drawdown_pct']:.1f}% drawdown")
            logger.warning(f"🛑 Stop loss: {signal['pair_symbol']} dropped -{price_data['max_drawdown_pct']:.1f}%")

        # Update to monitoring if still in DETECTED status
        elif signal['status'] == 'DETECTED' and signal['hours_since_signal'] >= 4:
            new_status = 'MONITORING'
            notes.append("Moved to monitoring phase")

        # Update signal in database
        if new_status != signal['status'] or price_data['max_gain_pct'] != signal['max_price_increase']:
            try:
                update_query = """
                UPDATE pump.signals
                SET
                    status = %s,
                    max_price_increase = %s,
                    pump_realized = %s,
                    validation_notes = %s,
                    updated_at = NOW()
                WHERE id = %s
                """

                with self.conn.cursor() as cur:
                    cur.execute(update_query, (
                        new_status,
                        price_data['max_gain_pct'],
                        pump_realized,
                        '; '.join(notes) if notes else None,
                        signal['id']
                    ))

                    # Add to tracking history
                    tracking_query = """
                    INSERT INTO pump.signal_tracking (
                        signal_id,
                        check_timestamp,
                        current_price,
                        price_change_pct,
                        max_price_since_signal,
                        status_at_check
                    ) VALUES (%s, NOW(), %s, %s, %s, %s)
                    """

                    cur.execute(tracking_query, (
                        signal['id'],
                        price_data['current_price'],
                        price_data['current_gain_pct'],
                        price_data['max_price'],
                        new_status
                    ))

                    self.conn.commit()

                    logger.debug(f"Updated {signal['pair_symbol']}: {signal['status']} → {new_status}")

            except Exception as e:
                logger.error(f"Error updating signal {signal['id']}: {e}")
                self.conn.rollback()

    def check_for_confirmations(self, signal):
        """Check for additional confirmation signals"""

        # Look for volume confirmations on smaller timeframes
        query = """
        SELECT COUNT(*) as confirmation_count
        FROM public.candles c
        WHERE c.trading_pair_id = %s
          AND c.interval_id IN (2, 3)  -- 1h, 2h
          AND to_timestamp(c.open_time / 1000) >= %s
          AND c.quote_asset_volume > (
              SELECT AVG(c2.quote_asset_volume) * 2
              FROM public.candles c2
              WHERE c2.trading_pair_id = c.trading_pair_id
                AND c2.interval_id = c.interval_id
                AND to_timestamp(c2.open_time / 1000) BETWEEN
                    (%s - INTERVAL '7 days') AND %s
          )
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (
                    signal['trading_pair_id'],
                    signal['signal_timestamp'],
                    signal['signal_timestamp'],
                    signal['signal_timestamp']
                ))

                result = cur.fetchone()
                if result and result['confirmation_count'] > 0:
                    # Record confirmations
                    insert_query = """
                    INSERT INTO pump.signal_confirmations (
                        signal_id,
                        confirmation_type,
                        confirmation_timestamp,
                        confirmation_value,
                        notes
                    ) VALUES (%s, %s, NOW(), %s, %s)
                    ON CONFLICT DO NOTHING
                    """

                    cur.execute(insert_query, (
                        signal['id'],
                        'VOLUME_SPIKE_1H',
                        result['confirmation_count'],
                        f"{result['confirmation_count']} volume spikes on lower timeframes"
                    ))

                    self.conn.commit()
                    logger.debug(f"Added {result['confirmation_count']} confirmations for {signal['pair_symbol']}")

        except Exception as e:
            logger.error(f"Error checking confirmations: {e}")

    def generate_validation_report(self):
        """Generate summary report of validation cycle"""

        query = """
        SELECT
            status,
            COUNT(*) as count,
            AVG(max_price_increase) as avg_gain
        FROM pump.signals
        WHERE updated_at >= NOW() - INTERVAL '15 minutes'
        GROUP BY status
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                results = cur.fetchall()

                if results:
                    logger.info("=== Validation Cycle Summary ===")
                    for row in results:
                        logger.info(f"{row['status']}: {row['count']} signals, "
                                  f"avg gain: {row['avg_gain']:.1f}%")
                    logger.info("================================")

        except Exception as e:
            logger.error(f"Error generating report: {e}")

    def run(self):
        """Main validator loop"""

        logger.info("Starting Signal Validator Daemon")
        logger.info(f"Validation interval: {self.validation_interval} minutes")
        logger.info(f"Pump threshold: {self.pump_threshold}%")
        logger.info(f"Monitoring period: {self.monitoring_hours} hours")

        self.connect()

        cycle_count = 0

        while self.running:
            try:
                cycle_count += 1
                logger.info(f"Starting validation cycle #{cycle_count}")

                # Get active signals
                active_signals = self.get_active_signals()

                if active_signals:
                    logger.info(f"Validating {len(active_signals)} active signals")

                    validated_count = 0
                    confirmed_count = 0
                    failed_count = 0

                    for signal in active_signals:
                        # Check price movement
                        price_data = self.check_price_movement(signal)

                        if price_data:
                            old_status = signal['status']
                            self.update_signal_status(signal, price_data)

                            # Check for additional confirmations
                            if signal['status'] in ['DETECTED', 'MONITORING']:
                                self.check_for_confirmations(signal)

                            validated_count += 1

                            # Count status changes
                            with self.conn.cursor() as cur:
                                cur.execute("SELECT status FROM pump.signals WHERE id = %s", (signal['id'],))
                                new_status = cur.fetchone()['status']

                                if new_status == 'CONFIRMED' and old_status != 'CONFIRMED':
                                    confirmed_count += 1
                                elif new_status == 'FAILED' and old_status != 'FAILED':
                                    failed_count += 1

                    logger.info(f"Cycle #{cycle_count} complete: "
                              f"{validated_count} validated, "
                              f"{confirmed_count} confirmed, "
                              f"{failed_count} failed")

                    # Generate summary report
                    self.generate_validation_report()

                else:
                    logger.debug(f"Cycle #{cycle_count} complete: No active signals to validate")

                # Sleep until next cycle
                sleep_seconds = self.validation_interval * 60
                logger.debug(f"Sleeping for {sleep_seconds} seconds until next cycle...")

                # Use interruptible sleep
                for _ in range(sleep_seconds):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Error in validation cycle: {e}")
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
        logger.info("Signal Validator Daemon stopped")


if __name__ == "__main__":
    daemon = SignalValidatorDaemon()

    try:
        daemon.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Daemon terminated")