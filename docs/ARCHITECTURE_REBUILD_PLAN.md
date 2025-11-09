# PUMP DETECTOR: Полный План Переархитектуры Системы

**Дата**: 2025-11-07
**Статус**: ПРОЕКТИРОВАНИЕ
**Критичность**: 🔴 ВЫСОКАЯ

---

## 📊 АНАЛИЗ СУЩЕСТВУЮЩИХ ДАННЫХ

### Доступные Источники Данных

#### 1. **public.trading_pairs**
```
Binance (exchange_id=1):
- Futures (contract_type_id=1): 500 активных пар
- Spot (contract_type_id=2): 396 активных пар
```

**Ключевые поля**:
- `id` - trading_pair_id (уникальный для каждой пары+тип)
- `pair_symbol` - символ пары (например, FILUSDT)
- `exchange_id` - биржа (1 = Binance)
- `contract_type_id` - тип (1 = Futures, 2 = Spot)
- `is_active` - активность пары
- `is_stablecoin` - стейблкоин или нет

#### 2. **public.candles**
```
FILUSDT данные:
- Futures: 1,395 свечей (4h)
- Spot: 1,396 свечей (4h)
- Period: 2025-03-19 до 2025-11-07
- Avg Volume (Futures): 24.28M USDT
- Avg Volume (Spot): 3.16M USDT
```

**Ключевые поля**:
- `trading_pair_id` - связь с trading_pairs
- `interval_id` - интервал (4 = 4h)
- `open_time` - UNIX timestamp открытия свечи (в миллисекундах!)
- `volume` - объем в базовой валюте
- `quote_asset_volume` - объем в USDT ✅ **ГЛАВНОЕ ПОЛЕ**
- `open_price`, `close_price`, `high_price`, `low_price` - OHLC

#### 3. **public.market_data** (TimescaleDB hypertable)
```
FILUSDT Futures данные:
- Records: 44,331 записей (каждую минуту!)
- Period: 2025-10-08 до 2025-11-07
- Avg OI: 22.66M
- StdDev OI: 4.62M
```

**Ключевые поля**:
- `trading_pair_id` - futures пара
- `capture_time` - timestamp записи (каждую минуту)
- `open_interest` - OI ✅ **ГЛАВНОЕ ПОЛЕ**
- `mark_price` - текущая цена фьючерса
- `volume_quote_24h` - 24h объем в USDT
- `funding_rate` - ставка финансирования

---

## 🎯 АРХИТЕКТУРА НОВОЙ СИСТЕМЫ

### Концепция

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA SOURCES                              │
│  trading_pairs (пары) → candles (объемы) → market_data (OI) │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│              STEP 1: DETECTOR (Каждые 5 мин)                │
│                                                              │
│  1. Выбрать активные пары (is_active=true, has futures+spot)│
│  2. Для futures: проверить 4h candles на spike объема       │
│  3. Рассчитать baseline (7d/14d/30d)                        │
│  4. Если spike_ratio >= threshold:                          │
│     → Получить SPOT данные для той же пары                  │
│     → Получить OI данные из market_data                     │
│     → Сохранить сигнал в pump.signals                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│            STEP 2: VALIDATOR (Каждые 15 мин)                │
│                                                              │
│  1. Выбрать DETECTED/MONITORING сигналы                     │
│  2. Проверить текущую цену (market_data.mark_price)         │
│  3. Рассчитать max_gain, drawdown                           │
│  4. Обновить статус (CONFIRMED/FAILED)                      │
│  5. Записать tracking данные                                │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│          STEP 3: SCORER (Каждые 5 мин после detect)        │
│                                                              │
│  1. Рассчитать Volume Score (spike_ratio)                   │
│  2. Рассчитать OI Score (oi_change_pct)                     │
│  3. Рассчитать Spot Sync Score (spot vs futures spike)      │
│  4. Рассчитать Timing Score (hour_of_day, freshness)        │
│  5. Рассчитать Confirmation Score (confirmations count)     │
│  6. Total Score = weighted sum                              │
│  7. Сохранить в pump.signal_scores                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 ДЕТАЛЬНЫЙ ПЛАН РЕАЛИЗАЦИИ

### ФАЗА 0: Подготовка и Очистка (30 мин)

#### Шаг 0.1: Остановить все демоны
```bash
sudo systemctl stop pump-detector pump-validator pump-spot-futures
```

#### Шаг 0.2: Backup существующих данных
```sql
-- Создать backup схемы pump
pg_dump -d fox_crypto_new -n pump -f /tmp/pump_schema_backup_$(date +%Y%m%d_%H%M%S).sql
```

#### Шаг 0.3: Очистить pump schema
```sql
-- Удалить все данные из таблиц
TRUNCATE TABLE pump.signal_tracking CASCADE;
TRUNCATE TABLE pump.signal_confirmations CASCADE;
TRUNCATE TABLE pump.signal_scores CASCADE;
TRUNCATE TABLE pump.signals CASCADE;

-- Сбросить sequences
ALTER SEQUENCE pump.signals_id_seq RESTART WITH 1;
```

---

### ФАЗА 1: Тестовый Детектор для FILUSDT (3-4 часа)

#### Цель
Создать и протестировать детектор на одной паре (FILUSDT), чтобы убедиться что все данные читаются правильно.

#### Шаг 1.1: Создать тестовый скрипт `test_detector_filusdt.py`

**Что должен делать**:
1. Получить trading_pair_id для FILUSDT Futures (ID: 2169)
2. Получить trading_pair_id для FILUSDT Spot (ID: 4303)
3. Прочитать последние 180 свечей (4h) для futures из `public.candles`
4. Рассчитать baseline (7d = 42 свечи, 14d = 84, 30d = 180)
5. Рассчитать spike_ratio для последней свечи
6. Если spike_ratio >= 1.5:
   - Получить spot данные (последние 180 свечей)
   - Рассчитать spot_spike_ratio
   - Получить OI данные из market_data
   - Рассчитать OI change %
   - Сохранить сигнал в pump.signals со ВСЕМИ полями заполненными

**Поля для заполнения в pump.signals**:
```python
signal_data = {
    # Base info
    'trading_pair_id': futures_pair_id,
    'pair_symbol': 'FILUSDT',
    'signal_timestamp': candle_open_time,  # from latest candle
    'detected_at': NOW(),

    # Futures data
    'futures_volume': latest_candle['quote_asset_volume'],
    'futures_baseline_7d': avg(last_42_candles),
    'futures_baseline_14d': avg(last_84_candles),
    'futures_baseline_30d': avg(last_180_candles),
    'futures_spike_ratio_7d': volume / baseline_7d,
    'futures_spike_ratio_14d': volume / baseline_14d,
    'futures_spike_ratio_30d': volume / baseline_30d,

    # Spot data
    'spot_volume': spot_latest_candle['quote_asset_volume'],
    'spot_baseline_7d': avg(spot_last_42_candles),
    'spot_spike_ratio_7d': spot_volume / spot_baseline_7d,
    'has_spot_sync': (spot_spike_ratio >= 1.5),

    # OI data
    'oi_value': current_oi,  # from market_data latest record
    'oi_change_pct': ((current_oi - avg_oi_4h) / avg_oi_4h) * 100,

    # Classification
    'signal_strength': classify_strength(spike_ratio_7d),
    'initial_confidence': calculate_initial_confidence(),
    'status': 'DETECTED',
    'is_active': True
}
```

**Код**:
```python
#!/usr/bin/env python3
"""
Тестовый детектор для FILUSDT
Цель: Проверить что все источники данных читаются правильно
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import sys

# Constants
FILUSDT_FUTURES_ID = 2169
FILUSDT_SPOT_ID = 4303
INTERVAL_4H = 4

def connect_db():
    """Connect to database"""
    return psycopg2.connect(
        dbname='fox_crypto_new',
        cursor_factory=RealDictCursor
    )

def get_latest_candles(conn, trading_pair_id, limit=180):
    """
    Получить последние N свечей для пары

    Returns: list of dicts with keys:
        - open_time (int milliseconds)
        - quote_asset_volume (Decimal)
        - close_price (Decimal)
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                open_time,
                quote_asset_volume,
                close_price,
                volume as base_volume
            FROM public.candles
            WHERE trading_pair_id = %s
              AND interval_id = %s
            ORDER BY open_time DESC
            LIMIT %s
        """, (trading_pair_id, INTERVAL_4H, limit))

        candles = cur.fetchall()

        # Reverse to get chronological order
        return list(reversed(candles))

def calculate_baseline(candles, num_candles):
    """
    Рассчитать baseline (среднее) за N свечей

    Args:
        candles: list of candles (chronological order, newest last)
        num_candles: количество свечей для расчета (42, 84, 180)

    Returns: float - среднее значение quote_asset_volume
    """
    if len(candles) < num_candles + 1:
        return None

    # Берем N свечей ДО последней (исключаем последнюю свечу)
    baseline_candles = candles[-(num_candles + 1):-1]

    total_volume = sum(float(c['quote_asset_volume']) for c in baseline_candles)
    return total_volume / len(baseline_candles)

def get_current_oi(conn, trading_pair_id):
    """
    Получить текущий OI и средний OI за последние 4 часа

    Returns: dict with:
        - current_oi: текущий OI
        - avg_oi_4h: средний OI за 4 часа (240 минут)
        - oi_change_pct: процент изменения
    """
    with conn.cursor() as cur:
        # Последнее значение OI
        cur.execute("""
            SELECT
                open_interest as current_oi,
                capture_time
            FROM public.market_data
            WHERE trading_pair_id = %s
              AND open_interest > 0
            ORDER BY capture_time DESC
            LIMIT 1
        """, (trading_pair_id,))

        latest = cur.fetchone()
        if not latest:
            return None

        current_oi = float(latest['current_oi'])
        latest_time = latest['capture_time']

        # Средний OI за последние 4 часа (240 записей назад)
        cur.execute("""
            SELECT AVG(open_interest) as avg_oi
            FROM public.market_data
            WHERE trading_pair_id = %s
              AND capture_time <= %s
              AND capture_time >= %s - INTERVAL '4 hours'
              AND open_interest > 0
        """, (trading_pair_id, latest_time, latest_time))

        avg_result = cur.fetchone()
        avg_oi_4h = float(avg_result['avg_oi']) if avg_result['avg_oi'] else current_oi

        # Рассчитать изменение
        oi_change_pct = ((current_oi - avg_oi_4h) / avg_oi_4h) * 100 if avg_oi_4h > 0 else 0

        return {
            'current_oi': current_oi,
            'avg_oi_4h': avg_oi_4h,
            'oi_change_pct': oi_change_pct
        }

def classify_strength(spike_ratio):
    """Classify signal strength based on spike ratio"""
    if spike_ratio >= 5.0:
        return 'EXTREME'
    elif spike_ratio >= 3.0:
        return 'STRONG'
    elif spike_ratio >= 2.0:
        return 'MEDIUM'
    else:
        return 'WEAK'

def calculate_initial_confidence(spike_ratio_7d, spot_spike_ratio, oi_change_pct, has_spot_sync):
    """
    Рассчитать начальную уверенность (0-100)

    Формула:
    - Volume component (0-40): на основе spike_ratio_7d
    - Spot sync (0-30): если spot тоже spike
    - OI component (0-30): если OI растет
    """
    confidence = 0

    # Volume component (0-40)
    if spike_ratio_7d >= 10:
        confidence += 40
    elif spike_ratio_7d >= 5:
        confidence += 35
    elif spike_ratio_7d >= 3:
        confidence += 25
    elif spike_ratio_7d >= 2:
        confidence += 15
    else:
        confidence += 5

    # Spot sync (0-30)
    if has_spot_sync:
        if spot_spike_ratio >= 3:
            confidence += 30
        elif spot_spike_ratio >= 2:
            confidence += 20
        elif spot_spike_ratio >= 1.5:
            confidence += 10

    # OI component (0-30)
    if oi_change_pct >= 20:
        confidence += 30
    elif oi_change_pct >= 10:
        confidence += 20
    elif oi_change_pct >= 5:
        confidence += 10
    elif oi_change_pct > 0:
        confidence += 5

    return min(confidence, 100)

def detect_signal_for_filusdt():
    """Main detection logic for FILUSDT"""

    conn = connect_db()

    try:
        print("="*60)
        print("FILUSDT TEST DETECTOR")
        print("="*60)

        # Step 1: Get Futures candles
        print("\n[1] Получение Futures свечей...")
        futures_candles = get_latest_candles(conn, FILUSDT_FUTURES_ID, limit=180)
        print(f"✓ Получено {len(futures_candles)} свечей")

        if len(futures_candles) < 181:
            print(f"✗ Недостаточно данных (нужно 181, есть {len(futures_candles)})")
            return

        # Latest candle
        latest_candle = futures_candles[-1]
        current_volume = float(latest_candle['quote_asset_volume'])
        candle_time = datetime.fromtimestamp(latest_candle['open_time'] / 1000)

        print(f"  Последняя свеча: {candle_time}")
        print(f"  Volume: {current_volume:,.2f} USDT")

        # Step 2: Calculate baselines
        print("\n[2] Расчет baseline...")
        baseline_7d = calculate_baseline(futures_candles, 42)
        baseline_14d = calculate_baseline(futures_candles, 84)
        baseline_30d = calculate_baseline(futures_candles, 180)

        print(f"  Baseline 7d (42 свечи): {baseline_7d:,.2f} USDT")
        print(f"  Baseline 14d (84 свечи): {baseline_14d:,.2f} USDT")
        print(f"  Baseline 30d (180 свечей): {baseline_30d:,.2f} USDT")

        # Step 3: Calculate spike ratios
        print("\n[3] Расчет spike ratios...")
        spike_ratio_7d = current_volume / baseline_7d if baseline_7d else 0
        spike_ratio_14d = current_volume / baseline_14d if baseline_14d else 0
        spike_ratio_30d = current_volume / baseline_30d if baseline_30d else 0

        print(f"  Spike ratio 7d: {spike_ratio_7d:.2f}x")
        print(f"  Spike ratio 14d: {spike_ratio_14d:.2f}x")
        print(f"  Spike ratio 30d: {spike_ratio_30d:.2f}x")

        # Check threshold
        if spike_ratio_7d < 1.5:
            print(f"\n✗ Spike ratio {spike_ratio_7d:.2f}x < 1.5x threshold")
            print("  Сигнал не создается")
            return

        print(f"\n✓ Spike ratio {spike_ratio_7d:.2f}x >= 1.5x threshold")

        # Step 4: Get Spot data
        print("\n[4] Получение Spot данных...")
        spot_candles = get_latest_candles(conn, FILUSDT_SPOT_ID, limit=180)
        print(f"✓ Получено {len(spot_candles)} spot свечей")

        spot_latest = spot_candles[-1]
        spot_volume = float(spot_latest['quote_asset_volume'])
        spot_baseline_7d = calculate_baseline(spot_candles, 42)
        spot_spike_ratio = spot_volume / spot_baseline_7d if spot_baseline_7d else 0
        has_spot_sync = (spot_spike_ratio >= 1.5)

        print(f"  Spot volume: {spot_volume:,.2f} USDT")
        print(f"  Spot baseline 7d: {spot_baseline_7d:,.2f} USDT")
        print(f"  Spot spike ratio: {spot_spike_ratio:.2f}x")
        print(f"  Has spot sync: {has_spot_sync}")

        # Step 5: Get OI data
        print("\n[5] Получение OI данных...")
        oi_data = get_current_oi(conn, FILUSDT_FUTURES_ID)

        if oi_data:
            print(f"  Current OI: {oi_data['current_oi']:,.2f}")
            print(f"  Avg OI (4h): {oi_data['avg_oi_4h']:,.2f}")
            print(f"  OI change: {oi_data['oi_change_pct']:+.2f}%")
        else:
            print("  ✗ OI данные недоступны")
            oi_data = {'current_oi': None, 'avg_oi_4h': None, 'oi_change_pct': 0}

        # Step 6: Classification
        print("\n[6] Классификация сигнала...")
        signal_strength = classify_strength(spike_ratio_7d)
        initial_confidence = calculate_initial_confidence(
            spike_ratio_7d,
            spot_spike_ratio,
            oi_data['oi_change_pct'],
            has_spot_sync
        )

        print(f"  Signal strength: {signal_strength}")
        print(f"  Initial confidence: {initial_confidence}%")

        # Step 7: Save to database
        print("\n[7] Сохранение сигнала в БД...")

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pump.signals (
                    trading_pair_id,
                    pair_symbol,
                    signal_timestamp,
                    detected_at,
                    futures_volume,
                    futures_baseline_7d,
                    futures_baseline_14d,
                    futures_baseline_30d,
                    futures_spike_ratio_7d,
                    futures_spike_ratio_14d,
                    futures_spike_ratio_30d,
                    spot_volume,
                    spot_baseline_7d,
                    spot_spike_ratio_7d,
                    has_spot_sync,
                    oi_value,
                    oi_change_pct,
                    signal_strength,
                    initial_confidence,
                    status,
                    is_active
                ) VALUES (
                    %s, %s, %s, NOW(),
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s,
                    %s, %s, 'DETECTED', true
                )
                RETURNING id
            """, (
                FILUSDT_FUTURES_ID,
                'FILUSDT',
                candle_time,
                current_volume,
                baseline_7d,
                baseline_14d,
                baseline_30d,
                spike_ratio_7d,
                spike_ratio_14d,
                spike_ratio_30d,
                spot_volume,
                spot_baseline_7d,
                spot_spike_ratio,
                has_spot_sync,
                oi_data['current_oi'],
                oi_data['oi_change_pct'],
                signal_strength,
                initial_confidence
            ))

            signal_id = cur.fetchone()['id']
            conn.commit()

            print(f"✓ Сигнал сохранен с ID: {signal_id}")

        print("\n" + "="*60)
        print("ТЕСТ ЗАВЕРШЕН УСПЕШНО")
        print("="*60)

    except Exception as e:
        print(f"\n✗ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    detect_signal_for_filusdt()
```

#### Шаг 1.2: Запустить тест
```bash
cd /home/elcrypto/pump_detector
./venv/bin/python3 scripts/test_detector_filusdt.py
```

#### Шаг 1.3: Валидация результата
```sql
-- Проверить созданный сигнал
SELECT
    id,
    pair_symbol,
    signal_timestamp,
    futures_spike_ratio_7d,
    spot_spike_ratio_7d,
    has_spot_sync,
    oi_value,
    oi_change_pct,
    signal_strength,
    initial_confidence
FROM pump.signals
ORDER BY detected_at DESC
LIMIT 1;

-- Проверить что ВСЕ поля заполнены
SELECT
    COUNT(*) FILTER (WHERE futures_volume IS NOT NULL) as has_futures_volume,
    COUNT(*) FILTER (WHERE futures_baseline_7d IS NOT NULL) as has_baseline_7d,
    COUNT(*) FILTER (WHERE spot_volume IS NOT NULL) as has_spot_volume,
    COUNT(*) FILTER (WHERE spot_spike_ratio_7d IS NOT NULL) as has_spot_spike,
    COUNT(*) FILTER (WHERE oi_value IS NOT NULL) as has_oi,
    COUNT(*) FILTER (WHERE oi_change_pct IS NOT NULL) as has_oi_change,
    COUNT(*) as total
FROM pump.signals;
```

**Критерий успеха**: ВСЕ поля должны быть заполнены (не NULL) для созданного сигнала.

---

### ФАЗА 2: Полный Детектор для Всех Пар (4-5 часов)

#### Цель
Расширить тестовый детектор на все активные пары Binance.

#### Шаг 2.1: Создать `detector_daemon_v2.py`

**Основные отличия от старой версии**:
1. ✅ Читает пары с `is_active=true`
2. ✅ Проверяет наличие обоих trading_pair_id (futures + spot)
3. ✅ Использует `quote_asset_volume` вместо `volume`
4. ✅ Заполняет OI данные из `market_data`
5. ✅ Заполняет spot данные из spot candles
6. ✅ Правильный расчет baseline (исключая текущую свечу)

**Структура**:
```python
class PumpDetectorV2:
    def __init__(self):
        self.conn = connect_db()
        self.interval_minutes = 5
        self.min_spike_ratio = 1.5

    def get_active_pairs(self):
        """
        Получить активные пары с futures и spot

        Returns: list of dicts:
            - base_symbol: 'FIL'
            - pair_symbol: 'FILUSDT'
            - futures_id: 2169
            - spot_id: 4303
        """

    def detect_for_pair(self, pair_info):
        """
        Детекция для одной пары
        Аналогично test_detector_filusdt.py
        """

    def run_detection_cycle(self):
        """
        Один цикл детекции для всех пар
        """
        pairs = self.get_active_pairs()

        for pair in pairs:
            try:
                self.detect_for_pair(pair)
            except Exception as e:
                logger.error(f"Error detecting {pair['pair_symbol']}: {e}")

    def run(self):
        """Main daemon loop"""
        while True:
            self.run_detection_cycle()
            time.sleep(self.interval_minutes * 60)
```

#### Шаг 2.2: Тестирование на 5-10 парах
```python
# В detector_daemon_v2.py добавить режим тестирования
TEST_PAIRS = ['FILUSDT', 'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']

if os.environ.get('TEST_MODE') == 'true':
    pairs = [p for p in pairs if p['pair_symbol'] in TEST_PAIRS]
```

```bash
TEST_MODE=true ./venv/bin/python3 daemons/detector_daemon_v2.py
```

#### Шаг 2.3: Валидация
```sql
-- Проверить созданные сигналы
SELECT
    pair_symbol,
    signal_strength,
    futures_spike_ratio_7d,
    has_spot_sync,
    oi_change_pct,
    initial_confidence
FROM pump.signals
WHERE detected_at >= NOW() - INTERVAL '1 hour'
ORDER BY futures_spike_ratio_7d DESC;

-- Проверить заполненность полей
SELECT
    pair_symbol,
    CASE WHEN futures_volume IS NULL THEN 'NULL' ELSE 'OK' END as fvolume,
    CASE WHEN spot_volume IS NULL THEN 'NULL' ELSE 'OK' END as svolume,
    CASE WHEN oi_value IS NULL THEN 'NULL' ELSE 'OK' END as oi
FROM pump.signals
WHERE detected_at >= NOW() - INTERVAL '1 hour';
```

---

### ФАЗА 3: Validator с OI Tracking (2-3 часа)

#### Цель
Перепис validator для использования `market_data.mark_price` для отслеживания цены.

#### Шаг 3.1: Создать `validator_daemon_v2.py`

**Изменения**:
1. ✅ Использовать `market_data.mark_price` вместо candles
2. ✅ Отслеживать OI изменения в реальном времени
3. ✅ Записывать tracking данные с OI

**Код**:
```python
def get_current_price_and_oi(self, trading_pair_id):
    """
    Получить текущую цену и OI из market_data

    Returns: dict with:
        - mark_price: текущая цена
        - open_interest: текущий OI
        - capture_time: время записи
    """
    with self.conn.cursor() as cur:
        cur.execute("""
            SELECT
                mark_price,
                open_interest,
                capture_time
            FROM public.market_data
            WHERE trading_pair_id = %s
            ORDER BY capture_time DESC
            LIMIT 1
        """, (trading_pair_id,))

        return cur.fetchone()

def track_signal(self, signal):
    """
    Отследить изменения цены и OI для сигнала
    """
    # Get current data
    current = self.get_current_price_and_oi(signal['trading_pair_id'])

    # Найти entry price (цена на момент signal_timestamp)
    entry_data = self.get_price_at_timestamp(
        signal['trading_pair_id'],
        signal['signal_timestamp']
    )

    entry_price = float(entry_data['mark_price'])
    current_price = float(current['mark_price'])

    # Calculate gains
    price_change_pct = ((current_price - entry_price) / entry_price) * 100

    # Update signal
    # ... (аналогично старой версии)

    # Save tracking data
    self.save_tracking_data(signal['id'], {
        'check_timestamp': current['capture_time'],
        'current_price': current_price,
        'current_gain_pct': price_change_pct,
        'current_oi': current['open_interest'],
        'volume_ratio': calculate_volume_ratio(),
        # ...
    })
```

#### Шаг 3.2: Тестирование
```bash
# Создать тестовый сигнал вручную
# Запустить validator
./venv/bin/python3 daemons/validator_daemon_v2.py
```

#### Шаг 3.3: Валидация
```sql
-- Проверить tracking данные
SELECT
    signal_id,
    check_timestamp,
    current_price,
    current_gain_pct,
    current_oi
FROM pump.signal_tracking
ORDER BY check_timestamp DESC
LIMIT 10;
```

---

### ФАЗА 4: Новая Scoring System (2-3 часа)

#### Цель
Переписать функцию `pump.calculate_confidence_score()` для использования реальных OI и Spot данных.

#### Шаг 4.1: Обновить SQL функцию

**Новая версия**:
```sql
CREATE OR REPLACE FUNCTION pump.calculate_confidence_score_v2(p_signal_id bigint)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_signal RECORD;
    v_volume_score INTEGER := 0;
    v_oi_score INTEGER := 0;
    v_spot_score INTEGER := 0;
    v_confirmation_score INTEGER := 0;
    v_timing_score INTEGER := 0;
    v_total_score INTEGER;
BEGIN
    -- Get signal data
    SELECT * INTO v_signal
    FROM pump.signals
    WHERE id = p_signal_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    -- VOLUME SCORE (0-30 points) - используем 14d spike (strongest predictor)
    IF v_signal.futures_spike_ratio_14d >= 10 THEN
        v_volume_score := 30;
    ELSIF v_signal.futures_spike_ratio_14d >= 7 THEN
        v_volume_score := 25;
    ELSIF v_signal.futures_spike_ratio_14d >= 5 THEN
        v_volume_score := 20;
    ELSIF v_signal.futures_spike_ratio_14d >= 3 THEN
        v_volume_score := 15;
    ELSIF v_signal.futures_spike_ratio_14d >= 2 THEN
        v_volume_score := 10;
    ELSE
        v_volume_score := 5;
    END IF;

    -- OI SCORE (0-15 points) - REAL DATA!
    IF v_signal.oi_change_pct IS NOT NULL THEN
        IF v_signal.oi_change_pct >= 30 THEN
            v_oi_score := 15;
        ELSIF v_signal.oi_change_pct >= 20 THEN
            v_oi_score := 12;
        ELSIF v_signal.oi_change_pct >= 10 THEN
            v_oi_score := 8;
        ELSIF v_signal.oi_change_pct >= 5 THEN
            v_oi_score := 4;
        ELSIF v_signal.oi_change_pct > 0 THEN
            v_oi_score := 2;
        END IF;
    END IF;

    -- SPOT SYNC SCORE (0-15 points) - REAL DATA!
    IF v_signal.has_spot_sync = TRUE AND v_signal.spot_spike_ratio_7d IS NOT NULL THEN
        IF v_signal.spot_spike_ratio_7d >= 5 THEN
            v_spot_score := 15;
        ELSIF v_signal.spot_spike_ratio_7d >= 3 THEN
            v_spot_score := 12;
        ELSIF v_signal.spot_spike_ratio_7d >= 2 THEN
            v_spot_score := 8;
        ELSIF v_signal.spot_spike_ratio_7d >= 1.5 THEN
            v_spot_score := 4;
        END IF;
    END IF;

    -- CONFIRMATION SCORE (0-25 points) - exponential
    SELECT COUNT(*) INTO v_confirmation_score
    FROM pump.signal_confirmations
    WHERE signal_id = p_signal_id;

    CASE
        WHEN v_confirmation_score = 0 THEN v_confirmation_score := 0;
        WHEN v_confirmation_score = 1 THEN v_confirmation_score := 10;
        WHEN v_confirmation_score = 2 THEN v_confirmation_score := 18;
        WHEN v_confirmation_score >= 3 THEN v_confirmation_score := 25;
    END CASE;

    -- TIMING SCORE (0-15 points) - hour of day + freshness
    DECLARE
        v_hour_of_day INTEGER;
        v_hours_since_signal NUMERIC;
    BEGIN
        v_hour_of_day := EXTRACT(HOUR FROM v_signal.signal_timestamp);
        v_hours_since_signal := EXTRACT(EPOCH FROM (NOW() - v_signal.detected_at)) / 3600;

        -- Hour of day bonus (0-10)
        IF v_hour_of_day BETWEEN 4 AND 8 THEN
            v_timing_score := 10;  -- Best hours (4-8 AM UTC)
        ELSIF v_hour_of_day BETWEEN 0 AND 4 THEN
            v_timing_score := 7;
        ELSIF v_hour_of_day BETWEEN 8 AND 12 THEN
            v_timing_score := 5;
        ELSIF v_hour_of_day BETWEEN 12 AND 16 THEN
            v_timing_score := 3;
        ELSE
            v_timing_score := 0;  -- Evening hours (worst)
        END IF;

        -- Freshness bonus (0-5)
        IF v_hours_since_signal < 1 THEN
            v_timing_score := v_timing_score + 5;
        ELSIF v_hours_since_signal < 4 THEN
            v_timing_score := v_timing_score + 3;
        ELSIF v_hours_since_signal < 12 THEN
            v_timing_score := v_timing_score + 1;
        END IF;
    END;

    -- TOTAL SCORE (0-100)
    v_total_score := v_volume_score + v_oi_score + v_spot_score +
                     v_confirmation_score + v_timing_score;

    -- Save detailed scores
    INSERT INTO pump.signal_scores (
        signal_id,
        volume_score,
        oi_score,
        spot_sync_score,
        confirmation_score,
        timing_score,
        total_score,
        confidence_level,
        calculated_at
    ) VALUES (
        p_signal_id,
        v_volume_score,
        v_oi_score,
        v_spot_score,
        v_confirmation_score,
        v_timing_score,
        v_total_score,
        CASE
            WHEN v_total_score >= 80 THEN 'VERY_HIGH'
            WHEN v_total_score >= 60 THEN 'HIGH'
            WHEN v_total_score >= 40 THEN 'MEDIUM'
            WHEN v_total_score >= 20 THEN 'LOW'
            ELSE 'VERY_LOW'
        END,
        NOW()
    )
    ON CONFLICT (signal_id)
    DO UPDATE SET
        volume_score = EXCLUDED.volume_score,
        oi_score = EXCLUDED.oi_score,
        spot_sync_score = EXCLUDED.spot_sync_score,
        confirmation_score = EXCLUDED.confirmation_score,
        timing_score = EXCLUDED.timing_score,
        total_score = EXCLUDED.total_score,
        confidence_level = EXCLUDED.confidence_level,
        calculated_at = NOW();

    RETURN v_total_score;
END;
$$;
```

#### Шаг 4.2: Тестирование
```sql
-- Запустить scoring для всех сигналов
SELECT
    id,
    pair_symbol,
    pump.calculate_confidence_score_v2(id) as score
FROM pump.signals
ORDER BY id DESC
LIMIT 10;

-- Проверить breakdown
SELECT
    s.pair_symbol,
    sc.volume_score,
    sc.oi_score,
    sc.spot_sync_score,
    sc.confirmation_score,
    sc.timing_score,
    sc.total_score,
    sc.confidence_level
FROM pump.signal_scores sc
INNER JOIN pump.signals s ON sc.signal_id = s.id
ORDER BY sc.total_score DESC
LIMIT 10;
```

---

### ФАЗА 5: Integration & Testing (3-4 часа)

#### Цель
Интегрировать все компоненты и провести полное тестирование.

#### Шаг 5.1: Создать новые systemd сервисы

```bash
# Скопировать старые unit files
sudo cp /etc/systemd/system/pump-detector.service \
        /etc/systemd/system/pump-detector-v2.service

# Изменить ExecStart
sudo nano /etc/systemd/system/pump-detector-v2.service
# ExecStart=/home/elcrypto/pump_detector/venv/bin/python3 /home/elcrypto/pump_detector/daemons/detector_daemon_v2.py

# То же для validator
sudo cp /etc/systemd/system/pump-validator.service \
        /etc/systemd/system/pump-validator-v2.service

# Reload systemd
sudo systemctl daemon-reload
```

#### Шаг 5.2: Запустить V2 демоны
```bash
sudo systemctl start pump-detector-v2
sudo systemctl start pump-validator-v2
```

#### Шаг 5.3: Мониторинг логов
```bash
tail -f /home/elcrypto/pump_detector/logs/detector_v2.log
tail -f /home/elcrypto/pump_detector/logs/validator_v2.log
```

#### Шаг 5.4: Полная валидация через 1 час
```sql
-- Проверка 1: Количество сигналов
SELECT
    COUNT(*) as total_signals,
    COUNT(*) FILTER (WHERE detected_at >= NOW() - INTERVAL '1 hour') as last_hour,
    COUNT(DISTINCT pair_symbol) as unique_pairs
FROM pump.signals;

-- Проверка 2: Заполненность полей
SELECT
    'futures_volume' as field,
    COUNT(*) FILTER (WHERE futures_volume IS NOT NULL) as filled,
    COUNT(*) as total,
    ROUND(COUNT(*) FILTER (WHERE futures_volume IS NOT NULL)::numeric / COUNT(*) * 100, 1) as pct
FROM pump.signals
UNION ALL
SELECT 'spot_volume',
       COUNT(*) FILTER (WHERE spot_volume IS NOT NULL),
       COUNT(*),
       ROUND(COUNT(*) FILTER (WHERE spot_volume IS NOT NULL)::numeric / COUNT(*) * 100, 1)
FROM pump.signals
UNION ALL
SELECT 'oi_value',
       COUNT(*) FILTER (WHERE oi_value IS NOT NULL),
       COUNT(*),
       ROUND(COUNT(*) FILTER (WHERE oi_value IS NOT NULL)::numeric / COUNT(*) * 100, 1)
FROM pump.signals
UNION ALL
SELECT 'oi_change_pct',
       COUNT(*) FILTER (WHERE oi_change_pct IS NOT NULL),
       COUNT(*),
       ROUND(COUNT(*) FILTER (WHERE oi_change_pct IS NOT NULL)::numeric / COUNT(*) * 100, 1)
FROM pump.signals;

-- Проверка 3: Scoring
SELECT
    COUNT(*) as signals_with_scores,
    ROUND(AVG(total_score), 1) as avg_score,
    MAX(total_score) as max_score,
    MIN(total_score) as min_score
FROM pump.signal_scores;

-- Проверка 4: Tracking
SELECT
    COUNT(DISTINCT signal_id) as tracked_signals,
    COUNT(*) as total_tracking_records,
    MAX(check_timestamp) as latest_check
FROM pump.signal_tracking;
```

**Критерии успеха**:
- ✅ futures_volume: 100% заполнено
- ✅ spot_volume: 100% заполнено
- ✅ oi_value: 95%+ заполнено (некоторые пары могут не иметь OI)
- ✅ oi_change_pct: 95%+ заполнено
- ✅ Все сигналы имеют scores
- ✅ Tracking данные записываются каждые 15 минут

---

### ФАЗА 6: Переключение на Production (1 час)

#### Шаг 6.1: Остановить старые демоны
```bash
sudo systemctl stop pump-detector
sudo systemctl stop pump-validator
sudo systemctl stop pump-spot-futures
sudo systemctl disable pump-detector
sudo systemctl disable pump-validator
sudo systemctl disable pump-spot-futures
```

#### Шаг 6.2: Переименовать V2 → Production
```bash
# Rename files
sudo mv /etc/systemd/system/pump-detector-v2.service \
        /etc/systemd/system/pump-detector.service

sudo mv /etc/systemd/system/pump-validator-v2.service \
        /etc/systemd/system/pump-validator.service

# Update ExecStart paths (убрать _v2 из имен файлов)
sudo mv daemons/detector_daemon_v2.py daemons/detector_daemon.py
sudo mv daemons/validator_daemon_v2.py daemons/validator_daemon.py

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable pump-detector
sudo systemctl enable pump-validator
sudo systemctl start pump-detector
sudo systemctl start pump-validator
```

#### Шаг 6.3: Обновить crontab
```bash
crontab -e

# Обновить пути к скриптам (если нужно)
```

---

## 📝 CHECKLIST

### Pre-Deployment
- [ ] Backup pump schema
- [ ] Stop all old daemons
- [ ] Clear pump.signals table

### Phase 1: Test FILUSDT
- [ ] Create test_detector_filusdt.py
- [ ] Run test
- [ ] Validate: ALL fields filled
- [ ] Validate: OI data present
- [ ] Validate: Spot data present

### Phase 2: Full Detector
- [ ] Create detector_daemon_v2.py
- [ ] Test on 5 pairs
- [ ] Validate: All pairs detected correctly
- [ ] Validate: All fields filled for all pairs

### Phase 3: Validator
- [ ] Create validator_daemon_v2.py
- [ ] Test signal tracking
- [ ] Validate: Prices updated correctly
- [ ] Validate: OI tracked correctly

### Phase 4: Scoring
- [ ] Update calculate_confidence_score_v2()
- [ ] Test on existing signals
- [ ] Validate: Real OI scores (not random)
- [ ] Validate: Real Spot scores (not random)

### Phase 5: Integration
- [ ] Create systemd services
- [ ] Start V2 daemons
- [ ] Monitor logs (1 hour)
- [ ] Run full validation queries
- [ ] Fix any issues found

### Phase 6: Production
- [ ] Stop old daemons
- [ ] Rename V2 → Production
- [ ] Enable and start new daemons
- [ ] Monitor for 24 hours

---

## ⏱️ TIMELINE

| Фаза | Задача | Время | Кумулятивно |
|------|--------|-------|-------------|
| 0 | Подготовка | 30 мин | 30 мин |
| 1 | Test FILUSDT | 3-4 часа | 4ч |
| 2 | Full Detector | 4-5 часов | 9ч |
| 3 | Validator V2 | 2-3 часа | 12ч |
| 4 | Scoring V2 | 2-3 часа | 15ч |
| 5 | Integration | 3-4 часа | 19ч |
| 6 | Production | 1 час | 20ч |

**Общая оценка**: 19-20 часов работы (2.5 рабочих дня)

---

## 🎯 EXPECTED RESULTS

После завершения переархитектуры:

| Метрика | До | После | Улучшение |
|---------|-----|-------|-----------|
| **OI Data Coverage** | 0% | 95%+ | ✅ +95% |
| **Spot Data Coverage** | 0% | 100% | ✅ +100% |
| **Fields Filled** | ~50% | 100% | ✅ +100% |
| **Scoring Accuracy** | Random (35% OI+Spot) | Real Data | ✅ Critical |
| **Price Tracking** | Candles (4h lag) | Market Data (1 min) | ✅ 240x faster |
| **System Confidence** | Low | High | ✅ Production Ready |

---

**Документ создан**: 2025-11-07
**Статус**: READY FOR IMPLEMENTATION
**Следующий шаг**: ФАЗА 0 - Подготовка и Очистка
