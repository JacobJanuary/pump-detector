# База Данных Pump Detection System - Схема и Описание

## Обзор

Система использует PostgreSQL базу данных `fox_crypto_new` со специальной схемой `pump` для хранения всех данных о pump-сигналах. Система также использует таблицы из схемы `public` для получения исходных данных о свечах и торговых парах.

## Схемы

### Схема `pump`
Основная схема для системы детекции пампов. Содержит все таблицы для сигналов, трекинга, подтверждений и scoring.

### Схема `public`
Общая схема с исходными данными о рынке (свечи, торговые пары, биржи).

---

## Таблицы Схемы `pump`

### 1. `pump.signals` - Основная таблица сигналов

**Назначение**: Хранит все обнаруженные pump-сигналы с их метриками и статусом.

**Количество записей**: 751 сигнал

#### Структура таблицы:

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | bigint | PRIMARY KEY, уникальный идентификатор сигнала |
| `trading_pair_id` | bigint | FK → `public.trading_pairs.id` |
| `pair_symbol` | text | Символ пары (например, BTCUSDT) |
| `signal_timestamp` | timestamp with time zone | Время свечи, на которой обнаружен всплеск |
| `detected_at` | timestamp with time zone | Время обнаружения сигнала системой |
| `futures_volume` | numeric | Объем на свече-сигнале (quote asset) |
| `futures_baseline_7d` | numeric | 7-дневный базовый средний объем |
| `futures_baseline_14d` | numeric | 14-дневный базовый средний объем |
| `futures_baseline_30d` | numeric | 30-дневный базовый средний объем |
| `futures_spike_ratio_7d` | numeric | Spike ratio относительно 7d baseline |
| `futures_spike_ratio_14d` | numeric | Spike ratio относительно 14d baseline |
| `futures_spike_ratio_30d` | numeric | Spike ratio относительно 30d baseline |
| `signal_strength` | text | Классификация: EXTREME/STRONG/MEDIUM/WEAK |
| `initial_confidence` | integer | Начальный уровень уверенности (0-100) |
| `status` | text | Текущий статус сигнала |
| `max_price_increase` | numeric | Максимальный рост цены после сигнала (%) |
| `pump_realized` | boolean | Флаг: был ли реализован памп (≥10% рост) |
| `has_spot_sync` | boolean | Есть ли синхронизация со spot |
| `spot_volume` | numeric | Объем на spot в момент сигнала |
| `spot_spike_ratio_7d` | numeric | Spike ratio на spot относительно 7d |
| `oi_change_pct` | numeric | Изменение Open Interest (%) |
| `created_at` | timestamp with time zone | Время создания записи |
| `updated_at` | timestamp with time zone | Время последнего обновления |

#### Constraints:

```sql
-- Проверка диапазона confidence
CHECK (initial_confidence >= 0 AND initial_confidence <= 100)

-- Проверка допустимых значений signal_strength
CHECK (signal_strength IN ('EXTREME', 'STRONG', 'MEDIUM', 'WEAK'))

-- Проверка допустимых статусов
CHECK (status IN ('DETECTED', 'MONITORING', 'CONFIRMED', 'FAILED', 'EXPIRED'))
```

#### Индексы:

```sql
CREATE INDEX idx_signals_status ON pump.signals(status);
CREATE INDEX idx_signals_timestamp ON pump.signals(signal_timestamp);
CREATE INDEX idx_signals_pair ON pump.signals(pair_symbol);
CREATE INDEX idx_signals_strength ON pump.signals(signal_strength);
```

#### Статусы сигналов:

- **DETECTED**: Только что обнаружен, начальный статус
- **MONITORING**: Активно отслеживается (после 4 часов с момента обнаружения)
- **CONFIRMED**: Памп подтвержден (цена выросла ≥10%)
- **FAILED**: Сигнал не реализовался (истекло 7 дней или просадка >15%)
- **EXPIRED**: Устаревший сигнал

#### Распределение по статусам:

```
DETECTED:    176 сигналов (23.4%)
MONITORING:   82 сигнала (10.9%)
CONFIRMED:   142 сигнала (18.9%)
FAILED:      351 сигнал  (46.7%)
```

---

### 2. `pump.signal_tracking` - История отслеживания сигналов

**Назначение**: Временные ряды данных о ценах и метриках для каждого сигнала.

**Количество записей**: 140 записей

#### Структура таблицы:

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | bigint | PRIMARY KEY |
| `signal_id` | bigint | FK → `pump.signals.id` |
| `check_timestamp` | timestamp with time zone | Время проверки |
| `price` | numeric | Текущая цена |
| `price_change_pct` | numeric | Изменение цены с момента сигнала (%) |
| `volume_24h` | numeric | 24-часовой объем |
| `volume_ratio_vs_baseline` | numeric | Отношение текущего объема к baseline |
| `oi_total` | numeric | Общий Open Interest |
| `oi_change_pct` | numeric | Изменение OI (%) |
| `current_confidence` | integer | Текущий уровень уверенности |
| `status` | text | Статус на момент проверки |
| `tracking_timestamp` | timestamp with time zone | Системное время записи |

**Использование**: Validator daemon добавляет записи каждые 15 минут для активных сигналов (DETECTED/MONITORING).

---

### 3. `pump.signal_confirmations` - Подтверждения сигналов

**Назначение**: Хранит подтверждения различных типов для каждого сигнала.

**Количество записей**: 330 подтверждений

#### Структура таблицы:

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | bigint | PRIMARY KEY |
| `signal_id` | bigint | FK → `pump.signals.id` |
| `confirmation_type` | text | Тип подтверждения |
| `confirmation_timestamp` | timestamp with time zone | Время подтверждения |
| `confidence_increase` | integer | Прирост уверенности от этого подтверждения |
| `data` | jsonb | Дополнительные данные |

#### Типы подтверждений:

- **SPOT_SYNC**: Синхронизация с spot рынком
- **OI_INCREASE**: Рост Open Interest
- **VOLUME_SUSTAINED**: Устойчивый повышенный объем
- **PRICE_PUMP**: Рост цены
- **SOCIAL_ACTIVITY**: Активность в соцсетях (future)

---

### 4. `pump.signal_scores` - Детальный scoring сигналов

**Назначение**: Хранит разбивку confidence score по компонентам.

**Количество записей**: 252 записи

#### Структура таблицы:

| Поле | Тип | Описание |
|------|-----|----------|
| `signal_id` | bigint | PRIMARY KEY, FK → `pump.signals.id` |
| `volume_score` | integer | Очки за объем (0-25) |
| `oi_score` | integer | Очки за OI (0-25) |
| `spot_sync_score` | integer | Очки за синхронизацию со spot (0-20) |
| `confirmation_score` | integer | Очки за подтверждения (0-20) |
| `timing_score` | integer | Очки за время (0-10) |
| `total_score` | integer | Общий score (0-100) |
| `confidence_level` | text | Уровень: EXTREME/HIGH/MEDIUM/LOW |
| `max_price_increase` | numeric | Максимальный рост цены |
| `time_to_pump_hours` | numeric | Время до реализации пампа (часы) |
| `pump_strength` | text | Сила пампа после реализации |
| `validated` | boolean | Флаг валидации |
| `validation_timestamp` | timestamp with time zone | Время валидации |
| `score_details` | jsonb | Детали расчета score |
| `created_at` | timestamp with time zone | Время создания |
| `updated_at` | timestamp with time zone | Время обновления |

#### Формула расчета Total Score:

```
Total Score = Volume Score + OI Score + Spot Sync Score + Confirmation Score + Timing Score

Где:
- Volume Score (0-25):
  * 25 если spike_ratio_7d >= 5.0 (EXTREME)
  * 20 если spike_ratio_7d >= 3.0 (STRONG)
  * 15 если spike_ratio_7d >= 2.0 (MEDIUM)
  * 10 в остальных случаях (WEAK)

- OI Score (0-25):
  * 25 если oi_change_pct >= 50%
  * 20 если oi_change_pct >= 30%
  * 15 если oi_change_pct >= 15%
  * 10 если oi_change_pct >= 5%
  * 0 в остальных случаях

- Spot Sync Score (0-20):
  * 20 если has_spot_sync И spot_spike_ratio_7d >= 2.0
  * 10 если has_spot_sync И spot_spike_ratio_7d >= 1.5
  * 0 в остальных случаях

- Confirmation Score (0-20):
  * MIN(20, количество_подтверждений * 5)

- Timing Score (0-10):
  * 10 если прошло <= 4 часов с обнаружения
  * 7 если прошло <= 12 часов
  * 5 если прошло <= 24 часов
  * 3 если прошло <= 48 часов
  * 0 в остальных случаях
```

---

### 5. Вспомогательные таблицы

#### `pump.oi_tracking`
Отслеживание Open Interest для фьючерсов.

#### `pump.price_alerts`
Настройки алертов для определенных ценовых уровней.

#### `pump.signal_notes`
Заметки и комментарии по сигналам.

#### `pump.backtesting_results`
Результаты бэктестов исторических данных.

#### `pump.calibration_history`
История калибровки параметров системы.

#### `pump.system_config`
Конфигурация системы (интервалы, пороги и т.д.).

---

## Таблицы Схемы `public` (используемые системой)

### 1. `public.candles` - Свечи

**Назначение**: Исторические OHLCV данные для всех торговых пар.

**Используемые поля**:
- `trading_pair_id` - ID торговой пары
- `interval_id` - Интервал свечи (4 = 4 часа)
- `open_time` - Время открытия свечи (milliseconds)
- `close_price` - Цена закрытия
- `high_price` - Максимальная цена
- `low_price` - Минимальная цена
- `quote_asset_volume` - Объем в quote валюте

**Важно**: Система использует только 4-часовые свечи (interval_id = 4) для фьючерсов Binance.

### 2. `public.trading_pairs` - Торговые пары

**Назначение**: Справочник всех торговых пар.

**Используемые поля**:
- `id` - PRIMARY KEY
- `pair_symbol` - Символ пары (BTCUSDT)
- `exchange_id` - ID биржи (1 = Binance)
- `contract_type_id` - Тип контракта (1 = Futures, NULL = Spot)
- `is_active` - Активна ли пара

**Фильтры системы**:
```sql
WHERE exchange_id = 1          -- Только Binance
  AND is_active = true         -- Только активные
  AND contract_type_id = 1     -- Только фьючерсы
```

---

## Связи между таблицами

```
public.trading_pairs
    ↓ (trading_pair_id)
pump.signals ← (signal_id) pump.signal_tracking
    ↓ (signal_id)
pump.signal_confirmations
    ↓ (signal_id)
pump.signal_scores

public.candles → используется для расчетов, но не имеет прямых FK
```

---

## Ключевые SQL-запросы

### 1. Получение активных сигналов с полными данными

```sql
SELECT
    s.*,
    sc.total_score,
    sc.confidence_level,
    COUNT(DISTINCT c.id) as confirmations_count
FROM pump.signals s
LEFT JOIN pump.signal_scores sc ON s.id = sc.signal_id
LEFT JOIN pump.signal_confirmations c ON s.id = c.signal_id
WHERE s.status IN ('DETECTED', 'MONITORING')
GROUP BY s.id, sc.total_score, sc.confidence_level
ORDER BY s.detected_at DESC;
```

### 2. Расчет baseline и spike ratio

```sql
WITH recent_candles AS (
    SELECT
        c.trading_pair_id,
        c.quote_asset_volume as volume,
        -- 7-дневный baseline (42 свечи для 4h интервала)
        AVG(c.quote_asset_volume) OVER (
            PARTITION BY c.trading_pair_id
            ORDER BY c.open_time
            ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING
        ) as baseline_7d
    FROM public.candles c
    INNER JOIN public.trading_pairs tp ON c.trading_pair_id = tp.id
    WHERE tp.exchange_id = 1
      AND tp.contract_type_id = 1
      AND c.interval_id = 4
)
SELECT
    trading_pair_id,
    volume,
    baseline_7d,
    CASE WHEN baseline_7d > 0
         THEN volume / baseline_7d
         ELSE 0
    END as spike_ratio_7d
FROM recent_candles
WHERE baseline_7d IS NOT NULL;
```

### 3. Статистика по сигналам

```sql
SELECT
    signal_strength,
    status,
    COUNT(*) as count,
    AVG(futures_spike_ratio_7d) as avg_spike_ratio,
    AVG(max_price_increase) as avg_price_increase,
    SUM(CASE WHEN pump_realized THEN 1 ELSE 0 END) as pumps_realized
FROM pump.signals
GROUP BY signal_strength, status
ORDER BY signal_strength, status;
```

---

## Индексная стратегия

### Критичные индексы для производительности:

1. **По статусу** - для быстрого получения активных сигналов
2. **По времени** - для фильтрации по временным диапазонам
3. **По паре** - для поиска по конкретным токенам
4. **Составные индексы** для частых JOIN-запросов

### Рекомендуемые дополнительные индексы:

```sql
-- Для validator daemon (частый запрос по статусу + времени)
CREATE INDEX idx_signals_status_detected_at
ON pump.signals(status, detected_at);

-- Для поиска по spike_ratio
CREATE INDEX idx_signals_spike_ratio_7d
ON pump.signals(futures_spike_ratio_7d DESC);

-- Для spot-futures analyzer
CREATE INDEX idx_signals_has_spot_sync
ON pump.signals(has_spot_sync)
WHERE status IN ('DETECTED', 'MONITORING');
```

---

## Очистка и архивирование

### Политика хранения данных:

1. **pump.signals**: Хранятся бессрочно (архив)
2. **pump.signal_tracking**: Хранятся 30 дней (ежедневная очистка через cron)
3. **pump.signal_confirmations**: Хранятся бессрочно
4. **pump.signal_scores**: Хранятся бессрочно

### Cron задача для очистки:

```bash
# Ежедневно в 4:00 удаляем старые tracking записи
0 4 * * * psql -d fox_crypto_new -c "DELETE FROM pump.signal_tracking WHERE check_timestamp < NOW() - INTERVAL '30 days';"
```

---

## Бэкапы

### Ежедневный бэкап схемы pump:

```bash
# В 5:00 каждое утро
0 5 * * * pg_dump -d fox_crypto_new -n pump \
  -f /home/elcrypto/pump_detector/backups/pump_$(date +\%Y\%m\%d).sql
```

### Восстановление:

```bash
psql -d fox_crypto_new < /home/elcrypto/pump_detector/backups/pump_YYYYMMDD.sql
```

---

## Проверка целостности данных

### SQL для проверки консистентности:

```sql
-- Проверка: все ли сигналы имеют valid spike ratios
SELECT COUNT(*) as invalid_spikes
FROM pump.signals
WHERE futures_spike_ratio_7d < 1.5  -- Минимальный порог
   OR futures_spike_ratio_7d IS NULL;

-- Проверка: есть ли сигналы без scores
SELECT COUNT(*) as signals_without_scores
FROM pump.signals s
LEFT JOIN pump.signal_scores sc ON s.id = sc.signal_id
WHERE sc.signal_id IS NULL;

-- Проверка: правильность статусов
SELECT status, COUNT(*) as count
FROM pump.signals
WHERE status NOT IN ('DETECTED', 'MONITORING', 'CONFIRMED', 'FAILED', 'EXPIRED')
GROUP BY status;
```

---

**Последнее обновление**: 2025-11-07
**Версия**: 1.0
**Всего таблиц в схеме pump**: 10
**Всего записей signals**: 751
