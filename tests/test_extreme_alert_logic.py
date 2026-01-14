#!/usr/bin/env python3
"""
Test Extreme Alert Logic
Simulates a 'Double EXTREME' scenario by inserting fake signals into the DB,
runs the monitor, and verifies it finds them.
"""

import sys
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import logging

# Add parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DATABASE
from daemons.extreme_alert_monitor import ExtremeAlertMonitor

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TEST_SYMBOL = 'TESTEXTREME'

def setup_test_data():
    """Insert fake EXTREME signals for SPOT and FUTURES"""
    conn = psycopg2.connect(**DATABASE)
    conn.autocommit = True
    cur = conn.cursor()

    # Get a valid trading_pair_id to satisfy FK constraint
    cur.execute("SELECT id FROM trading_pairs LIMIT 1")
    result = cur.fetchone()
    if not result:
        logger.error("No trading pairs found in DB! Cannot run test.")
        sys.exit(1)
    
    valid_id = result['id']

    # Clean up old test data
    cur.execute("DELETE FROM pump.raw_signals WHERE pair_symbol = %s", (TEST_SYMBOL,))
    
    # Create a 4h candle timestamp (e.g., closest 4h interval)
    now = datetime.now()
    candle_time = now.replace(minute=0, second=0, microsecond=0)
    
    logger.info(f"Inserting test signals for {TEST_SYMBOL} at {candle_time} (using real ID {valid_id})...")

    # Insert SPOT EXTREME
    cur.execute("""
        INSERT INTO pump.raw_signals (
            trading_pair_id, pair_symbol, signal_timestamp, detected_at, 
            signal_type, volume, baseline_7d, spike_ratio_7d, signal_strength, price_at_signal, detector_version
        ) VALUES (
            %s, %s, %s, NOW(), 
            'SPOT', 1000000, 10000, 100.0, 'EXTREME', 1.0, 'TEST'
        )
    """, (valid_id, TEST_SYMBOL, candle_time))

    # Insert FUTURES EXTREME (same timestamp)
    cur.execute("""
        INSERT INTO pump.raw_signals (
            trading_pair_id, pair_symbol, signal_timestamp, detected_at, 
            signal_type, volume, baseline_7d, spike_ratio_7d, signal_strength, price_at_signal, detector_version
        ) VALUES (
            %s, %s, %s, NOW(), 
            'FUTURES', 5000000, 50000, 100.0, 'EXTREME', 1.0, 'TEST'
        )
    """, (valid_id, TEST_SYMBOL, candle_time))

    conn.close()
    logger.info("Test data inserted.")

def cleanup_test_data():
    """Remove test data"""
    conn = psycopg2.connect(**DATABASE)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DELETE FROM pump.raw_signals WHERE pair_symbol = %s", (TEST_SYMBOL,))
    conn.close()
    logger.info("Test data cleaned up.")

def run_test():
    try:
        setup_test_data()
        
        logger.info("Running ExtremeAlertMonitor in dry-run mode...")
        # Run with dry_run=True so we don't spam Telegram, but we see the log output
        monitor = ExtremeAlertMonitor(lookback_minutes=60, dry_run=True)
        monitor.connect()
        
        # Manually call find method to verify
        signals = monitor.find_double_extreme_signals()
        
        found = False
        for sig in signals:
            if sig['pair_symbol'] == TEST_SYMBOL:
                found = True
                logger.info(f"SUCCESS: Found test symbol {TEST_SYMBOL} with double extreme signals!")
                logger.info(f"  Spot spike: {sig['spot_spike']}x")
                logger.info(f"  Futures spike: {sig['futures_spike']}x")
                
                # Try sending alert (dry run)
                monitor.send_alert(sig)
                break
        
        if not found:
            logger.error(f"FAILURE: Did not find {TEST_SYMBOL} signals!")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Test failed: {e}")
        sys.exit(1)
    finally:
        cleanup_test_data()

if __name__ == "__main__":
    run_test()
