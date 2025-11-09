#!/usr/bin/env python3
"""
Quick test for Telegram alerts
"""

import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from engine.telegram_alerts import TelegramAlerter

def test_telegram():
    """Test Telegram bot connection and send test message"""

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

    print("="*60)
    print("Telegram Bot Test")
    print("="*60)

    if not bot_token:
        print("❌ TELEGRAM_BOT_TOKEN not set!")
        print("\nSet it with:")
        print('  export TELEGRAM_BOT_TOKEN="your_token_here"')
        return False

    if not chat_id:
        print("❌ TELEGRAM_CHAT_ID not set!")
        print("\nSet it with:")
        print('  export TELEGRAM_CHAT_ID="your_chat_id_here"')
        return False

    print(f"✅ Bot Token: {bot_token[:10]}...{bot_token[-5:]}")
    print(f"✅ Chat ID: {chat_id}")
    print()

    # Create alerter
    alerter = TelegramAlerter(bot_token, chat_id)

    # Test connection
    print("Testing bot connection...")
    if not alerter.test_connection():
        print("❌ Bot connection failed!")
        print("\nCheck:")
        print("  1. Token is correct")
        print("  2. Bot is not blocked")
        return False

    print("✅ Bot connected successfully!")
    print()

    # Send test alert
    print("Sending test alert...")
    test_candidate = {
        'pair_symbol': 'TESTUSDT',
        'confidence': 'HIGH',
        'score': 95.5,
        'pattern_type': 'EXTREME_PRECURSOR',
        'total_signals': 20,
        'extreme_signals': 8,
        'critical_window_signals': 6,
        'eta_hours': 48
    }

    if alerter.send_candidate_alert(test_candidate):
        print("✅ Test alert sent successfully!")
        print("\nCheck your Telegram for the message!")
        print("="*60)
        return True
    else:
        print("❌ Failed to send alert!")
        print("\nCheck:")
        print("  1. You sent START to the bot")
        print("  2. Chat ID is correct")
        print("="*60)
        return False

if __name__ == "__main__":
    success = test_telegram()
    sys.exit(0 if success else 1)
