#!/usr/bin/env python3
"""
Price Updater - Обновление актуальных цен и price_change_24h

Использует Binance API (бесплатно, без лимитов):
- Получает текущие цены
- Рассчитывает price_change_24h
- Обновляет actual_price и price_change_24h в pump.pump_candidates

Запускается через cron раз в час
"""

import requests
import logging
import argparse
import signal
import sys
import os
from datetime import datetime
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE
from engine.database_helper import PumpDatabaseHelper

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/elcrypto/pump_detector/logs/price_updater.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PriceUpdater:
    """
    Price Updater

    Обновляет actual_price и price_change_24h для всех ACTIVE кандидатов
    через Binance API (ticker/24hr endpoint)
    """

    def __init__(self):
        self.db = None
        self.binance_api_base = "https://api.binance.com/api/v3"
        self.running = True

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
            logger.info("Price Updater initialized")
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def get_active_candidates(self) -> List[Dict]:
        """
        Получить список ACTIVE кандидатов

        Returns:
            List of {id, pair_symbol}
        """
        try:
            query = """
                SELECT id, pair_symbol
                FROM pump.pump_candidates
                WHERE status = 'ACTIVE'
                ORDER BY pair_symbol
            """

            with self.db.conn.cursor() as cur:
                cur.execute(query)
                candidates = cur.fetchall()

            logger.info(f"Found {len(candidates)} ACTIVE candidates")
            return candidates

        except Exception as e:
            logger.error(f"Error getting active candidates: {e}")
            return []

    def fetch_binance_24h_prices(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Получить 24h тикеры для всех символов через Binance API

        Использует endpoint: GET /api/v3/ticker/24hr
        Возвращает текущую цену и изменение за 24ч

        Args:
            symbols: List of trading pairs (e.g. ['BTCUSDT', 'ETHUSDT'])

        Returns:
            Dict {symbol: {'price': float, 'priceChangePercent': float}}
        """
        try:
            # Binance API: получить все тикеры сразу (без параметров)
            url = f"{self.binance_api_base}/ticker/24hr"

            logger.info(f"Fetching prices from Binance for {len(symbols)} symbols...")

            response = requests.get(url, timeout=10)
            response.raise_for_status()

            all_tickers = response.json()

            # Фильтруем только наши символы
            result = {}
            for ticker in all_tickers:
                symbol = ticker['symbol']
                if symbol in symbols:
                    result[symbol] = {
                        'price': float(ticker['lastPrice']),
                        'priceChangePercent': float(ticker['priceChangePercent'])
                    }

            logger.info(f"Successfully fetched {len(result)} prices from Binance")
            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Binance API request failed: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error parsing Binance response: {e}")
            return {}

    def update_candidate_prices(self, candidate_id: int, symbol: str,
                                price: float, price_change_24h: float):
        """
        Обновить actual_price и price_change_24h для кандидата

        Args:
            candidate_id: ID кандидата
            symbol: Trading pair symbol
            price: Текущая цена
            price_change_24h: Изменение за 24ч (%)
        """
        try:
            query = """
                UPDATE pump.pump_candidates
                SET
                    actual_price = %s,
                    price_change_24h = %s,
                    price_updated_at = NOW()
                WHERE id = %s
            """

            with self.db.conn.cursor() as cur:
                cur.execute(query, (price, price_change_24h, candidate_id))

            self.db.conn.commit()

            logger.debug(f"{symbol}: price={price:.8f}, 24h%={price_change_24h:+.2f}%")

        except Exception as e:
            logger.error(f"Error updating prices for {symbol} (id={candidate_id}): {e}")
            self.db.conn.rollback()

    def run_update_cycle(self):
        """
        Выполнить один цикл обновления цен

        Returns:
            (total_candidates, updated_count, failed_count)
        """
        logger.info("=" * 60)
        logger.info("Starting price update cycle")
        logger.info("=" * 60)

        # Получить ACTIVE кандидатов
        candidates = self.get_active_candidates()

        if not candidates:
            logger.info("No ACTIVE candidates to update")
            return (0, 0, 0)

        # Подготовить список символов
        symbols = [c['pair_symbol'] for c in candidates]

        # Получить цены с Binance
        prices = self.fetch_binance_24h_prices(symbols)

        if not prices:
            logger.error("Failed to fetch prices from Binance")
            return (len(candidates), 0, len(candidates))

        # Обновить БД
        updated = 0
        failed = 0

        for candidate in candidates:
            symbol = candidate['pair_symbol']
            candidate_id = candidate['id']

            if symbol in prices:
                price_data = prices[symbol]
                self.update_candidate_prices(
                    candidate_id,
                    symbol,
                    price_data['price'],
                    price_data['priceChangePercent']
                )
                updated += 1
            else:
                logger.warning(f"{symbol}: Price not found in Binance response")
                failed += 1

        # Статистика
        logger.info("=" * 60)
        logger.info(f"Price update complete:")
        logger.info(f"  Total candidates: {len(candidates)}")
        logger.info(f"  Successfully updated: {updated}")
        logger.info(f"  Failed: {failed}")
        logger.info("=" * 60)

        return (len(candidates), updated, failed)

    def run(self):
        """Main runner"""
        logger.info("=" * 60)
        logger.info("Price Updater - Starting")
        logger.info("=" * 60)

        self.connect()

        try:
            total, updated, failed = self.run_update_cycle()

            if failed > 0:
                logger.warning(f"Price update completed with {failed} failures")
                sys.exit(1)
            else:
                logger.info("Price update completed successfully")
                sys.exit(0)

        except Exception as e:
            logger.error(f"Fatal error during price update: {e}")
            sys.exit(1)

        finally:
            if self.db:
                self.db.close()
            logger.info("Price Updater stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Price Updater for Pump Candidates')
    parser.add_argument('--test', action='store_true',
                       help='Test mode - just print what would be updated')
    args = parser.parse_args()

    updater = PriceUpdater()

    try:
        updater.run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
