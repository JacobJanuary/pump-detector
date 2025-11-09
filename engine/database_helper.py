"""
Database Helper для Pump Detection System V2.0
Упрощенная работа с БД для нового детектора
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class PumpDatabaseHelper:
    """Helper класс для работы с pump schema V2.0"""

    def __init__(self, db_config: dict):
        self.db_config = db_config
        self.conn = None

    def connect(self):
        """Подключение к БД"""
        try:
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

    def close(self):
        """Закрыть соединение"""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")

    def get_config_value(self, key: str, default=None):
        """Получить значение из pump.detector_config"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT value, value_type
                    FROM pump.detector_config
                    WHERE key = %s
                """, (key,))

                result = cur.fetchone()
                if not result:
                    return default

                value, value_type = result['value'], result['value_type']

                # Конвертация типа
                if value_type == 'integer':
                    return int(value)
                elif value_type == 'float':
                    return float(value)
                elif value_type == 'boolean':
                    return value.lower() in ('true', '1', 'yes')
                else:
                    return value
        except Exception as e:
            logger.error(f"Error getting config {key}: {e}")
            return default

    def get_signals_last_n_days(self, symbol: str, days: int = 7,
                                 current_time: datetime = None) -> List[Dict]:
        """
        Получить сигналы за последние N дней для символа

        Args:
            symbol: Символ торговой пары (например, 'BTCUSDT')
            days: Количество дней назад
            current_time: Текущее время (для тестирования на исторических данных)

        Returns:
            List of signal dicts с полями:
                id, signal_type, signal_timestamp, spike_ratio_7d,
                signal_strength, volume, price_at_signal
        """
        if current_time is None:
            current_time = datetime.now()

        lookback_time = current_time - timedelta(days=days)

        try:
            with self.conn.cursor() as cur:
                query = """
                    SELECT
                        id,
                        signal_type,
                        signal_timestamp,
                        spike_ratio_7d,
                        signal_strength,
                        volume,
                        price_at_signal,
                        baseline_7d,
                        baseline_14d,
                        baseline_30d
                    FROM pump.raw_signals
                    WHERE pair_symbol = %s
                      AND signal_timestamp >= %s
                      AND signal_timestamp <= %s
                    ORDER BY signal_timestamp DESC
                """

                cur.execute(query, (symbol, lookback_time, current_time))
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Error getting signals for {symbol}: {e}")
            return []

    def insert_raw_signal(self, signal_data: Dict) -> Optional[int]:
        """
        Вставить сырой сигнал в pump.raw_signals

        Args:
            signal_data: Dict с полями:
                trading_pair_id, pair_symbol, signal_type, signal_timestamp,
                volume, price_at_signal, baseline_7d, spike_ratio_7d,
                signal_strength, [baseline_14d, baseline_30d, spike_ratio_14d, spike_ratio_30d]

        Returns:
            ID вставленной записи или None при ошибке
        """
        try:
            with self.conn.cursor() as cur:
                query = """
                    INSERT INTO pump.raw_signals (
                        trading_pair_id, pair_symbol, signal_type,
                        signal_timestamp, volume, price_at_signal,
                        baseline_7d, baseline_14d, baseline_30d,
                        spike_ratio_7d, spike_ratio_14d, spike_ratio_30d,
                        signal_strength, detector_version
                    ) VALUES (
                        %(trading_pair_id)s, %(pair_symbol)s, %(signal_type)s,
                        %(signal_timestamp)s, %(volume)s, %(price_at_signal)s,
                        %(baseline_7d)s, %(baseline_14d)s, %(baseline_30d)s,
                        %(spike_ratio_7d)s, %(spike_ratio_14d)s, %(spike_ratio_30d)s,
                        %(signal_strength)s, %(detector_version)s
                    )
                    RETURNING id
                """

                # Добавляем дефолтные значения если не указаны
                signal_data.setdefault('detector_version', '2.0')
                signal_data.setdefault('baseline_14d', None)
                signal_data.setdefault('baseline_30d', None)
                signal_data.setdefault('spike_ratio_14d', None)
                signal_data.setdefault('spike_ratio_30d', None)

                cur.execute(query, signal_data)
                result = cur.fetchone()
                self.conn.commit()

                return result['id'] if result else None
        except Exception as e:
            logger.error(f"Error inserting signal: {e}")
            self.conn.rollback()
            return None

    def create_or_update_candidate(self, candidate_data: Dict) -> Optional[int]:
        """
        Создать или обновить pump candidate

        Args:
            candidate_data: Dict с полями:
                pair_symbol, trading_pair_id, confidence, score, pattern_type,
                total_signals, extreme_signals, critical_window_signals,
                eta_hours, is_actionable, pump_phase, price_change_from_first,
                price_change_24h, hours_since_last_pump, [status]

        Returns:
            ID кандидата или None при ошибке
        """
        try:
            with self.conn.cursor() as cur:
                # Проверяем, есть ли уже ACTIVE кандидат для этого символа
                cur.execute("""
                    SELECT id FROM pump.pump_candidates
                    WHERE pair_symbol = %s AND status = 'ACTIVE'
                    ORDER BY first_detected_at DESC
                    LIMIT 1
                """, (candidate_data['pair_symbol'],))

                existing = cur.fetchone()

                if existing:
                    # Обновляем существующий
                    query = """
                        UPDATE pump.pump_candidates SET
                            last_updated_at = NOW(),
                            confidence = %(confidence)s,
                            score = %(score)s,
                            pattern_type = %(pattern_type)s,
                            total_signals = %(total_signals)s,
                            extreme_signals = %(extreme_signals)s,
                            critical_window_signals = %(critical_window_signals)s,
                            eta_hours = %(eta_hours)s,
                            is_actionable = %(is_actionable)s,
                            pump_phase = %(pump_phase)s,
                            price_change_from_first = %(price_change_from_first)s,
                            price_change_24h = %(price_change_24h)s,
                            hours_since_last_pump = %(hours_since_last_pump)s
                        WHERE id = %(id)s
                        RETURNING id
                    """
                    candidate_data['id'] = existing['id']
                else:
                    # Создаем новый
                    query = """
                        INSERT INTO pump.pump_candidates (
                            pair_symbol, trading_pair_id, first_detected_at,
                            confidence, score, pattern_type,
                            total_signals, extreme_signals, critical_window_signals,
                            eta_hours, status, is_actionable,
                            pump_phase, price_change_from_first, price_change_24h, hours_since_last_pump
                        ) VALUES (
                            %(pair_symbol)s, %(trading_pair_id)s, NOW(),
                            %(confidence)s, %(score)s, %(pattern_type)s,
                            %(total_signals)s, %(extreme_signals)s, %(critical_window_signals)s,
                            %(eta_hours)s, %(status)s, %(is_actionable)s,
                            %(pump_phase)s, %(price_change_from_first)s, %(price_change_24h)s, %(hours_since_last_pump)s
                        )
                        RETURNING id
                    """
                    candidate_data.setdefault('status', 'ACTIVE')

                cur.execute(query, candidate_data)
                result = cur.fetchone()
                self.conn.commit()

                return result['id'] if result else None
        except Exception as e:
            logger.error(f"Error creating/updating candidate: {e}")
            self.conn.rollback()
            return None

    def save_analysis_snapshot(self, candidate_id: int, analysis_data: dict):
        """Сохранить snapshot анализа в JSONB"""
        try:
            with self.conn.cursor() as cur:
                query = """
                    INSERT INTO pump.analysis_snapshots (
                        candidate_id, analysis_data
                    ) VALUES (%s, %s)
                """

                import json
                cur.execute(query, (candidate_id, json.dumps(analysis_data)))
                self.conn.commit()
        except Exception as e:
            logger.error(f"Error saving analysis snapshot: {e}")
            self.conn.rollback()

    def get_active_candidates(self) -> List[Dict]:
        """Получить все активные кандидаты"""
        try:
            with self.conn.cursor() as cur:
                query = """
                    SELECT * FROM pump.pump_candidates
                    WHERE status = 'ACTIVE'
                    ORDER BY score DESC
                """
                cur.execute(query)
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Error getting active candidates: {e}")
            return []

    def get_hours_since_last_pump(self, symbol: str, current_time: datetime = None) -> Optional[int]:
        """
        Получить количество часов с последнего пампа для символа

        Args:
            symbol: Символ торговой пары (например, 'BTCUSDT')
            current_time: Текущее время (для расчета разницы)

        Returns:
            Количество часов с последнего пампа или None если пампа не было
        """
        if current_time is None:
            current_time = datetime.now()

        try:
            with self.conn.cursor() as cur:
                query = """
                    SELECT pump_start
                    FROM pump.known_pump_events
                    WHERE pair_symbol = %s
                      AND pump_start <= %s
                    ORDER BY pump_start DESC
                    LIMIT 1
                """
                cur.execute(query, (symbol, current_time))
                result = cur.fetchone()

                if not result:
                    return None

                pump_start = result['pump_start']
                time_diff = current_time - pump_start
                hours = int(time_diff.total_seconds() / 3600)

                return hours
        except Exception as e:
            logger.error(f"Error getting last pump for {symbol}: {e}")
            return None

    def get_last_pump_info(self, symbol: str, current_time: datetime = None) -> Optional[Dict]:
        """
        Получить информацию о последнем пампе для символа

        Args:
            symbol: Символ торговой пары (например, 'BTCUSDT')
            current_time: Текущее время (для фильтрации)

        Returns:
            Dict с полями pump_start, start_price, hours_since_pump или None если пампа не было
        """
        if current_time is None:
            current_time = datetime.now()

        try:
            with self.conn.cursor() as cur:
                query = """
                    SELECT pump_start, start_price
                    FROM pump.known_pump_events
                    WHERE pair_symbol = %s
                      AND pump_start <= %s
                    ORDER BY pump_start DESC
                    LIMIT 1
                """
                cur.execute(query, (symbol, current_time))
                result = cur.fetchone()

                if not result:
                    return None

                pump_start = result['pump_start']
                start_price = float(result['start_price']) if result['start_price'] else None
                time_diff = current_time - pump_start
                hours = int(time_diff.total_seconds() / 3600)

                return {
                    'pump_start': pump_start,
                    'start_price': start_price,
                    'hours_since_pump': hours
                }
        except Exception as e:
            logger.error(f"Error getting last pump info for {symbol}: {e}")
            return None
