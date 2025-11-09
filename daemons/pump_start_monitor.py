#!/usr/bin/env python3
"""
Pump Start Monitor - Real-time pump start detection
Мониторит HIGH Confidence кандидатов на предмет начала пампа
Проверяет объемы на 1h свечах SPOT и FUTURES
"""

import time
import logging
import signal
import argparse
from datetime import datetime
from typing import Dict, List, Optional
import sys
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE
from engine.database_helper import PumpDatabaseHelper
from engine.telegram_alerts import TelegramAlerter

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/elcrypto/pump_detector/logs/pump_start_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PumpStartMonitor:
    """
    Pump Start Monitor

    Мониторит HIGH Confidence кандидатов раз в час.
    Проверяет условия:
    - SPOT volume: current >= 2.0x previous
    - FUTURES volume: current >= 1.5x previous

    Если оба условия выполнены → отправляет Telegram alert
    """

    def __init__(self, interval_minutes=60, once_mode=False):
        self.db_config = DATABASE
        self.db = None
        self.running = True
        self.interval_minutes = interval_minutes
        self.once_mode = once_mode

        # Volume spike thresholds
        self.spot_threshold = 2.0      # SPOT должен вырасти в 2x
        self.futures_threshold = 1.5   # FUTURES должен вырасти в 1.5x

        # Telegram alerter
        telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.telegram = TelegramAlerter(telegram_bot_token, telegram_chat_id)

        # Track last alerts to avoid spam (symbol -> timestamp)
        self.last_alerts = {}
        self.alert_cooldown_hours = 6  # Не спамить одним символом чаще раза в 6 часов

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
            self.db = PumpDatabaseHelper(DATABASE)
            self.db.connect()
            logger.info("Pump Start Monitor initialized")
            logger.info(f"Thresholds: SPOT≥{self.spot_threshold}x, FUTURES≥{self.futures_threshold}x")
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            raise

    def get_high_confidence_candidates(self) -> List[Dict]:
        """
        Получить HIGH Confidence кандидатов

        Returns:
            List of candidate dicts
        """
        try:
            query = """
                SELECT
                    id,
                    pair_symbol,
                    trading_pair_id,
                    confidence,
                    score,
                    pattern_type,
                    total_signals,
                    extreme_signals,
                    eta_hours
                FROM pump.pump_candidates
                WHERE status = 'ACTIVE'
                  AND confidence = 'HIGH'
                ORDER BY score DESC
            """

            with self.db.conn.cursor() as cur:
                cur.execute(query)
                candidates = cur.fetchall()

            logger.info(f"Found {len(candidates)} HIGH confidence candidates to monitor")
            return candidates

        except Exception as e:
            logger.error(f"Error getting HIGH confidence candidates: {e}")
            return []

    def get_latest_candles(self, symbol: str) -> Optional[Dict]:
        """
        Получить последние 2 закрытые 1h свечи для SPOT и FUTURES

        Args:
            symbol: Пара (например 'BTCUSDT')

        Returns:
            Dict с ключами 'spot_current', 'spot_previous', 'futures_current', 'futures_previous'
            Каждое значение - dict с полями: volume, candle_time, trading_pair_id
            Или None если данных недостаточно
        """
        try:
            query = """
                WITH latest_candles AS (
                    SELECT
                        c.trading_pair_id,
                        tp.pair_symbol,
                        tp.contract_type_id,
                        CASE
                            WHEN tp.contract_type_id = 1 THEN 'SPOT'
                            WHEN tp.contract_type_id = 2 THEN 'FUTURES'
                        END as market_type,
                        c.open_time,
                        to_timestamp(c.open_time/1000) as candle_time,
                        c.quote_asset_volume,
                        c.is_closed,
                        ROW_NUMBER() OVER (PARTITION BY tp.contract_type_id ORDER BY c.open_time DESC) as rn
                    FROM candles c
                    JOIN trading_pairs tp ON c.trading_pair_id = tp.id
                    WHERE tp.pair_symbol = %s
                        AND tp.exchange_id = 1
                        AND tp.is_active = true
                        AND c.interval_id = 3
                        AND c.is_closed = true
                )
                SELECT
                    market_type,
                    rn,
                    trading_pair_id,
                    candle_time,
                    quote_asset_volume
                FROM latest_candles
                WHERE rn <= 2
                ORDER BY contract_type_id, rn
            """

            with self.db.conn.cursor() as cur:
                cur.execute(query, (symbol,))
                rows = cur.fetchall()

            if len(rows) < 4:
                logger.warning(f"{symbol}: Insufficient candle data (got {len(rows)}, need 4)")
                return None

            # Parse results
            result = {}
            for row in rows:
                market = row['market_type'].lower()
                rn = row['rn']

                key = f"{market}_{'current' if rn == 1 else 'previous'}"
                result[key] = {
                    'volume': float(row['quote_asset_volume']),
                    'candle_time': row['candle_time'],
                    'trading_pair_id': row['trading_pair_id']
                }

            # Проверяем что все 4 ключа присутствуют
            required_keys = ['spot_current', 'spot_previous', 'futures_current', 'futures_previous']
            if not all(k in result for k in required_keys):
                logger.warning(f"{symbol}: Missing some market data")
                return None

            return result

        except Exception as e:
            logger.error(f"Error getting candles for {symbol}: {e}")
            return None

    def check_pump_start(self, candidate: Dict) -> bool:
        """
        Проверить начался ли памп для кандидата

        Args:
            candidate: Candidate dict

        Returns:
            True если памп начался (оба условия выполнены)
        """
        symbol = candidate['pair_symbol']

        # Проверка cooldown
        if symbol in self.last_alerts:
            hours_since_last = (datetime.now() - self.last_alerts[symbol]).total_seconds() / 3600
            if hours_since_last < self.alert_cooldown_hours:
                logger.debug(f"{symbol}: Skipping (alert sent {hours_since_last:.1f}h ago)")
                return False

        # Получить свечи
        candles = self.get_latest_candles(symbol)
        if not candles:
            return False

        # Рассчитать ratios
        spot_current = candles['spot_current']['volume']
        spot_previous = candles['spot_previous']['volume']
        futures_current = candles['futures_current']['volume']
        futures_previous = candles['futures_previous']['volume']

        spot_ratio = spot_current / spot_previous if spot_previous > 0 else 0
        futures_ratio = futures_current / futures_previous if futures_previous > 0 else 0

        # Проверка условий
        spot_triggered = spot_ratio >= self.spot_threshold
        futures_triggered = futures_ratio >= self.futures_threshold

        logger.info(f"{symbol}: SPOT {spot_ratio:.2f}x {'✅' if spot_triggered else '❌'}, "
                   f"FUTURES {futures_ratio:.2f}x {'✅' if futures_triggered else '❌'}")

        # Оба условия должны выполниться
        if spot_triggered and futures_triggered:
            logger.warning(f"🚨 PUMP STARTED: {symbol}")
            logger.info(f"  SPOT: {spot_previous:,.0f} → {spot_current:,.0f} ({spot_ratio:.2f}x)")
            logger.info(f"  FUTURES: {futures_previous:,.0f} → {futures_current:,.0f} ({futures_ratio:.2f}x)")
            logger.info(f"  Candle time: {candles['spot_current']['candle_time']}")

            # Отправить Telegram alert
            self.send_pump_start_alert(candidate, candles, spot_ratio, futures_ratio)

            # Запомнить время alert
            self.last_alerts[symbol] = datetime.now()

            return True

        return False

    def send_pump_start_alert(self, candidate: Dict, candles: Dict, spot_ratio: float, futures_ratio: float):
        """
        Отправить Telegram alert о начале пампа

        Args:
            candidate: Candidate dict
            candles: Candles data
            spot_ratio: SPOT volume ratio
            futures_ratio: FUTURES volume ratio
        """
        try:
            symbol = candidate['pair_symbol']
            candle_time = candles['spot_current']['candle_time'].strftime('%H:%M UTC')

            message = f"""
🚨🚨🚨 PUMP HAS STARTED! 🚨🚨🚨

💎 {symbol}
⏰ Candle: {candle_time}

📊 Volume Spikes:
  • SPOT: {spot_ratio:.2f}x (threshold: {self.spot_threshold}x)
  • FUTURES: {futures_ratio:.2f}x (threshold: {self.futures_threshold}x)

🎯 Candidate Info:
  • Confidence: {candidate['confidence']}
  • Score: {candidate['score']:.2f}
  • Pattern: {candidate['pattern_type']}
  • Total Signals: {candidate['total_signals']}
  • EXTREME Signals: {candidate['extreme_signals']}
  • ETA: {candidate['eta_hours']}h

⚡ ACTION REQUIRED! ⚡
"""

            if self.telegram.send_message(message):
                logger.info(f"✅ Telegram alert sent successfully for {symbol}")
            else:
                logger.warning(f"❌ Failed to send Telegram alert for {symbol}")

        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")

    def run_check_cycle(self):
        """
        Выполнить один цикл проверки

        Returns:
            (checked_count, triggered_count)
        """
        logger.info("="*60)
        logger.info("Starting pump start check cycle")
        logger.info("="*60)

        # Получить HIGH confidence кандидатов
        candidates = self.get_high_confidence_candidates()

        if not candidates:
            logger.info("No HIGH confidence candidates to check")
            return (0, 0)

        checked = 0
        triggered = 0

        for candidate in candidates:
            symbol = candidate['pair_symbol']

            try:
                logger.info(f"Checking {symbol} (score={candidate['score']:.2f})...")

                if self.check_pump_start(candidate):
                    triggered += 1

                checked += 1

            except Exception as e:
                logger.error(f"Error checking {symbol}: {e}")
                continue

        # Статистика
        logger.info("="*60)
        logger.info(f"Check cycle complete:")
        logger.info(f"  Checked: {checked} candidates")
        logger.info(f"  Pumps detected: {triggered}")
        logger.info("="*60)

        return (checked, triggered)

    def run(self):
        """Main runner loop"""

        mode_str = "ONCE MODE" if self.once_mode else "CONTINUOUS MODE"

        logger.info("="*60)
        logger.info(f"Pump Start Monitor [{mode_str}]")
        logger.info(f"Check interval: {self.interval_minutes} minutes")
        logger.info(f"SPOT threshold: {self.spot_threshold}x")
        logger.info(f"FUTURES threshold: {self.futures_threshold}x")
        logger.info("="*60)

        self.connect()

        cycle_count = 0

        while self.running:
            try:
                cycle_count += 1

                # Run check cycle
                checked, triggered = self.run_check_cycle()

                # In once mode, exit after first cycle
                if self.once_mode:
                    logger.info(f"\nOnce mode: Check complete")
                    break

                # Sleep until next cycle
                sleep_seconds = self.interval_minutes * 60
                logger.info(f"\nSleeping for {self.interval_minutes} minutes until next check...")

                # Use interruptible sleep
                for _ in range(sleep_seconds):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Error in check cycle: {e}")
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
        logger.info("Pump Start Monitor stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Pump Start Monitor')
    parser.add_argument('--interval', type=int, default=60,
                       help='Check interval in minutes (default: 60)')
    parser.add_argument('--once', action='store_true',
                       help='Run once and exit (for testing)')
    parser.add_argument('--spot-threshold', type=float, default=2.0,
                       help='SPOT volume spike threshold (default: 2.0x)')
    parser.add_argument('--futures-threshold', type=float, default=1.5,
                       help='FUTURES volume spike threshold (default: 1.5x)')
    args = parser.parse_args()

    monitor = PumpStartMonitor(
        interval_minutes=args.interval,
        once_mode=args.once
    )

    # Override thresholds if specified
    if args.spot_threshold:
        monitor.spot_threshold = args.spot_threshold
    if args.futures_threshold:
        monitor.futures_threshold = args.futures_threshold

    try:
        monitor.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        logger.info("Monitor terminated")
