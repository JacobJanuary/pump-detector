#!/usr/bin/env python3
"""
Analysis Runner V2.0 - Периодический анализ всех символов
Запускает PumpDetectionEngine для всех активных пар
Создает/обновляет pump candidates и сохраняет snapshots
"""

import time
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import sys
import os
import signal
import argparse

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE
from engine.database_helper import PumpDatabaseHelper
from engine.pump_detection_engine import PumpDetectionEngine
from engine.telegram_alerts import TelegramAlerter

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/elcrypto/pump_detector/logs/analysis_runner_v2.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AnalysisRunner:
    """
    Analysis Runner V2.0

    Периодически:
    1. Получает список активных торговых пар с достаточным количеством сигналов
    2. Запускает PumpDetectionEngine.analyze_symbol() для каждой
    3. Создает/обновляет записи в pump.pump_candidates
    4. Сохраняет analysis snapshots
    5. Связывает кандидаты с сигналами через pump.candidate_signals
    """

    def __init__(self, interval_minutes=30, once_mode=False):
        self.db_config = DATABASE
        self.db = None
        self.engine = None
        self.running = True
        self.interval_minutes = interval_minutes
        self.once_mode = once_mode

        # Telegram alerter
        telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.telegram = TelegramAlerter(telegram_bot_token, telegram_chat_id)

        # Signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def connect(self):
        """Connect to database and initialize engine"""
        try:
            self.db = PumpDatabaseHelper(DATABASE)
            self.db.connect()

            self.engine = PumpDetectionEngine(self.db)

            logger.info("Analysis Runner V2.0 initialized")
            logger.info(f"Engine config: min_signals={self.engine.min_signal_count}, "
                       f"HIGH≥{self.engine.high_conf_threshold}, "
                       f"MEDIUM≥{self.engine.medium_conf_threshold}")
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            raise

    def get_symbols_to_analyze(self):
        """
        Получить список символов для анализа

        Критерии:
        - Есть хотя бы 10 сигналов за последние 7 дней
        - Символ активен (is_active = true)

        Returns:
            List of (pair_symbol, signal_count, trading_pair_id)
        """
        try:
            query = """
            SELECT
                rs.pair_symbol,
                MIN(rs.trading_pair_id) as trading_pair_id,
                COUNT(*) as signal_count,
                COUNT(*) FILTER (WHERE rs.signal_strength = 'EXTREME') as extreme_count,
                MAX(rs.signal_timestamp) as latest_signal
            FROM pump.raw_signals rs
            INNER JOIN trading_pairs tp ON rs.trading_pair_id = tp.id
            WHERE rs.signal_timestamp >= NOW() - INTERVAL '7 days'
              AND tp.is_active = true
            GROUP BY rs.pair_symbol
            HAVING COUNT(*) >= %s
            ORDER BY extreme_count DESC, signal_count DESC
            """

            with self.db.conn.cursor() as cur:
                cur.execute(query, (self.engine.min_signal_count,))
                symbols = cur.fetchall()

            logger.info(f"Found {len(symbols)} symbols with ≥{self.engine.min_signal_count} signals")
            return symbols

        except Exception as e:
            logger.error(f"Error getting symbols to analyze: {e}")
            return []

    def process_detection(self, detection_result, trading_pair_id):
        """
        Обработать результат детектирования

        1. Создать/обновить pump.pump_candidates
        2. Сохранить analysis snapshot
        3. Связать кандидата с сигналами

        Args:
            detection_result: Dict from PumpDetectionEngine.analyze_symbol()
            trading_pair_id: ID торговой пары

        Returns:
            candidate_id or None
        """
        try:
            symbol = detection_result['pair_symbol']

            # Проверяем наличие сигналов
            if not detection_result['signals']:
                logger.warning(f"{symbol}: No signals in detection result")
                return None

            # 1. Создать/обновить candidate
            candidate_data = {
                'pair_symbol': symbol,
                'trading_pair_id': trading_pair_id,
                'confidence': detection_result['confidence'],
                'score': detection_result['score'],
                'pattern_type': detection_result['pattern_type'],
                'total_signals': detection_result['total_signals'],
                'extreme_signals': detection_result['extreme_signals'],
                'critical_window_signals': detection_result['critical_window_signals'],
                'eta_hours': detection_result['eta_hours'],
                'is_actionable': detection_result['is_actionable'],
                'pump_phase': detection_result.get('pump_phase', 'UNKNOWN'),
                'price_change_from_first': detection_result.get('price_change_from_first', 0.0),
                'price_change_24h': detection_result.get('price_change_24h', 0.0),
                'hours_since_last_pump': detection_result.get('hours_since_last_pump')
            }

            candidate_id = self.db.create_or_update_candidate(candidate_data)

            if not candidate_id:
                logger.error(f"{symbol}: Failed to create/update candidate")
                return None

            logger.info(f"{symbol}: Candidate created/updated (id={candidate_id}, "
                       f"confidence={detection_result['confidence']}, "
                       f"score={detection_result['score']:.2f}, "
                       f"actionable={detection_result['is_actionable']})")

            # 2. Сохранить analysis snapshot
            self.db.save_analysis_snapshot(candidate_id, detection_result['analysis_details'])
            logger.debug(f"{symbol}: Analysis snapshot saved")

            # 3. Связать кандидата с сигналами
            self.link_candidate_signals(candidate_id, detection_result['signals'])
            logger.debug(f"{symbol}: Linked {len(detection_result['signals'])} signals")

            return candidate_id

        except Exception as e:
            logger.error(f"Error processing detection for {detection_result.get('pair_symbol', 'UNKNOWN')}: {e}")
            return None

    def link_candidate_signals(self, candidate_id, signals):
        """
        Связать кандидата с его сигналами

        Args:
            candidate_id: ID кандидата
            signals: List of signal dicts
        """
        try:
            # Очистить старые связи для этого кандидата
            with self.db.conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM pump.candidate_signals
                    WHERE candidate_id = %s
                """, (candidate_id,))

                # Вставить новые связи
                for signal in signals:
                    # Рассчитать hours_before_detection (пока не используется, но для будущего)
                    insert_query = """
                    INSERT INTO pump.candidate_signals (
                        candidate_id, signal_id, relevance_score
                    ) VALUES (%s, %s, %s)
                    ON CONFLICT (candidate_id, signal_id) DO NOTHING
                    """

                    # Relevance score на основе силы сигнала
                    relevance = {
                        'EXTREME': 1.0,
                        'VERY_STRONG': 0.8,
                        'STRONG': 0.6,
                        'MEDIUM': 0.4,
                        'WEAK': 0.2
                    }.get(signal['signal_strength'], 0.5)

                    cur.execute(insert_query, (candidate_id, signal['id'], relevance))

                self.db.conn.commit()

        except Exception as e:
            logger.error(f"Error linking candidate signals: {e}")
            self.db.conn.rollback()

    def run_analysis_cycle(self):
        """
        Выполнить один цикл анализа

        Returns:
            (total_analyzed, detections_count, actionable_count)
        """
        logger.info("="*60)
        logger.info("Starting analysis cycle")
        logger.info("="*60)

        # Получить символы для анализа
        symbols = self.get_symbols_to_analyze()

        if not symbols:
            logger.info("No symbols to analyze")
            return (0, 0, 0)

        total_analyzed = 0
        detections = []
        actionable = []

        for symbol_data in symbols:
            symbol = symbol_data['pair_symbol']
            trading_pair_id = symbol_data['trading_pair_id']
            signal_count = symbol_data['signal_count']

            try:
                logger.info(f"Analyzing {symbol} ({signal_count} signals)...")

                # Запустить engine
                result = self.engine.analyze_symbol(symbol)

                total_analyzed += 1

                if result:
                    # Pump pattern detected!
                    detections.append(result)

                    logger.info(f"  ✅ DETECTED: {result['confidence']} confidence, "
                               f"score={result['score']:.2f}, "
                               f"pattern={result['pattern_type']}, "
                               f"actionable={result['is_actionable']}")

                    # Обработать детектирование
                    candidate_id = self.process_detection(result, trading_pair_id)

                    if result['is_actionable'] and candidate_id:
                        actionable.append({
                            'candidate_id': candidate_id,
                            'symbol': symbol,
                            'result': result
                        })

                        # Отправить Telegram alert для actionable кандидата
                        try:
                            candidate_data = {
                                'pair_symbol': result['pair_symbol'],
                                'confidence': result['confidence'],
                                'score': result['score'],
                                'pattern_type': result['pattern_type'],
                                'total_signals': result['total_signals'],
                                'extreme_signals': result['extreme_signals'],
                                'critical_window_signals': result['critical_window_signals'],
                                'eta_hours': result['eta_hours']
                            }
                            self.telegram.send_candidate_alert(candidate_data)
                        except Exception as e:
                            logger.error(f"Error sending Telegram alert: {e}")
                else:
                    logger.debug(f"  ❌ No pattern for {symbol}")

            except Exception as e:
                logger.error(f"Error analyzing {symbol}: {e}")
                continue

        # Статистика цикла
        logger.info("="*60)
        logger.info(f"Analysis cycle complete:")
        logger.info(f"  Analyzed: {total_analyzed} symbols")
        logger.info(f"  Detected: {len(detections)} pump patterns")
        logger.info(f"  Actionable: {len(actionable)} candidates")
        logger.info("="*60)

        # Вывести actionable кандидаты
        if actionable:
            logger.info("\nActionable candidates:")
            for item in actionable:
                r = item['result']
                logger.info(f"  🎯 {r['pair_symbol']:12s} - {r['confidence']:6s} - "
                           f"Score: {r['score']:5.2f} - ETA: {r['eta_hours']:3d}h - "
                           f"Pattern: {r['pattern_type']}")

        return (total_analyzed, len(detections), len(actionable))

    def expire_old_candidates(self):
        """
        Пометить старые кандидаты как EXPIRED

        Кандидаты старше 7 дней со статусом ACTIVE помечаются как EXPIRED
        """
        try:
            with self.db.conn.cursor() as cur:
                cur.execute("""
                    UPDATE pump.pump_candidates
                    SET status = 'EXPIRED'
                    WHERE status = 'ACTIVE'
                      AND first_detected_at < NOW() - INTERVAL '7 days'
                    RETURNING id, pair_symbol
                """)

                expired = cur.fetchall()
                self.db.conn.commit()

                if expired:
                    logger.info(f"Expired {len(expired)} old candidates")
                    for exp in expired:
                        logger.debug(f"  Expired: {exp['pair_symbol']} (id={exp['id']})")

        except Exception as e:
            logger.error(f"Error expiring old candidates: {e}")
            self.db.conn.rollback()

    def run(self):
        """Main runner loop"""

        mode_str = "ONCE MODE" if self.once_mode else "CONTINUOUS MODE"

        logger.info("="*60)
        logger.info(f"Analysis Runner V2.0 [{mode_str}]")
        logger.info(f"Analysis interval: {self.interval_minutes} minutes")
        logger.info("="*60)

        self.connect()

        cycle_count = 0

        while self.running:
            try:
                cycle_count += 1

                # Expire old candidates
                self.expire_old_candidates()

                # Run analysis cycle
                analyzed, detected, actionable = self.run_analysis_cycle()

                # In once mode, exit after first cycle
                if self.once_mode:
                    logger.info(f"\nOnce mode: Analysis complete")
                    break

                # Sleep until next cycle
                sleep_seconds = self.interval_minutes * 60
                logger.info(f"\nSleeping for {self.interval_minutes} minutes until next cycle...")

                # Use interruptible sleep
                for _ in range(sleep_seconds):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Error in analysis cycle: {e}")
                time.sleep(60)  # Wait 1 minute before retry

                # Reconnect if needed
                try:
                    with self.db.conn.cursor() as cur:
                        cur.execute("SELECT 1")
                except:
                    logger.info("Database connection lost, reconnecting...")
                    try:
                        self.db.close()
                    except:
                        pass
                    self.connect()

        # Cleanup
        if self.db:
            self.db.close()
        logger.info("Analysis Runner V2.0 stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Analysis Runner V2.0')
    parser.add_argument('--interval', type=int, default=30,
                       help='Analysis interval in minutes (default: 30)')
    parser.add_argument('--once', action='store_true',
                       help='Run once and exit (for cron scheduling)')
    args = parser.parse_args()

    runner = AnalysisRunner(interval_minutes=args.interval, once_mode=args.once)

    try:
        runner.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Runner terminated")
