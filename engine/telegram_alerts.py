"""
Telegram Alert System for Pump Detection V2.0
Sends notifications for actionable pump candidates
"""

import requests
import logging
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class TelegramAlerter:
    """
    Telegram alerter for pump candidates

    Sends formatted messages to Telegram for HIGH confidence actionable candidates
    """

    def __init__(self, bot_token: str, chat_id: str):
        """
        Args:
            bot_token: Telegram bot token
            chat_id: Telegram chat/channel ID to send alerts to
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

        if not bot_token or not chat_id:
            logger.warning("Telegram bot_token or chat_id not configured. Alerts disabled.")
            self.enabled = False
        else:
            self.enabled = True
            logger.info(f"Telegram Alerter initialized for chat {chat_id}")

    def format_candidate_message(self, candidate: Dict) -> str:
        """
        Форматировать кандидата в Telegram сообщение

        Args:
            candidate: Dict с данными кандидата из pump.pump_candidates

        Returns:
            Formatted HTML message
        """
        symbol = candidate['pair_symbol']
        confidence = candidate['confidence']
        score = candidate['score']
        pattern = candidate['pattern_type']
        total_signals = candidate['total_signals']
        extreme_signals = candidate['extreme_signals']
        critical_window = candidate['critical_window_signals']
        eta_hours = candidate['eta_hours']

        # Эмодзи для confidence
        if confidence == 'HIGH':
            conf_emoji = '🔴'
        elif confidence == 'MEDIUM':
            conf_emoji = '🟡'
        else:
            conf_emoji = '🟢'

        # Эмодзи для pattern
        if pattern == 'EXTREME_PRECURSOR':
            pattern_emoji = '⚡️'
        elif pattern == 'STRONG_PRECURSOR':
            pattern_emoji = '💥'
        else:
            pattern_emoji = '📊'

        message = f"""
{conf_emoji} <b>PUMP ALERT: {symbol}</b>

{pattern_emoji} <b>Pattern:</b> {pattern}
📈 <b>Confidence:</b> {confidence} ({score:.1f}/100)

<b>Signals:</b>
├ Total: {total_signals}
├ EXTREME: {extreme_signals}
└ Critical window (48-72h): {critical_window}

⏰ <b>ETA:</b> ~{eta_hours}h

🎯 <b>ACTIONABLE</b>
"""
        return message.strip()

    def send_message(self, message: str, parse_mode: str = 'HTML') -> bool:
        """
        Отправить сообщение в Telegram

        Args:
            message: Текст сообщения
            parse_mode: Режим парсинга (HTML, Markdown, None)

        Returns:
            True если успешно, False если ошибка
        """
        if not self.enabled:
            logger.debug("Telegram alerts disabled, skipping message")
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }

            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 200:
                logger.info(f"Telegram message sent successfully to {self.chat_id}")
                return True
            else:
                logger.error(f"Telegram API error: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False

    def send_candidate_alert(self, candidate: Dict) -> bool:
        """
        Отправить алерт для кандидата

        Args:
            candidate: Dict с данными кандидата

        Returns:
            True если успешно отправлено
        """
        try:
            message = self.format_candidate_message(candidate)
            return self.send_message(message)
        except Exception as e:
            logger.error(f"Error sending candidate alert: {e}")
            return False

    def send_summary_alert(self, actionable_count: int, total_analyzed: int,
                          top_candidates: list) -> bool:
        """
        Отправить summary сообщение о цикле анализа

        Args:
            actionable_count: Количество actionable кандидатов
            total_analyzed: Общее количество проанализированных символов
            top_candidates: Список топ кандидатов (первые 3-5)

        Returns:
            True если успешно
        """
        if not self.enabled:
            return False

        try:
            message = f"""
📊 <b>Analysis Cycle Complete</b>

Analyzed: {total_analyzed} symbols
Actionable: {actionable_count} pump candidates

"""
            if top_candidates:
                message += "<b>Top Candidates:</b>\n"
                for i, c in enumerate(top_candidates[:5], 1):
                    message += f"{i}. {c['pair_symbol']} - {c['score']:.1f}/100 - {c['pattern_type']}\n"

            return self.send_message(message)

        except Exception as e:
            logger.error(f"Error sending summary alert: {e}")
            return False

    def test_connection(self) -> bool:
        """
        Тест подключения к Telegram API

        Returns:
            True если бот работает
        """
        if not self.enabled:
            logger.warning("Telegram not configured")
            return False

        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                bot_info = response.json()
                logger.info(f"Telegram bot connected: @{bot_info['result']['username']}")
                return True
            else:
                logger.error(f"Telegram bot test failed: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error testing Telegram connection: {e}")
            return False
