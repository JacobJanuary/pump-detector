#!/usr/bin/env python3
"""
Signal Correlator Daemon
Кластеризует связанные SPOT и FUTURES сигналы в временном окне ±7 дней
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import logging
import sys
import os
import signal as sig
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DATABASE

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/elcrypto/pump_detector/logs/signal_correlator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class SignalCorrelator:
    """Correlates SPOT and FUTURES signals into clusters"""

    def __init__(self):
        self.db_config = DATABASE
        self.conn = None
        self.running = True
        self.correlation_interval = 5  # minutes
        self.cluster_window_days = 7  # ±7 days window

        sig.signal(sig.SIGINT, self.handle_shutdown)
        sig.signal(sig.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def connect(self):
        """Connect to database"""
        try:
            if not self.db_config.get('password'):
                conn_params = {
                    'dbname': self.db_config['dbname'],
                    'cursor_factory': RealDictCursor
                }
            else:
                conn_params = self.db_config.copy()
                conn_params['cursor_factory'] = RealDictCursor

            self.conn = psycopg2.connect(**conn_params)
            self.conn.autocommit = False
            logger.info("Database connection established")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def find_unclustered_signals(self):
        """Find signals without cluster assignment"""

        query = """
        SELECT
            id,
            pair_symbol,
            signal_type,
            signal_timestamp,
            spike_ratio_7d,
            oi_change_pct
        FROM pump.signals
        WHERE cluster_id IS NULL
          AND status IN ('DETECTED', 'MONITORING', 'CONFIRMED')
        ORDER BY signal_timestamp DESC
        LIMIT 100
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Error finding unclustered signals: {e}")
            return []

    def find_or_create_cluster(self, signal):
        """Find existing cluster or create new one for signal"""

        # Ищем существующий кластер в окне ±7 дней для того же символа
        find_query = """
        SELECT id, pair_symbol, first_signal_time, last_signal_time
        FROM pump.signal_clusters
        WHERE pair_symbol = %s
          AND status = 'ACTIVE'
          AND first_signal_time >= %s - INTERVAL '%s days'
          AND first_signal_time <= %s + INTERVAL '%s days'
        ORDER BY first_signal_time DESC
        LIMIT 1
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(find_query, (
                    signal['pair_symbol'],
                    signal['signal_timestamp'],
                    self.cluster_window_days,
                    signal['signal_timestamp'],
                    self.cluster_window_days
                ))
                cluster = cur.fetchone()

                if cluster:
                    # Обновляем существующий кластер
                    logger.info(f"Found existing cluster #{cluster['id']} for {signal['pair_symbol']}")
                    return cluster['id']
                else:
                    # Создаем новый кластер
                    create_query = """
                    INSERT INTO pump.signal_clusters (
                        pair_symbol,
                        first_signal_time,
                        last_signal_time,
                        has_futures_spike,
                        has_spot_spike,
                        status
                    ) VALUES (%s, %s, %s, %s, %s, 'ACTIVE')
                    RETURNING id
                    """

                    cur.execute(create_query, (
                        signal['pair_symbol'],
                        signal['signal_timestamp'],
                        signal['signal_timestamp'],
                        signal['signal_type'] == 'FUTURES',
                        signal['signal_type'] == 'SPOT'
                    ))

                    cluster_id = cur.fetchone()['id']
                    logger.info(f"Created new cluster #{cluster_id} for {signal['pair_symbol']}")
                    return cluster_id

        except Exception as e:
            logger.error(f"Error finding/creating cluster: {e}")
            return None

    def assign_signal_to_cluster(self, signal_id, cluster_id):
        """Assign signal to cluster"""

        try:
            with self.conn.cursor() as cur:
                # Обновляем сигнал
                cur.execute("""
                    UPDATE pump.signals
                    SET cluster_id = %s, updated_at = NOW()
                    WHERE id = %s
                """, (cluster_id, signal_id))

                logger.debug(f"Assigned signal #{signal_id} to cluster #{cluster_id}")
                return True

        except Exception as e:
            logger.error(f"Error assigning signal to cluster: {e}")
            return False

    def update_cluster_metadata(self, cluster_id):
        """Update cluster metadata based on its signals"""

        query = """
        WITH cluster_signals AS (
            SELECT
                signal_type,
                signal_timestamp,
                spike_ratio_7d,
                oi_change_pct,
                price_change_1h,
                price_change_4h,
                price_change_24h
            FROM pump.signals
            WHERE cluster_id = %s
        ),
        cluster_stats AS (
            SELECT
                MIN(signal_timestamp) as first_time,
                MAX(signal_timestamp) as last_time,
                BOOL_OR(signal_type = 'FUTURES') as has_futures,
                BOOL_OR(signal_type = 'SPOT') as has_spot,
                MAX(COALESCE(price_change_24h, 0)) as max_price_change
            FROM cluster_signals
        )
        UPDATE pump.signal_clusters
        SET
            first_signal_time = cs.first_time,
            last_signal_time = cs.last_time,
            has_futures_spike = cs.has_futures,
            has_spot_spike = cs.has_spot,
            max_price_change = cs.max_price_change,
            updated_at = NOW()
        FROM cluster_stats cs
        WHERE id = %s
        RETURNING
            id,
            pair_symbol,
            has_futures_spike,
            has_spot_spike,
            max_price_change
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (cluster_id, cluster_id))
                cluster = cur.fetchone()

                if cluster:
                    logger.info(
                        f"Updated cluster #{cluster['id']} {cluster['pair_symbol']}: "
                        f"Futures={cluster['has_futures_spike']}, "
                        f"Spot={cluster['has_spot_spike']}, "
                        f"MaxPrice={cluster['max_price_change']}"
                    )
                    return True

        except Exception as e:
            logger.error(f"Error updating cluster metadata: {e}")
            return False

    def calculate_cluster_score(self, cluster_id):
        """Calculate total score for cluster based on all signals"""

        query = """
        WITH cluster_signals AS (
            SELECT
                s.id,
                s.signal_type,
                s.spike_ratio_7d,
                s.oi_change_pct,
                COALESCE(ss.total_score, 0) as signal_score
            FROM pump.signals s
            LEFT JOIN pump.signal_scores ss ON s.id = ss.signal_id
            WHERE s.cluster_id = %s
        )
        SELECT
            COUNT(*) as signal_count,
            SUM(signal_score) as total_score,
            AVG(spike_ratio_7d) as avg_spike_ratio,
            MAX(spike_ratio_7d) as max_spike_ratio,
            COUNT(*) FILTER (WHERE signal_type = 'FUTURES') as futures_count,
            COUNT(*) FILTER (WHERE signal_type = 'SPOT') as spot_count,
            AVG(oi_change_pct) FILTER (WHERE signal_type = 'FUTURES') as avg_oi_change
        FROM cluster_signals
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (cluster_id,))
                stats = cur.fetchone()

                if stats and stats['signal_count'] > 0:
                    # Обновляем total_score кластера
                    cur.execute("""
                        UPDATE pump.signal_clusters
                        SET total_score = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (stats['total_score'] or 0, cluster_id))

                    logger.info(
                        f"Cluster #{cluster_id} score: {stats['total_score']} "
                        f"({stats['futures_count']} FUTURES + {stats['spot_count']} SPOT)"
                    )

                    return stats

        except Exception as e:
            logger.error(f"Error calculating cluster score: {e}")
            return None

    def expire_old_clusters(self):
        """Mark old clusters as EXPIRED"""

        query = """
        UPDATE pump.signal_clusters
        SET status = 'EXPIRED', updated_at = NOW()
        WHERE status = 'ACTIVE'
          AND last_signal_time < NOW() - INTERVAL '7 days'
        RETURNING id, pair_symbol, first_signal_time
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                expired = cur.fetchall()

                if expired:
                    logger.info(f"Expired {len(expired)} old clusters")
                    for cluster in expired[:5]:
                        logger.debug(f"  Expired cluster #{cluster['id']} {cluster['pair_symbol']}")

                self.conn.commit()
                return len(expired)

        except Exception as e:
            logger.error(f"Error expiring old clusters: {e}")
            self.conn.rollback()
            return 0

    def correlate_signals(self):
        """Main correlation logic - assign signals to clusters"""

        unclustered = self.find_unclustered_signals()

        if not unclustered:
            logger.debug("No unclustered signals found")
            return 0

        logger.info(f"Found {len(unclustered)} unclustered signals")

        clustered_count = 0
        updated_clusters = set()

        for signal in unclustered:
            try:
                # Найти или создать кластер
                cluster_id = self.find_or_create_cluster(signal)

                if cluster_id:
                    # Назначить сигнал кластеру
                    if self.assign_signal_to_cluster(signal['id'], cluster_id):
                        clustered_count += 1
                        updated_clusters.add(cluster_id)

            except Exception as e:
                logger.error(f"Error processing signal #{signal['id']}: {e}")
                continue

        # Обновить метаданные кластеров
        for cluster_id in updated_clusters:
            self.update_cluster_metadata(cluster_id)
            self.calculate_cluster_score(cluster_id)

        # Commit всех изменений
        try:
            self.conn.commit()
            logger.info(f"Clustered {clustered_count} signals into {len(updated_clusters)} clusters")
        except Exception as e:
            logger.error(f"Error committing changes: {e}")
            self.conn.rollback()
            return 0

        return clustered_count

    def run(self):
        """Main daemon loop"""

        logger.info("Starting Signal Correlator Daemon")
        logger.info(f"Correlation interval: {self.correlation_interval} minutes")
        logger.info(f"Cluster window: ±{self.cluster_window_days} days")

        self.connect()

        cycle_count = 0

        while self.running:
            try:
                cycle_count += 1
                logger.info(f"Starting correlation cycle #{cycle_count}")

                # Кластеризовать некластеризованные сигналы
                clustered = self.correlate_signals()

                # Периодически закрывать старые кластеры (каждый 12-й цикл = 1 час)
                if cycle_count % 12 == 0:
                    expired = self.expire_old_clusters()

                # Sleep until next cycle
                sleep_seconds = self.correlation_interval * 60
                logger.debug(f"Sleeping for {sleep_seconds} seconds...")

                for _ in range(sleep_seconds):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Error in correlation cycle: {e}")
                time.sleep(60)

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
        logger.info("Signal Correlator Daemon stopped")


if __name__ == "__main__":
    correlator = SignalCorrelator()

    try:
        correlator.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Correlator terminated")
