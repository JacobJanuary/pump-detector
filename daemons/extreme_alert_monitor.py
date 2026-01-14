#!/usr/bin/env python3
"""
Extreme Alert Monitor - Double EXTREME Signal Detection
Monitors for simultaneous EXTREME volume spikes on both SPOT and FUTURES.
Run this IMMEDIATELY after detector_daemon_v2.py.
"""

import logging
import signal
import sys
import os
import argparse
from datetime import datetime
from typing import Dict, List, Optional
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
        logging.FileHandler('/home/elcrypto/pump_detector/logs/extreme_alert_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ExtremeAlertMonitor:
    """
    Monitor for Double EXTREME signals (Spot + Futures on same candle).
    """

    def __init__(self, lookback_minutes=60, dry_run=False):
        self.db_config = DATABASE
        self.db = None
        self.running = True
        self.lookback_minutes = lookback_minutes
        self.dry_run = dry_run

        # Telegram alerter
        telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        self.telegram = TelegramAlerter(telegram_bot_token, telegram_chat_id)

        # Signal handling
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
            logger.info("Extreme Alert Monitor initialized")
        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            raise

    def find_double_extreme_signals(self) -> List[Dict]:
        """
        Find pairs with EXTREME signals on both Spot and Futures
        for the same candle timestamp, detected recently.
        """
        try:
            query = """
                SELECT
                    s_spot.pair_symbol,
                    s_spot.signal_timestamp,
                    s_spot.spike_ratio_7d as spot_spike,
                    s_futures.spike_ratio_7d as futures_spike,
                    s_spot.volume as spot_volume,
                    s_futures.volume as futures_volume,
                    s_spot.detected_at as spot_detected_at,
                    s_futures.detected_at as futures_detected_at
                FROM pump.raw_signals s_spot
                JOIN pump.raw_signals s_futures 
                    ON s_spot.pair_symbol = s_futures.pair_symbol 
                    AND s_spot.signal_timestamp = s_futures.signal_timestamp
                WHERE s_spot.signal_type = 'SPOT'
                  AND s_futures.signal_type = 'FUTURES'
                  AND s_spot.signal_strength = 'EXTREME'
                  AND s_futures.signal_strength = 'EXTREME'
                  -- Check if either signal was detected recently
                  AND (
                      s_spot.detected_at >= NOW() - INTERVAL '%s minutes'
                      OR
                      s_futures.detected_at >= NOW() - INTERVAL '%s minutes'
                  )
            """
            
            with self.db.conn.cursor() as cur:
                # Execute with lookback parameter twice
                cur.execute(query, (self.lookback_minutes, self.lookback_minutes))
                results = cur.fetchall()

            logger.info(f"Found {len(results)} potential Double EXTREME signals")
            return results

        except Exception as e:
            logger.error(f"Error searching for signals: {e}")
            return []

    def is_alert_already_sent(self, symbol: str, timestamp: datetime) -> bool:
        """
        Check if we already sent an alert for this symbol and candle time.
        Uses a simple file-based check or DB check. 
        For now, let's assume if it was detected > lookback, valid.
        But since we filter by detected_at >= NOW - interval, we implicitly handle duplication
        assuming the script runs once per cycle.
        
        To be safe, we can check if there's already a candidate created recently or just rely on the short lookback.
        """
        # The SQL query filters for "recently detected". 
        # Since the daemon runs every 4 hours and this runs immediately after,
        # we shouldn't get duplicates unless the script is run multiple times manually.
        return False

    def send_alert(self, signal_data: Dict):
        """Send Telegram alert"""
        try:
            symbol = signal_data['pair_symbol']
            candle_time = signal_data['signal_timestamp'].strftime('%Y-%m-%d %H:%M UTC')
            
            message = f"""
🔥🔥🔥 DOUBLE EXTREME DETECTED! 🔥🔥🔥

🚀 **{symbol}** shows MASSIVE volume spikes on both markets!

⏰ Candle: {candle_time}

📊 Volume Spikes (7-day base):
  • SPOT:    **{signal_data['spot_spike']:.2f}x** 🟢
  • FUTURES: **{signal_data['futures_spike']:.2f}x** 🔵

💰 Volume:
  • Spot: ${signal_data['spot_volume']:,.0f}
  • Futures: ${signal_data['futures_volume']:,.0f}

⚠️ High probability of volatility!
"""
            if self.dry_run:
                logger.info(f"[DRY RUN] Would send alert for {symbol}:\n{message}")
            else:
                if self.telegram.send_message(message):
                    logger.info(f"✅ Alert sent for {symbol}")
                else:
                    logger.error(f"❌ Failed to send alert for {symbol}")

        except Exception as e:
            logger.error(f"Error sending alert: {e}")

    def run(self):
        """Main execution"""
        logger.info("="*60)
        logger.info(f"Extreme Alert Monitor (Lookback: {self.lookback_minutes}m)")
        logger.info("="*60)

        self.connect()

        try:
            signals = self.find_double_extreme_signals()
            
            if not signals:
                logger.info("No new Double EXTREME signals found.")
            
            for sig in signals:
                self.send_alert(sig)

        except Exception as e:
            logger.error(f"Fatal error: {e}")
            sys.exit(1)
        finally:
            if self.db:
                self.db.close()
            logger.info("Monitor finished")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Extreme Alert Monitor')
    parser.add_argument('--lookback', type=int, default=60,
                       help='Lookback in minutes for new signals (default: 60)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Do not send actual Telegram messages')
    args = parser.parse_args()

    monitor = ExtremeAlertMonitor(lookback_minutes=args.lookback, dry_run=args.dry_run)
    monitor.run()
