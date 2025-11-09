-- ============================================================
-- ЗАГРУЗКА ИСТОРИЧЕСКИХ СИГНАЛОВ ДЛЯ КАЛИБРОВКИ
-- ============================================================

\echo 'Loading historical signals for calibration...'

-- Загружаем сигналы за последние 7 дней для начальной калибровки
INSERT INTO pump.signals (
    trading_pair_id,
    pair_symbol,
    signal_timestamp,
    detected_at,
    futures_volume,
    futures_baseline_7d,
    futures_baseline_14d,
    futures_spike_ratio_7d,
    futures_spike_ratio_14d,
    signal_strength,
    initial_confidence,
    status,
    max_price_increase,
    pump_realized
)
WITH volume_data AS (
    SELECT
        c.trading_pair_id,
        tp.pair_symbol,
        to_timestamp(c.open_time / 1000) as candle_time,
        c.close_price,
        c.quote_asset_volume as volume,
        -- 7-дневный baseline (42 свечи для 4h)
        AVG(c.quote_asset_volume) OVER (
            PARTITION BY c.trading_pair_id
            ORDER BY c.open_time
            ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING
        ) as baseline_7d,
        -- 14-дневный baseline (84 свечи)
        AVG(c.quote_asset_volume) OVER (
            PARTITION BY c.trading_pair_id
            ORDER BY c.open_time
            ROWS BETWEEN 84 PRECEDING AND 1 PRECEDING
        ) as baseline_14d
    FROM public.candles c
    INNER JOIN public.trading_pairs tp ON c.trading_pair_id = tp.id
    WHERE tp.exchange_id = 1  -- Binance
      AND tp.is_active = true
      AND tp.contract_type_id = 1  -- Futures
      AND c.interval_id = 4  -- 4h
      AND to_timestamp(c.open_time / 1000) BETWEEN
          (NOW() - INTERVAL '28 days')  -- +21 день для расчета baseline
          AND (NOW() - INTERVAL '1 day')  -- До вчера (исторические данные)
),
spike_data AS (
    SELECT
        trading_pair_id,
        pair_symbol,
        candle_time,
        close_price,
        volume,
        baseline_7d,
        baseline_14d,
        CASE
            WHEN baseline_7d > 0 THEN volume / baseline_7d
            ELSE 0
        END as spike_ratio_7d,
        CASE
            WHEN baseline_14d > 0 THEN volume / baseline_14d
            ELSE 0
        END as spike_ratio_14d
    FROM volume_data
    WHERE baseline_7d IS NOT NULL
      AND candle_time >= NOW() - INTERVAL '7 days'
),
anomalies AS (
    SELECT
        sd.*,
        -- Классификация сигнала
        CASE
            WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= 5.0 THEN 'EXTREME'
            WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= 3.0 THEN 'STRONG'
            WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= 2.0 THEN 'MEDIUM'
            WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= 1.5 THEN 'WEAK'
            ELSE NULL
        END as signal_strength,
        -- Начальная уверенность
        CASE
            WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= 5.0 THEN 75
            WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= 3.0 THEN 60
            WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= 2.0 THEN 45
            WHEN GREATEST(spike_ratio_7d, spike_ratio_14d) >= 1.5 THEN 30
            ELSE 0
        END as confidence_score,
        -- Проверяем рост цены для валидации
        (
            SELECT MAX(c2.high_price)
            FROM public.candles c2
            WHERE c2.trading_pair_id = sd.trading_pair_id
              AND c2.interval_id = 4
              AND to_timestamp(c2.open_time / 1000) BETWEEN
                  sd.candle_time AND (sd.candle_time + INTERVAL '7 days')
        ) as max_price_7d
    FROM spike_data sd
    WHERE spike_ratio_7d >= 1.5  -- Минимальный порог
),
validated_anomalies AS (
    SELECT
        *,
        CASE
            WHEN max_price_7d IS NOT NULL
            THEN ((max_price_7d - close_price) / close_price * 100)
            ELSE NULL
        END as price_increase_pct,
        CASE
            WHEN max_price_7d IS NOT NULL
                AND ((max_price_7d - close_price) / close_price * 100) >= 10
            THEN TRUE
            ELSE FALSE
        END as pump_realized
    FROM anomalies
)
-- Вставляем только топ сигналы для каждой пары за период
SELECT DISTINCT ON (trading_pair_id, DATE_TRUNC('day', candle_time))
    trading_pair_id,
    pair_symbol,
    candle_time as signal_timestamp,
    candle_time as detected_at,
    volume as futures_volume,
    baseline_7d as futures_baseline_7d,
    baseline_14d as futures_baseline_14d,
    spike_ratio_7d as futures_spike_ratio_7d,
    spike_ratio_14d as futures_spike_ratio_14d,
    signal_strength,
    confidence_score as initial_confidence,
    CASE
        WHEN pump_realized THEN 'CONFIRMED'
        WHEN price_increase_pct IS NOT NULL THEN 'FAILED'
        ELSE 'MONITORING'
    END as status,
    price_increase_pct as max_price_increase,
    pump_realized
FROM validated_anomalies
WHERE signal_strength IS NOT NULL
ORDER BY trading_pair_id, DATE_TRUNC('day', candle_time), spike_ratio_7d DESC
LIMIT 500  -- Ограничиваем для начальной загрузки
ON CONFLICT DO NOTHING;

-- Статистика загрузки
SELECT
    'Historical signals loaded' as status,
    COUNT(*) as total_signals,
    COUNT(*) FILTER (WHERE pump_realized = TRUE) as successful_pumps,
    COUNT(*) FILTER (WHERE pump_realized = FALSE) as failed_signals,
    ROUND(
        COUNT(*) FILTER (WHERE pump_realized = TRUE)::numeric /
        NULLIF(COUNT(*), 0) * 100,
        1
    ) as success_rate_pct
FROM pump.signals
WHERE detected_at >= NOW() - INTERVAL '7 days';

\echo 'Historical data loading completed!'