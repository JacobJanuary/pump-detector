#!/usr/bin/env python3
"""
Spot/Futures Synchronization Analyzer
Detects correlated movements between spot and futures markets
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import numpy as np
from datetime import datetime, timedelta
import logging
import sys
import os
import signal
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DATABASE

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/pump_detector/logs/spot_futures.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SpotFuturesAnalyzer:
    """Analyzes correlation between spot and futures markets"""

    def __init__(self):
        self.db_config = DATABASE
        self.conn = None
        self.running = True
        self.analysis_interval = 10  # minutes

        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

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

    def get_spot_futures_pairs(self):
        """Get trading pairs that have both spot and futures markets"""

        query = """
        WITH spot_pairs AS (
            SELECT DISTINCT
                SPLIT_PART(pair_symbol, 'USDT', 1) as base_asset,
                id as spot_pair_id,
                pair_symbol as spot_symbol
            FROM public.trading_pairs
            WHERE exchange_id = 1  -- Binance
              AND is_active = true
              AND contract_type_id IS NULL  -- Spot
              AND pair_symbol LIKE '%USDT'
        ),
        futures_pairs AS (
            SELECT DISTINCT
                SPLIT_PART(pair_symbol, 'USDT', 1) as base_asset,
                id as futures_pair_id,
                pair_symbol as futures_symbol
            FROM public.trading_pairs
            WHERE exchange_id = 1
              AND is_active = true
              AND contract_type_id = 1  -- Futures
              AND pair_symbol LIKE '%USDT'
        )
        SELECT
            sp.base_asset,
            sp.spot_pair_id,
            sp.spot_symbol,
            fp.futures_pair_id,
            fp.futures_symbol
        FROM spot_pairs sp
        INNER JOIN futures_pairs fp ON sp.base_asset = fp.base_asset
        WHERE sp.base_asset != ''
        ORDER BY sp.base_asset
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Error fetching pairs: {e}")
            return []

    def analyze_correlation(self, spot_id, futures_id, hours_back=24):
        """Analyze correlation between spot and futures volumes"""

        query = """
        WITH spot_data AS (
            SELECT
                to_timestamp(open_time / 1000) as candle_time,
                close_price as spot_price,
                quote_asset_volume as spot_volume,
                number_of_trades as spot_trades
            FROM public.candles
            WHERE trading_pair_id = %s
              AND interval_id = 3  -- 2h candles
              AND to_timestamp(open_time / 1000) >= NOW() - INTERVAL '%s hours'
            ORDER BY open_time
        ),
        futures_data AS (
            SELECT
                to_timestamp(open_time / 1000) as candle_time,
                close_price as futures_price,
                quote_asset_volume as futures_volume,
                number_of_trades as futures_trades,
                open_interest,
                open_interest_value
            FROM public.candles
            WHERE trading_pair_id = %s
              AND interval_id = 3  -- 2h candles
              AND to_timestamp(open_time / 1000) >= NOW() - INTERVAL '%s hours'
            ORDER BY open_time
        ),
        combined AS (
            SELECT
                s.candle_time,
                s.spot_price,
                s.spot_volume,
                s.spot_trades,
                f.futures_price,
                f.futures_volume,
                f.futures_trades,
                f.open_interest,
                -- Calculate price premium/discount
                ((f.futures_price - s.spot_price) / s.spot_price * 100) as basis_pct,
                -- Volume ratio
                (f.futures_volume / NULLIF(s.spot_volume, 0)) as volume_ratio
            FROM spot_data s
            INNER JOIN futures_data f ON s.candle_time = f.candle_time
        )
        SELECT
            candle_time,
            spot_price,
            futures_price,
            basis_pct,
            spot_volume,
            futures_volume,
            volume_ratio,
            open_interest,
            -- Moving averages
            AVG(volume_ratio) OVER (ORDER BY candle_time ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) as ma_volume_ratio,
            AVG(basis_pct) OVER (ORDER BY candle_time ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) as ma_basis
        FROM combined
        ORDER BY candle_time DESC
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (spot_id, hours_back, futures_id, hours_back))
                data = cur.fetchall()

                if len(data) >= 5:
                    # Calculate correlation
                    spot_volumes = [d['spot_volume'] for d in data if d['spot_volume']]
                    futures_volumes = [d['futures_volume'] for d in data if d['futures_volume']]

                    if len(spot_volumes) > 1 and len(futures_volumes) > 1:
                        correlation = np.corrcoef(spot_volumes[:min(len(spot_volumes), len(futures_volumes))],
                                                 futures_volumes[:min(len(spot_volumes), len(futures_volumes))])[0, 1]

                        # Detect anomalies
                        latest = data[0]
                        anomalies = []

                        # Check for volume divergence
                        if latest['volume_ratio'] and latest['ma_volume_ratio']:
                            if latest['volume_ratio'] > latest['ma_volume_ratio'] * 2:
                                anomalies.append('FUTURES_VOLUME_SPIKE')
                            elif latest['volume_ratio'] < latest['ma_volume_ratio'] * 0.5:
                                anomalies.append('SPOT_VOLUME_SPIKE')

                        # Check for basis anomaly
                        if latest['basis_pct'] and latest['ma_basis']:
                            if abs(latest['basis_pct']) > abs(latest['ma_basis']) * 2:
                                anomalies.append('BASIS_ANOMALY')

                        return {
                            'correlation': correlation,
                            'latest_basis': latest['basis_pct'],
                            'latest_volume_ratio': latest['volume_ratio'],
                            'anomalies': anomalies,
                            'timestamp': latest['candle_time']
                        }

        except Exception as e:
            logger.error(f"Error analyzing correlation: {e}")

        return None

    def detect_synchronized_pumps(self):
        """Detect synchronized pump signals across spot and futures"""

        query = """
        WITH recent_signals AS (
            SELECT
                s.*,
                tp.pair_symbol,
                SPLIT_PART(tp.pair_symbol, 'USDT', 1) as base_asset
            FROM pump.signals s
            INNER JOIN public.trading_pairs tp ON s.trading_pair_id = tp.id
            WHERE s.status IN ('DETECTED', 'MONITORING')
              AND s.signal_timestamp >= NOW() - INTERVAL '4 hours'
        ),
        spot_activity AS (
            SELECT DISTINCT
                SPLIT_PART(tp.pair_symbol, 'USDT', 1) as base_asset,
                MAX(c.quote_asset_volume) as max_spot_volume,
                AVG(c.quote_asset_volume) as avg_spot_volume
            FROM public.candles c
            INNER JOIN public.trading_pairs tp ON c.trading_pair_id = tp.id
            WHERE tp.exchange_id = 1
              AND tp.contract_type_id IS NULL  -- Spot
              AND tp.pair_symbol LIKE '%USDT'
              AND to_timestamp(c.open_time / 1000) >= NOW() - INTERVAL '4 hours'
            GROUP BY SPLIT_PART(tp.pair_symbol, 'USDT', 1)
        )
        SELECT
            rs.id as signal_id,
            rs.base_asset,
            rs.pair_symbol as pair_symbol,
            rs.signal_timestamp,
            rs.futures_spike_ratio_7d,
            sa.max_spot_volume / NULLIF(sa.avg_spot_volume, 0) as spot_spike_ratio,
            CASE
                WHEN sa.max_spot_volume / NULLIF(sa.avg_spot_volume, 0) > 2 THEN TRUE
                ELSE FALSE
            END as spot_confirmed
        FROM recent_signals rs
        LEFT JOIN spot_activity sa ON rs.base_asset = sa.base_asset
        WHERE rs.base_asset != ''
        ORDER BY rs.signal_timestamp DESC
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query)
                signals = cur.fetchall()

                synchronized_count = 0
                for signal in signals:
                    if signal['spot_confirmed']:
                        synchronized_count += 1
                        logger.info(f"Synchronized pump detected: {signal['pair_symbol']} "
                                  f"(Futures: {signal['futures_spike_ratio_7d']:.1f}x, "
                                  f"Spot: {signal['spot_spike_ratio']:.1f}x)")

                        # Update signal with spot confirmation
                        self.update_signal_correlation(signal['signal_id'], signal['spot_spike_ratio'])

                if synchronized_count > 0:
                    logger.info(f"Found {synchronized_count} synchronized pump signals")

                return synchronized_count

        except Exception as e:
            logger.error(f"Error detecting synchronized pumps: {e}")
            return 0

    def update_signal_correlation(self, signal_id, spot_spike_ratio):
        """Update signal with spot/futures correlation data"""

        try:
            update_query = """
            UPDATE pump.signals
            SET
                spot_volume_change_pct = %s,
                spot_futures_correlation = 0.8,  -- Placeholder
                updated_at = NOW()
            WHERE id = %s
            """

            with self.conn.cursor() as cur:
                cur.execute(update_query, ((spot_spike_ratio - 1) * 100, signal_id))

                # Add confirmation
                confirm_query = """
                INSERT INTO pump.signal_confirmations (
                    signal_id,
                    confirmation_type,
                    confirmation_timestamp,
                    confirmation_value,
                    notes
                ) VALUES (%s, 'SPOT_SYNC', NOW(), %s, %s)
                ON CONFLICT DO NOTHING
                """

                cur.execute(confirm_query, (
                    signal_id,
                    spot_spike_ratio,
                    f"Spot volume spike: {spot_spike_ratio:.1f}x"
                ))

                self.conn.commit()

        except Exception as e:
            logger.error(f"Error updating signal: {e}")
            self.conn.rollback()

    def analyze_all_pairs(self):
        """Analyze all spot/futures pairs for correlation"""

        pairs = self.get_spot_futures_pairs()
        logger.info(f"Analyzing {len(pairs)} spot/futures pairs")

        high_correlation_pairs = []
        anomaly_pairs = []

        for pair in pairs[:50]:  # Limit to top 50 for performance
            result = self.analyze_correlation(
                pair['spot_pair_id'],
                pair['futures_pair_id'],
                hours_back=24
            )

            if result:
                # High correlation pairs
                if result['correlation'] > 0.8:
                    high_correlation_pairs.append({
                        'asset': pair['base_asset'],
                        'correlation': result['correlation']
                    })

                # Pairs with anomalies
                if result['anomalies']:
                    anomaly_pairs.append({
                        'asset': pair['base_asset'],
                        'anomalies': result['anomalies'],
                        'basis': result['latest_basis'],
                        'volume_ratio': result['latest_volume_ratio']
                    })

        # Log summary
        if high_correlation_pairs:
            logger.info(f"High correlation pairs (>0.8): {len(high_correlation_pairs)}")
            for pair in high_correlation_pairs[:5]:
                logger.info(f"  {pair['asset']}: {pair['correlation']:.3f}")

        if anomaly_pairs:
            logger.warning(f"Pairs with anomalies: {len(anomaly_pairs)}")
            for pair in anomaly_pairs[:5]:
                logger.warning(f"  {pair['asset']}: {', '.join(pair['anomalies'])}")

        return {
            'high_correlation': high_correlation_pairs,
            'anomalies': anomaly_pairs
        }

    def run(self):
        """Main analysis loop"""

        logger.info("Starting Spot/Futures Analyzer")
        logger.info(f"Analysis interval: {self.analysis_interval} minutes")

        self.connect()

        cycle_count = 0

        while self.running:
            try:
                cycle_count += 1
                logger.info(f"Starting analysis cycle #{cycle_count}")

                # Detect synchronized pumps
                sync_count = self.detect_synchronized_pumps()

                # Analyze all pairs periodically (every 6 cycles = 1 hour)
                if cycle_count % 6 == 0:
                    logger.info("Running full correlation analysis...")
                    self.analyze_all_pairs()

                # Sleep until next cycle
                sleep_seconds = self.analysis_interval * 60
                logger.debug(f"Sleeping for {sleep_seconds} seconds...")

                for _ in range(sleep_seconds):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Error in analysis cycle: {e}")
                time.sleep(60)

                # Reconnect if needed
                try:
                    self.conn.ping()
                except:
                    logger.info("Reconnecting to database...")
                    self.connect()

        # Cleanup
        if self.conn:
            self.conn.close()
        logger.info("Spot/Futures Analyzer stopped")

if __name__ == "__main__":
    analyzer = SpotFuturesAnalyzer()

    try:
        analyzer.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Analyzer terminated")