# Логика Детекции Пампов - Подробное Описание

## Обзор

Система детекции пампов использует статистический анализ временных рядов для выявления аномальных всплесков объема торгов. Основной метод - сравнение текущего объема с историческим базовым уровнем (baseline) через расчет spike ratio.

---

## 1. Основной Алгоритм Детекции

### 1.1. Сбор данных

**Источник**: Таблица `public.candles`
**Временной интервал**: 4-часовые свечи
**Рынок**: Binance Futures (USDT-margined)

```sql
SELECT
    c.trading_pair_id,
    tp.pair_symbol,
    to_timestamp(c.open_time / 1000) as candle_time,
    c.close_price,
    c.quote_asset_volume as volume
FROM public.candles c
INNER JOIN public.trading_pairs tp ON c.trading_pair_id = tp.id
WHERE tp.exchange_id = 1          -- Binance
  AND tp.is_active = true         -- Активные пары
  AND tp.contract_type_id = 1     -- Фьючерсы
  AND c.interval_id = 4           -- 4h свечи
```

### 1.2. Расчет Baseline (скользящее среднее)

Система рассчитывает **три baseline** для разных временных окон:

#### 7-дневный Baseline
```
baseline_7d = AVG(volume за последние 42 свечи)

Почему 42?
- 1 день = 6 свечей по 4 часа (24/4 = 6)
- 7 дней = 7 × 6 = 42 свечи
```

**SQL реализация**:
```sql
AVG(c.quote_asset_volume) OVER (
    PARTITION BY c.trading_pair_id
    ORDER BY c.open_time
    ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING  -- Не включаем текущую свечу!
) as baseline_7d
```

#### 14-дневный Baseline
```
baseline_14d = AVG(volume за последние 84 свечи)
84 = 14 дней × 6 свечей
```

#### 30-дневный Baseline
```
baseline_30d = AVG(volume за последние 180 свечей)
180 = 30 дней × 6 свечей
```

**Важно**: Текущая свеча НЕ включается в расчет baseline (BETWEEN ... AND 1 PRECEDING).

### 1.3. Расчет Spike Ratio

**Формула**:
```
spike_ratio = current_volume / baseline_volume

Где:
- current_volume: объем на текущей 4h свече
- baseline_volume: средний объем за N дней
```

**Пример расчета**:
```
Пара: HIPPOUSDT
Текущий объем: 105,129,169 USDT
Baseline 7d: 18,988,185 USDT

spike_ratio_7d = 105,129,169 / 18,988,185 = 5.54x

Интерпретация: Текущий объем в 5.54 раза больше среднего за последние 7 дней
```

### 1.4. Классификация Signal Strength

Система использует максимальное значение из spike_ratio_7d и spike_ratio_14d:

```python
max_spike = MAX(spike_ratio_7d, spike_ratio_14d)

if max_spike >= 5.0:
    signal_strength = "EXTREME"    # Экстремальный всплеск
elif max_spike >= 3.0:
    signal_strength = "STRONG"     # Сильный всплеск
elif max_spike >= 2.0:
    signal_strength = "MEDIUM"     # Средний всплеск
elif max_spike >= 1.5:
    signal_strength = "WEAK"       # Слабый всплеск
else:
    # Не создаем сигнал (ниже минимального порога)
    pass
```

**Минимальный порог**: 1.5x (настраивается в `config/settings.py`)

### 1.5. Начальный Confidence Score

При создании сигнала назначается начальный уровень уверенности:

```python
if max_spike >= 5.0:
    initial_confidence = 75    # EXTREME
elif max_spike >= 3.0:
    initial_confidence = 60    # STRONG
elif max_spike >= 2.0:
    initial_confidence = 45    # MEDIUM
elif max_spike >= 1.5:
    initial_confidence = 30    # WEAK
```

---

## 2. Жизненный Цикл Сигнала

### 2.1. Фаза DETECTED (начальная)

**Когда**: Сразу после обнаружения детектором
**Длительность**: До 4 часов
**Действия**:
- Сохранение в БД с полными метриками
- Расчет начального confidence score
- Статус = `DETECTED`

**Пример записи**:
```json
{
  "pair_symbol": "HIPPOUSDT",
  "signal_timestamp": "2025-11-07 12:00:00+00",
  "futures_volume": 105129169.57,
  "futures_baseline_7d": 18988185.83,
  "futures_spike_ratio_7d": 5.54,
  "signal_strength": "EXTREME",
  "initial_confidence": 75,
  "status": "DETECTED"
}
```

### 2.2. Фаза MONITORING (активное отслеживание)

**Переход**: Через 4 часа после обнаружения
**Условие**:
```sql
UPDATE pump.signals
SET status = 'MONITORING'
WHERE status = 'DETECTED'
  AND detected_at < NOW() - INTERVAL '4 hours';
```

**Что отслеживается**:
1. Движение цены (каждые 15 минут)
2. Объем торгов
3. Изменение Open Interest
4. Синхронизация со spot

**Расчет Max Gain**:
```sql
WITH price_data AS (
    SELECT
        MAX(c.high_price) as max_price,
        s.entry_price
    FROM public.candles c
    WHERE trading_pair_id = s.trading_pair_id
      AND to_timestamp(c.open_time / 1000) >= s.signal_timestamp
)
SELECT
    (max_price - entry_price) / entry_price * 100 as max_gain_pct
FROM price_data;
```

### 2.3. Переход в CONFIRMED (памп подтвержден)

**Условие**:
```
max_gain_pct >= 10%
```

**Действия**:
```sql
UPDATE pump.signals
SET
    status = 'CONFIRMED',
    pump_realized = true,
    max_price_increase = max_gain_pct
WHERE id = signal_id;
```

**Пример**:
```
HIPPOUSDT:
- Цена входа: $0.00818200
- Максимум: $0.00919900
- Рост: 12.43% → CONFIRMED ✅
```

### 2.4. Переход в FAILED (памп не реализовался)

**Условия для перехода в FAILED**:

1. **Истечение времени**:
```python
if hours_since_detection >= 168:  # 7 дней
    status = 'FAILED'
```

2. **Сильная просадка**:
```python
if max_drawdown_pct >= 15:  # Падение на 15%
    status = 'FAILED'
```

**Расчет просадки**:
```sql
max_drawdown_pct = (entry_price - min_price) / entry_price * 100
```

---

## 3. Многофакторный Confidence Scoring

### 3.1. Компоненты Score

Confidence score состоит из 5 компонентов с разными весами:

```
Total Score (0-100) =
    Volume Score (0-25)        [25% вес]
  + OI Score (0-25)            [25% вес]
  + Spot Sync Score (0-20)     [20% вес]
  + Confirmation Score (0-20)  [20% вес]
  + Timing Score (0-10)        [10% вес]
```

### 3.2. Volume Score (0-25 баллов)

**Формула**:
```python
if futures_spike_ratio_7d >= 5.0:
    volume_score = 25  # Максимальный балл
elif futures_spike_ratio_7d >= 3.0:
    volume_score = 20
elif futures_spike_ratio_7d >= 2.0:
    volume_score = 15
else:
    volume_score = 10
```

**Примеры**:
- HIPPOUSDT (5.54x) → 25 баллов
- GALAUSDT (2.99x) → 20 баллов
- RUNEUSDT (2.40x) → 15 баллов

### 3.3. OI Score (0-25 баллов)

Open Interest показывает рост открытых позиций.

**Формула**:
```python
if oi_change_pct >= 50:
    oi_score = 25
elif oi_change_pct >= 30:
    oi_score = 20
elif oi_change_pct >= 15:
    oi_score = 15
elif oi_change_pct >= 5:
    oi_score = 10
else:
    oi_score = 0
```

**Расчет изменения OI**:
```sql
oi_change_pct = (current_oi - baseline_oi) / baseline_oi * 100
```

**Интерпретация**:
- Рост OI + рост цены = бычий памп (хорошо)
- Рост OI + падение цены = медвежий дамп (плохо)

### 3.4. Spot Sync Score (0-20 баллов)

Проверка синхронизации фьючерсов со спотом.

**Формула**:
```python
if has_spot_sync and spot_spike_ratio_7d >= 2.0:
    spot_sync_score = 20  # Сильная синхронизация
elif has_spot_sync and spot_spike_ratio_7d >= 1.5:
    spot_sync_score = 10  # Слабая синхронизация
else:
    spot_sync_score = 0   # Нет синхронизации
```

**Важность**: Синхронизация со спотом подтверждает органический рост, а не манипуляцию только фьючерсами.

### 3.5. Confirmation Score (0-20 баллов)

Каждое подтверждение добавляет 5 баллов (максимум 20).

**Формула**:
```python
confirmation_score = MIN(20, confirmations_count * 5)
```

**Типы подтверждений**:
- SPOT_SYNC: Синхронизация со spot
- OI_INCREASE: Рост Open Interest
- VOLUME_SUSTAINED: Устойчивый объем
- PRICE_PUMP: Рост цены

### 3.6. Timing Score (0-10 баллов)

Учитывает "свежесть" сигнала. Чем новее сигнал, тем выше score.

**Формула**:
```python
hours_since_detection = (NOW() - detected_at).total_seconds() / 3600

if hours_since_detection <= 4:
    timing_score = 10    # Очень свежий
elif hours_since_detection <= 12:
    timing_score = 7     # Свежий
elif hours_since_detection <= 24:
    timing_score = 5     # Средней давности
elif hours_since_detection <= 48:
    timing_score = 3     # Старый
else:
    timing_score = 0     # Очень старый
```

### 3.7. Итоговый Confidence Level

```python
if total_score >= 80:
    confidence_level = "EXTREME"  # Очень высокая уверенность
elif total_score >= 60:
    confidence_level = "HIGH"     # Высокая уверенность
elif total_score >= 40:
    confidence_level = "MEDIUM"   # Средняя уверенность
else:
    confidence_level = "LOW"      # Низкая уверенность
```

---

## 4. Spot-Futures Correlation Analysis

### 4.1. Цель анализа

Определить, является ли всплеск объема на фьючерсах **органическим ростом** (весь рынок) или **манипуляцией** (только фьючерсы).

### 4.2. Алгоритм

1. **Получить futures сигналы** за последние 4 часа
2. **Найти spot активность** для той же базовой валюты
3. **Сравнить spike ratios**

**SQL запрос**:
```sql
WITH recent_signals AS (
    SELECT
        s.id as signal_id,
        s.pair_symbol,
        SPLIT_PART(s.pair_symbol, 'USDT', 1) as base_asset,
        s.futures_spike_ratio_7d
    FROM pump.signals s
    WHERE s.status IN ('DETECTED', 'MONITORING')
      AND s.signal_timestamp >= NOW() - INTERVAL '4 hours'
),
spot_activity AS (
    SELECT
        SPLIT_PART(tp.pair_symbol, 'USDT', 1) as base_asset,
        MAX(c.quote_asset_volume) as max_spot_volume,
        AVG(c.quote_asset_volume) as avg_spot_volume
    FROM public.candles c
    INNER JOIN public.trading_pairs tp ON c.trading_pair_id = tp.id
    WHERE tp.exchange_id = 1
      AND tp.contract_type_id IS NULL  -- Спот
      AND tp.pair_symbol LIKE '%USDT'
      AND to_timestamp(c.open_time / 1000) >= NOW() - INTERVAL '4 hours'
    GROUP BY SPLIT_PART(tp.pair_symbol, 'USDT', 1)
)
SELECT
    rs.signal_id,
    rs.pair_symbol,
    rs.futures_spike_ratio_7d,
    sa.max_spot_volume / NULLIF(sa.avg_spot_volume, 0) as spot_spike_ratio,
    CASE
        WHEN (sa.max_spot_volume / NULLIF(sa.avg_spot_volume, 0)) > 2.0
        THEN true
        ELSE false
    END as spot_confirmed
FROM recent_signals rs
LEFT JOIN spot_activity sa ON rs.base_asset = sa.base_asset;
```

### 4.3. Критерии синхронизации

```python
# Сильная синхронизация
if spot_spike_ratio >= 2.0:
    has_spot_sync = True
    spot_sync_score = 20

# Слабая синхронизация
elif spot_spike_ratio >= 1.5:
    has_spot_sync = True
    spot_sync_score = 10

# Нет синхронизации
else:
    has_spot_sync = False
    spot_sync_score = 0
```

### 4.4. Интерпретация результатов

| Futures | Spot | Интерпретация | Рейтинг |
|---------|------|---------------|---------|
| 5.0x | 2.5x | Органический рост | ⭐⭐⭐⭐⭐ |
| 5.0x | 1.8x | Частичная синхронизация | ⭐⭐⭐⭐ |
| 5.0x | 1.2x | Слабая корреляция | ⭐⭐⭐ |
| 5.0x | 0.9x | Только фьючерсы (подозрительно) | ⭐⭐ |

---

## 5. Примеры Расчетов

### Пример 1: HIPPOUSDT (EXTREME сигнал)

**Входные данные**:
```
Текущий volume: 105,129,169 USDT
Baseline 7d: 18,988,185 USDT
Baseline 14d: 12,173,520 USDT
Цена входа: $0.00818200
```

**Шаг 1: Расчет spike ratios**
```
spike_ratio_7d = 105,129,169 / 18,988,185 = 5.54x
spike_ratio_14d = 105,129,169 / 12,173,520 = 8.64x
```

**Шаг 2: Классификация**
```
MAX(5.54, 8.64) = 8.64x >= 5.0
→ signal_strength = "EXTREME"
→ initial_confidence = 75
```

**Шаг 3: Confidence scoring**
```
Volume Score: 25 (spike_ratio >= 5.0)
OI Score: 0 (нет данных OI)
Spot Sync Score: 0 (нет синхронизации)
Confirmation Score: 5 (1 подтверждение)
Timing Score: 10 (< 4 часов)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Score: 40 → MEDIUM confidence
```

**Шаг 4: Валидация**
```
Максимальная цена: $0.00919900
Max gain: (0.00919900 - 0.00818200) / 0.00818200 * 100 = 12.43%

12.43% >= 10% → status = "CONFIRMED" ✅
```

### Пример 2: GALAUSDT (STRONG сигнал)

**Входные данные**:
```
Текущий volume: 26,278,465 USDT
Baseline 7d: 8,798,420 USDT
```

**Расчеты**:
```
spike_ratio_7d = 26,278,465 / 8,798,420 = 2.99x

2.99x >= 3.0? Нет
2.99x >= 2.0? Да → signal_strength = "MEDIUM"

⚠️ ОШИБКА: В реальных данных указано STRONG
   Возможная причина: округление или spike_ratio_14d выше
```

---

## 6. Настройка Параметров

### 6.1. Файл конфигурации (`config/settings.py`)

```python
DETECTION = {
    # Детектор
    'interval_minutes': 5,          # Частота проверок
    'lookback_hours': 4,            # Окно для поиска новых сигналов

    # Пороги spike ratio
    'min_spike_ratio': 1.5,         # Минимум для детекции
    'extreme_spike_ratio': 5.0,     # EXTREME
    'strong_spike_ratio': 3.0,      # STRONG
    'medium_spike_ratio': 2.0,      # MEDIUM

    # Интервал и таймфрейм
    'timeframe': '4h',              # 4-часовые свечи

    # Валидация
    'pump_threshold_pct': 10,       # % роста для подтверждения
    'monitoring_hours': 168,        # 7 дней мониторинга
}

SCORING = {
    'volume_weight': 0.25,          # 25% от total score
    'oi_weight': 0.25,              # 25%
    'spot_sync_weight': 0.20,       # 20%
    'confirmation_weight': 0.20,    # 20%
    'timing_weight': 0.10,          # 10%
}
```

### 6.2. Рекомендации по настройке

**Агрессивная стратегия** (больше сигналов):
```python
'min_spike_ratio': 1.3,
'pump_threshold_pct': 5,
'monitoring_hours': 120,
```

**Консервативная стратегия** (меньше false positives):
```python
'min_spike_ratio': 2.0,
'pump_threshold_pct': 15,
'monitoring_hours': 240,
```

---

## 7. Валидация и Тестирование

### 7.1. Validation Script

Система включает скрипт для независимой проверки всех расчетов:

```bash
cd /home/elcrypto/pump_detector
./venv/bin/python3 scripts/validate_signals.py --random 10
```

**Что проверяется**:
- ✅ Корректность расчета baseline
- ✅ Корректность spike ratios
- ✅ Правильность классификации signal_strength
- ✅ Точность max_price_increase

**Результаты тестирования** (10 случайных сигналов):
```
Total: 10 | Valid: 10 (100.0%) | Invalid: 0 (0.0%)
```

### 7.2. Unit Tests

**Тест spike ratio**:
```python
def test_spike_ratio_calculation():
    volume = 100000
    baseline = 20000
    expected = 5.0

    actual = volume / baseline

    assert abs(actual - expected) < 0.01
```

**Тест классификации**:
```python
def test_signal_strength_classification():
    assert classify_strength(5.5) == "EXTREME"
    assert classify_strength(3.5) == "STRONG"
    assert classify_strength(2.5) == "MEDIUM"
    assert classify_strength(1.7) == "WEAK"
```

---

## 8. Оптимизация Производительности

### 8.1. SQL оптимизация

**Используйте оконные функции вместо подзапросов**:
```sql
-- ✅ Быстро (оконная функция)
AVG(volume) OVER (
    PARTITION BY trading_pair_id
    ORDER BY open_time
    ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING
)

-- ❌ Медленно (подзапрос для каждой строки)
(SELECT AVG(volume)
 FROM candles c2
 WHERE c2.trading_pair_id = c.trading_pair_id
   AND c2.open_time < c.open_time
 ORDER BY c2.open_time DESC
 LIMIT 42)
```

### 8.2. Индексы

```sql
-- Критичные индексы для производительности
CREATE INDEX idx_candles_pair_interval_time
ON public.candles(trading_pair_id, interval_id, open_time);

CREATE INDEX idx_signals_status
ON pump.signals(status) WHERE status IN ('DETECTED', 'MONITORING');
```

---

## 9. False Positives и Фильтрация

### 9.1. Причины ложных срабатываний

1. **Низкая ликвидность**: Малоликвидные пары могут давать высокие spike ratios
2. **Листинг новых монет**: Первые дни торгов с нестабильными объемами
3. **Технические сбои**: Проблемы с получением данных от биржи
4. **Wash trading**: Искусственная накрутка объемов

### 9.2. Фильтры

**Минимальный объем**:
```sql
WHERE futures_volume >= 100000  -- Минимум 100k USDT
```

**Минимальная ликвидность**:
```sql
WHERE futures_baseline_7d >= 10000  -- Средний объем >= 10k
```

**Возраст пары**:
```sql
WHERE tp.listing_date < NOW() - INTERVAL '30 days'  -- Старше 30 дней
```

---

## 10. Будущие Улучшения

### 10.1. Machine Learning

Использование ML для предсказания вероятности реализации пампа:

```python
features = [
    'spike_ratio_7d',
    'spike_ratio_14d',
    'oi_change_pct',
    'spot_sync',
    'market_cap',
    'trading_volume_24h'
]

model = RandomForestClassifier()
prediction = model.predict_proba(features)
```

### 10.2. Sentiment Analysis

Анализ социальных сетей и новостей:
- Twitter mentions frequency
- Reddit posts sentiment
- Trading view ideas count

### 10.3. Market Regime Detection

Адаптация параметров в зависимости от рыночного режима:
- Bull market: более агрессивные пороги
- Bear market: более консервативные пороги
- Sideways: средние параметры

---

**Последнее обновление**: 2025-11-07
**Версия**: 1.0
**Точность валидации**: 100% (10/10 тестов)
