"""
Pump Detection Engine V2.0
Основан на анализе 136 реальных pump событий

Ключевые находки из исследования:
- 43.4% pumps are actionable (59 из 136)
- Actionable pumps имеют 16.44 сигналов vs 4.43 у non-actionable (3.7x)
- Критическое окно 48-72h: 4.68 vs 0.58 сигналов (8x разница)
- EXTREME сигналы (≥5.0x): 57.6% vs 24.7% presence rate
- Минимум 10 сигналов за 7 дней для надежного детектирования
"""

from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from collections import Counter
import logging

logger = logging.getLogger(__name__)


class PumpDetectionEngine:
    """Движок детектирования pump на основе сигналов"""

    def __init__(self, db_helper):
        """
        Args:
            db_helper: PumpDatabaseHelper instance
        """
        self.db = db_helper

        # Загружаем конфигурацию из БД
        self.min_signal_count = self.db.get_config_value('min_signal_count', 10)
        self.high_conf_threshold = self.db.get_config_value('high_confidence_threshold', 75.0)
        self.medium_conf_threshold = self.db.get_config_value('medium_confidence_threshold', 50.0)

        # Пороги spike ratio для категорий силы сигнала
        self.extreme_threshold = self.db.get_config_value('extreme_spike_threshold', 5.0)
        self.very_strong_threshold = self.db.get_config_value('very_strong_spike_threshold', 3.0)
        self.strong_threshold = self.db.get_config_value('strong_spike_threshold', 2.0)

        # Критическое окно (часы до pump)
        self.critical_window_start = self.db.get_config_value('critical_window_start', 48)
        self.critical_window_end = self.db.get_config_value('critical_window_end', 72)
        self.critical_window_min_signals = self.db.get_config_value('critical_window_min_signals', 4)

        # Веса для многофакторной оценки (на основе исследования)
        self.weight_signal_count = self.db.get_config_value('weight_signal_count', 0.40)
        self.weight_time_distribution = self.db.get_config_value('weight_time_distribution', 0.25)
        self.weight_signal_strength = self.db.get_config_value('weight_signal_strength', 0.20)
        self.weight_escalation = self.db.get_config_value('weight_escalation', 0.10)
        self.weight_spot_futures = self.db.get_config_value('weight_spot_futures_balance', 0.05)

        logger.info("PumpDetectionEngine V2.0 initialized")

    def analyze_symbol(self, symbol: str, current_time: datetime = None) -> Optional[Dict]:
        """
        Анализировать символ на наличие pump паттерна

        Args:
            symbol: Символ торговой пары (например, 'BTCUSDT')
            current_time: Текущее время (для тестирования на исторических данных)

        Returns:
            Dict с результатами анализа или None если нет pump паттерна
            {
                'pair_symbol': str,
                'confidence': str (HIGH/MEDIUM/LOW),
                'score': float (0-100),
                'pattern_type': str,
                'total_signals': int,
                'extreme_signals': int,
                'critical_window_signals': int,
                'eta_hours': int,
                'is_actionable': bool,
                'signals': List[Dict],  # все сигналы для этого кандидата
                'analysis_details': Dict  # детальная информация для snapshot
            }
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # Получаем сигналы за последние 7 дней
        signals = self.db.get_signals_last_n_days(symbol, days=7, current_time=current_time)

        if len(signals) < self.min_signal_count:
            logger.debug(f"{symbol}: Not enough signals ({len(signals)} < {self.min_signal_count})")
            return None

        # Выполняем многофакторный анализ
        analysis = self._multi_factor_analysis(signals, current_time)

        # Проверяем, есть ли pump паттерн
        if analysis['score'] < self.medium_conf_threshold:
            logger.debug(f"{symbol}: Score too low ({analysis['score']:.2f})")
            return None

        # Определяем уровень уверенности
        if analysis['score'] >= self.high_conf_threshold:
            confidence = 'HIGH'
        elif analysis['score'] >= self.medium_conf_threshold:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'

        # Определяем тип паттерна
        pattern_type = self._determine_pattern_type(analysis)

        # Оцениваем ETA (estimated time to pump)
        eta_hours = self._estimate_eta(analysis, current_time)

        # Actionable если HIGH confidence и достаточно сигналов в критическом окне
        is_actionable = (
            confidence == 'HIGH' and
            analysis['critical_window_signals'] >= self.critical_window_min_signals
        )

        # Определяем фазу пампа (для отфильтровывания post-pump сигналов)
        pump_phase, phase_metrics = self.calculate_pump_phase(symbol, signals, current_time)

        result = {
            'pair_symbol': symbol,
            'confidence': confidence,
            'score': round(analysis['score'], 2),
            'pattern_type': pattern_type,
            'total_signals': len(signals),
            'extreme_signals': analysis['extreme_count'],
            'critical_window_signals': analysis['critical_window_signals'],
            'eta_hours': eta_hours,
            'is_actionable': is_actionable,
            'pump_phase': pump_phase,
            'price_change_from_first': phase_metrics['price_change_from_first'],
            'price_change_24h': phase_metrics['price_change_24h'],
            'hours_since_last_pump': phase_metrics['hours_since_last_pump'],
            'signals': signals,
            'analysis_details': analysis  # для сохранения в analysis_snapshots
        }

        logger.info(
            f"{symbol}: PUMP DETECTED - Confidence={confidence}, Score={result['score']:.2f}, "
            f"Pattern={pattern_type}, ETA={eta_hours}h, Actionable={is_actionable}, "
            f"Phase={pump_phase}"
        )

        return result

    def _multi_factor_analysis(self, signals: List[Dict], current_time: datetime) -> Dict:
        """
        Многофакторный анализ сигналов

        Факторы (веса на основе исследования):
        1. Количество сигналов (40%) - actionable имеют 3.7x больше
        2. Временное распределение (25%) - критическое окно 48-72h
        3. Сила сигналов (20%) - presence rate EXTREME сигналов
        4. Эскалация (10%) - нарастание активности
        5. SPOT/FUTURES баланс (5%) - оба типа сигналов

        Returns:
            Dict с детальной информацией по каждому фактору
        """
        # Подготовка данных
        signal_strengths = [s['signal_strength'] for s in signals]
        signal_times = [s['signal_timestamp'] for s in signals]
        signal_types = [s['signal_type'] for s in signals]

        # Считаем категории сигналов
        extreme_count = signal_strengths.count('EXTREME')
        very_strong_count = signal_strengths.count('VERY_STRONG')
        strong_count = signal_strengths.count('STRONG')

        # ФАКТОР 1: Количество сигналов (40%)
        # Research: actionable имеют avg 16.44 signals
        signal_count_score = min(100, (len(signals) / 16.44) * 100)

        # ФАКТОР 2: Временное распределение (25%)
        # Ключевая находка: критическое окно 48-72h имеет 8x больше сигналов
        time_dist_score, critical_window_signals = self._analyze_time_distribution(
            signal_times, current_time
        )

        # ФАКТОР 3: Сила сигналов (20%)
        # Research: EXTREME signals presence rate 57.6% vs 24.7%
        strength_score = self._analyze_signal_strength(
            extreme_count, very_strong_count, strong_count, len(signals)
        )

        # ФАКТОР 4: Эскалация (10%)
        # Нарастание активности во времени
        escalation_score = self._analyze_escalation(signal_times, current_time)

        # ФАКТОР 5: SPOT/FUTURES баланс (5%)
        # Оба типа сигналов указывают на согласованность
        balance_score = self._analyze_spot_futures_balance(signal_types)

        # Итоговый взвешенный score
        total_score = (
            signal_count_score * self.weight_signal_count +
            time_dist_score * self.weight_time_distribution +
            strength_score * self.weight_signal_strength +
            escalation_score * self.weight_escalation +
            balance_score * self.weight_spot_futures
        )

        return {
            'score': total_score,
            'total_signals': len(signals),
            'extreme_count': extreme_count,
            'very_strong_count': very_strong_count,
            'strong_count': strong_count,
            'critical_window_signals': critical_window_signals,
            'factor_scores': {
                'signal_count': round(signal_count_score, 2),
                'time_distribution': round(time_dist_score, 2),
                'signal_strength': round(strength_score, 2),
                'escalation': round(escalation_score, 2),
                'spot_futures_balance': round(balance_score, 2)
            },
            'signal_type_distribution': dict(Counter(signal_types)),
            'strength_distribution': dict(Counter(signal_strengths))
        }

    def _analyze_time_distribution(self, signal_times: List[datetime],
                                   current_time: datetime) -> Tuple[float, int]:
        """
        Анализ временного распределения сигналов

        Ключевая находка: критическое окно 48-72h показывает 8x больше сигналов

        Returns:
            (score 0-100, количество сигналов в критическом окне)
        """
        # Разбиваем на временные окна (часы назад от current_time)
        windows = {
            '0-24h': 0,
            '24-48h': 0,
            '48-72h': 0,  # критическое окно!
            '72-96h': 0,
            '96-120h': 0,
            '120+h': 0
        }

        for sig_time in signal_times:
            hours_ago = (current_time - sig_time).total_seconds() / 3600

            if hours_ago <= 24:
                windows['0-24h'] += 1
            elif hours_ago <= 48:
                windows['24-48h'] += 1
            elif hours_ago <= 72:
                windows['48-72h'] += 1  # критическое!
            elif hours_ago <= 96:
                windows['72-96h'] += 1
            elif hours_ago <= 120:
                windows['96-120h'] += 1
            else:
                windows['120+h'] += 1

        critical_window_signals = windows['48-72h']

        # Оценка: высокий score если много сигналов в критическом окне
        # Research: actionable имеют avg 4.68 в критическом окне
        if critical_window_signals >= 5:
            score = 100
        elif critical_window_signals >= 4:
            score = 90
        elif critical_window_signals >= 3:
            score = 70
        elif critical_window_signals >= 2:
            score = 50
        elif critical_window_signals >= 1:
            score = 30
        else:
            # Даже если нет в критическом окне, смотрим на другие недавние
            recent_signals = windows['0-24h'] + windows['24-48h']
            score = min(40, recent_signals * 5)

        return score, critical_window_signals

    def _analyze_signal_strength(self, extreme_count: int, very_strong_count: int,
                                 strong_count: int, total_signals: int) -> float:
        """
        Анализ силы сигналов

        Research:
        - EXTREME signals presence rate: 57.6% (actionable) vs 24.7% (non-actionable)
        - Минимум 2 EXTREME сигнала для HIGH confidence

        Returns:
            Score 0-100
        """
        if total_signals == 0:
            return 0

        # Взвешенный score силы сигналов
        # EXTREME = 3 points, VERY_STRONG = 2 points, STRONG = 1 point
        weighted_strength = (extreme_count * 3) + (very_strong_count * 2) + strong_count
        max_possible = total_signals * 3  # если все EXTREME

        strength_ratio = weighted_strength / max_possible

        # Базовый score
        score = strength_ratio * 100

        # Бонус за наличие EXTREME сигналов
        if extreme_count >= 3:
            score = min(100, score + 20)
        elif extreme_count >= 2:
            score = min(100, score + 10)

        return score

    def _analyze_escalation(self, signal_times: List[datetime],
                           current_time: datetime) -> float:
        """
        Анализ эскалации (нарастания активности)

        Если сигналы учащаются со временем - это признак приближающегося pump

        Returns:
            Score 0-100
        """
        if len(signal_times) < 3:
            return 50  # недостаточно данных

        # Сортируем по времени (от старых к новым)
        sorted_times = sorted(signal_times)

        # Разбиваем на 2 половины
        mid_point = len(sorted_times) // 2
        first_half = sorted_times[:mid_point]
        second_half = sorted_times[mid_point:]

        # Считаем плотность (signals per hour)
        if len(first_half) > 0:
            first_duration = (first_half[-1] - first_half[0]).total_seconds() / 3600
            first_density = len(first_half) / max(first_duration, 1)
        else:
            first_density = 0

        if len(second_half) > 0:
            second_duration = (second_half[-1] - second_half[0]).total_seconds() / 3600
            second_density = len(second_half) / max(second_duration, 1)
        else:
            second_density = 0

        # Эскалация = вторая половина плотнее первой
        if first_density > 0:
            escalation_ratio = second_density / first_density
        else:
            escalation_ratio = 1.0

        # Оценка
        if escalation_ratio >= 2.0:
            score = 100  # сильная эскалация
        elif escalation_ratio >= 1.5:
            score = 80
        elif escalation_ratio >= 1.0:
            score = 60
        else:
            score = 40  # активность снижается

        return score

    def _analyze_spot_futures_balance(self, signal_types: List[str]) -> float:
        """
        Анализ баланса SPOT/FUTURES сигналов

        Наличие обоих типов указывает на согласованность паттерна

        Returns:
            Score 0-100
        """
        type_counts = Counter(signal_types)
        spot_count = type_counts.get('SPOT', 0)
        futures_count = type_counts.get('FUTURES', 0)

        total = spot_count + futures_count
        if total == 0:
            return 0

        # Идеальный баланс = оба типа присутствуют
        if spot_count > 0 and futures_count > 0:
            # Считаем, насколько сбалансированы
            ratio = min(spot_count, futures_count) / max(spot_count, futures_count)
            # ratio близкий к 1.0 = идеальный баланс
            score = 50 + (ratio * 50)
        else:
            # Только один тип - ниже score
            score = 30

        return score

    def _determine_pattern_type(self, analysis: Dict) -> str:
        """
        Определить тип pump паттерна на основе анализа

        Типы паттернов:
        - EXTREME_PRECURSOR: экстремальные сигналы + критическое окно
        - STRONG_PRECURSOR: сильные сигналы + хорошее распределение
        - MEDIUM_PRECURSOR: средняя сила, но много сигналов
        - EARLY_PATTERN: ранние признаки
        """
        extreme_count = analysis['extreme_count']
        critical_window = analysis['critical_window_signals']
        score = analysis['score']

        if extreme_count >= 2 and critical_window >= 4:
            return 'EXTREME_PRECURSOR'
        elif extreme_count >= 1 and critical_window >= 3:
            return 'STRONG_PRECURSOR'
        elif score >= 60 and analysis['total_signals'] >= 12:
            return 'MEDIUM_PRECURSOR'
        else:
            return 'EARLY_PATTERN'

    def _estimate_eta(self, analysis: Dict, current_time: datetime) -> Optional[int]:
        """
        Оценить ETA (estimated time to pump) в часах

        На основе критического окна 48-72h

        Returns:
            Часы до предполагаемого pump или None если не можем оценить
        """
        critical_window = analysis['critical_window_signals']

        # Если много сигналов в критическом окне - pump близко
        if critical_window >= 5:
            return 48  # ~2 дня
        elif critical_window >= 3:
            return 60  # ~2.5 дня
        elif critical_window >= 1:
            return 72  # ~3 дня
        else:
            # Смотрим на общий score
            if analysis['score'] >= 70:
                return 96  # ~4 дня
            else:
                return None  # слишком рано для оценки

    def calculate_pump_phase(self, symbol: str, signals: List[Dict],
                            current_time: datetime = None) -> Tuple[str, Dict]:
        """
        Определяет фазу пампа для отфильтровывания post-pump сигналов

        Фазы:
        - EARLY_SIGNAL: Ранний предвестник пампа (умеренный рост, нет недавнего пампа)
        - POST_PUMP_COOLING: Памп уже состоялся, остывание (большой рост + недавний памп)
        - SECOND_WAVE_POTENTIAL: Возможна вторая волна (давний памп + новая волна роста)

        Args:
            symbol: Символ торговой пары
            signals: Список сигналов с price_at_signal
            current_time: Текущее время (для расчетов)

        Returns:
            (pump_phase: str, metrics: Dict)
            metrics содержит:
                - price_change_from_first: % изменения от начала пампа (или первого сигнала)
                - price_change_24h: % изменения за последние 24ч
                - hours_since_last_pump: часы с последнего пампа или None
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        # Получаем информацию о последнем пампе из БД
        pump_info = self.db.get_last_pump_info(symbol, current_time)
        hours_since_last_pump = pump_info['hours_since_pump'] if pump_info else None

        # Получаем цены из сигналов
        prices_with_times = [(s['signal_timestamp'], s['price_at_signal'])
                            for s in signals if s.get('price_at_signal')]

        if not prices_with_times:
            # Нет ценовых данных - возвращаем EARLY_SIGNAL по умолчанию
            return 'EARLY_SIGNAL', {
                'price_change_from_first': 0.0,
                'price_change_24h': 0.0,
                'hours_since_last_pump': hours_since_last_pump
            }

        # Сортируем по времени (от старых к новым)
        prices_with_times.sort(key=lambda x: x[0])

        # Текущая цена (конвертируем в float для расчетов)
        current_price = float(prices_with_times[-1][1])

        # Определяем базовую цену для сравнения:
        # 1. Если есть pump event - используем start_price из него
        # 2. Иначе используем первый сигнал из списка
        if pump_info and pump_info['start_price']:
            base_price = float(pump_info['start_price'])
            logger.debug(f"{symbol}: Using pump start_price={base_price} as base")
        else:
            base_price = float(prices_with_times[0][1])
            logger.debug(f"{symbol}: Using first signal price={base_price} as base")

        # % изменения от базовой цены (start_price пампа или первого сигнала)
        if base_price and base_price > 0:
            price_change_from_first = ((current_price - base_price) / base_price) * 100
        else:
            price_change_from_first = 0.0

        # % изменения за последние 24ч
        price_24h_ago = None
        cutoff_24h = current_time - timedelta(hours=24)

        for timestamp, price in reversed(prices_with_times):
            if timestamp <= cutoff_24h:
                price_24h_ago = float(price)
                break

        if price_24h_ago and price_24h_ago > 0:
            price_change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100
        else:
            # Если нет данных за 24ч назад, используем самые ранние доступные
            price_change_24h = price_change_from_first

        # Определяем фазу пампа
        pump_phase = self._classify_pump_phase(
            price_change_from_first,
            price_change_24h,
            hours_since_last_pump
        )

        metrics = {
            'price_change_from_first': round(price_change_from_first, 2),
            'price_change_24h': round(price_change_24h, 2),
            'hours_since_last_pump': hours_since_last_pump
        }

        logger.info(
            f"{symbol}: Pump Phase={pump_phase}, Price↑={metrics['price_change_from_first']:.2f}%, "
            f"24h={metrics['price_change_24h']:.2f}%, Last Pump={hours_since_last_pump}h"
        )

        return pump_phase, metrics

    def _classify_pump_phase(self, price_from_first: float, price_24h: float,
                            hours_since_pump: Optional[int]) -> str:
        """
        Классифицирует фазу пампа на основе метрик

        Args:
            price_from_first: % изменения цены от начала пампа
            price_24h: % изменения цены за последние 24ч
            hours_since_pump: часы с последнего пампа или None

        Returns:
            Фаза пампа: EARLY_SIGNAL, POST_PUMP_COOLING, или SECOND_WAVE_POTENTIAL
        """
        # POST-PUMP: значительный рост от начала пампа + недавний памп + стабильная/падающая цена
        # Порог снижен с 50% до 15% чтобы ловить реальные post-pump кейсы
        if (price_from_first > 15 and
            hours_since_pump is not None and
            hours_since_pump < 72 and
            price_24h < 5):
            return 'POST_PUMP_COOLING'

        # SECOND WAVE: давний памп + новая волна роста
        if (hours_since_pump is not None and
            hours_since_pump > 168 and
            price_24h > 10):
            return 'SECOND_WAVE_POTENTIAL'

        # EARLY SIGNAL: умеренный рост + нет недавнего пампа
        return 'EARLY_SIGNAL'
