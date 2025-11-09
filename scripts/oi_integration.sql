-- ============================================================
-- OPEN INTEREST INTEGRATION FOR PUMP DETECTION
-- ============================================================

-- Add OI tracking columns to signals table
ALTER TABLE pump.signals
ADD COLUMN IF NOT EXISTS futures_oi_change_pct NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS futures_oi_spike_ratio NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS spot_volume_change_pct NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS spot_futures_correlation NUMERIC(5,3);

-- Create OI monitoring table
CREATE TABLE IF NOT EXISTS pump.oi_tracking (
    id BIGSERIAL PRIMARY KEY,
    trading_pair_id INTEGER NOT NULL,
    pair_symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open_interest NUMERIC(20,2),
    oi_value_usd NUMERIC(20,2),
    oi_change_1h NUMERIC(10,2),
    oi_change_4h NUMERIC(10,2),
    oi_change_24h NUMERIC(10,2),
    top_trader_ratio NUMERIC(5,3),
    long_short_ratio NUMERIC(5,3),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oi_tracking_pair_time
ON pump.oi_tracking(trading_pair_id, timestamp DESC);

-- Function to analyze OI patterns
CREATE OR REPLACE FUNCTION pump.analyze_oi_patterns(
    p_trading_pair_id INTEGER,
    p_timestamp TIMESTAMPTZ
)
RETURNS TABLE (
    oi_spike_detected BOOLEAN,
    oi_change_4h NUMERIC,
    oi_baseline_7d NUMERIC,
    oi_spike_ratio NUMERIC,
    unusual_activity BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    WITH recent_oi AS (
        -- Get OI data from existing tables
        SELECT
            tp.id as trading_pair_id,
            to_timestamp(c.open_time / 1000) as candle_time,
            c.open_interest,
            c.open_interest_value
        FROM public.candles c
        INNER JOIN public.trading_pairs tp ON c.trading_pair_id = tp.id
        WHERE tp.id = p_trading_pair_id
          AND c.interval_id = 4  -- 4h
          AND to_timestamp(c.open_time / 1000) >= p_timestamp - INTERVAL '30 days'
          AND c.open_interest IS NOT NULL
        ORDER BY c.open_time DESC
    ),
    oi_analysis AS (
        SELECT
            candle_time,
            open_interest,
            -- Calculate 7-day baseline
            AVG(open_interest) OVER (
                ORDER BY candle_time
                ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING
            ) as baseline_7d,
            -- Calculate 4h change
            LAG(open_interest, 1) OVER (ORDER BY candle_time) as prev_oi,
            -- Detect unusual patterns
            STDDEV(open_interest) OVER (
                ORDER BY candle_time
                ROWS BETWEEN 42 PRECEDING AND CURRENT ROW
            ) as oi_stddev
        FROM recent_oi
        WHERE candle_time <= p_timestamp
    )
    SELECT
        COALESCE(
            (open_interest > baseline_7d * 1.5) AND
            (open_interest - prev_oi) > 0,
            FALSE
        ) as oi_spike_detected,
        COALESCE(
            ((open_interest - prev_oi) / NULLIF(prev_oi, 0)) * 100,
            0
        ) as oi_change_4h,
        baseline_7d as oi_baseline_7d,
        COALESCE(
            open_interest / NULLIF(baseline_7d, 0),
            0
        ) as oi_spike_ratio,
        COALESCE(
            ABS(open_interest - baseline_7d) > (2 * oi_stddev),
            FALSE
        ) as unusual_activity
    FROM oi_analysis
    WHERE candle_time = p_timestamp
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Enhanced detection function with OI
CREATE OR REPLACE FUNCTION pump.detect_anomalies_with_oi(
    p_lookback_hours INTEGER DEFAULT 4
)
RETURNS TABLE (
    trading_pair_id INTEGER,
    pair_symbol VARCHAR,
    signal_timestamp TIMESTAMPTZ,
    volume_spike_ratio NUMERIC,
    oi_spike_ratio NUMERIC,
    combined_score NUMERIC,
    signal_strength VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    WITH volume_spikes AS (
        -- Original volume spike detection
        SELECT
            c.trading_pair_id,
            tp.pair_symbol,
            to_timestamp(c.open_time / 1000) as candle_time,
            c.quote_asset_volume as volume,
            AVG(c.quote_asset_volume) OVER (
                PARTITION BY c.trading_pair_id
                ORDER BY c.open_time
                ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING
            ) as baseline_7d
        FROM public.candles c
        INNER JOIN public.trading_pairs tp ON c.trading_pair_id = tp.id
        WHERE tp.exchange_id = 1
          AND tp.is_active = true
          AND tp.contract_type_id = 1
          AND c.interval_id = 4
          AND to_timestamp(c.open_time / 1000) >= NOW() - INTERVAL '30 days'
    ),
    oi_data AS (
        -- Get OI data
        SELECT
            c.trading_pair_id,
            to_timestamp(c.open_time / 1000) as candle_time,
            c.open_interest,
            AVG(c.open_interest) OVER (
                PARTITION BY c.trading_pair_id
                ORDER BY c.open_time
                ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING
            ) as oi_baseline_7d
        FROM public.candles c
        WHERE c.interval_id = 4
          AND to_timestamp(c.open_time / 1000) >= NOW() - INTERVAL '30 days'
          AND c.open_interest IS NOT NULL
    ),
    combined_signals AS (
        SELECT
            v.trading_pair_id,
            v.pair_symbol,
            v.candle_time,
            COALESCE(v.volume / NULLIF(v.baseline_7d, 0), 0) as vol_spike,
            COALESCE(o.open_interest / NULLIF(o.oi_baseline_7d, 0), 0) as oi_spike
        FROM volume_spikes v
        LEFT JOIN oi_data o ON
            v.trading_pair_id = o.trading_pair_id
            AND v.candle_time = o.candle_time
        WHERE v.baseline_7d IS NOT NULL
          AND v.candle_time >= NOW() - INTERVAL '%s hours'
          AND v.volume / v.baseline_7d >= 1.5
    )
    SELECT
        trading_pair_id,
        pair_symbol,
        candle_time as signal_timestamp,
        vol_spike as volume_spike_ratio,
        COALESCE(oi_spike, 1.0) as oi_spike_ratio,
        -- Combined score with OI weight
        (vol_spike * 0.6 + COALESCE(oi_spike, 1.0) * 0.4) as combined_score,
        -- Signal strength classification
        CASE
            WHEN vol_spike >= 5 AND COALESCE(oi_spike, 1) >= 1.5 THEN 'EXTREME'
            WHEN vol_spike >= 3 AND COALESCE(oi_spike, 1) >= 1.3 THEN 'STRONG'
            WHEN vol_spike >= 2 OR COALESCE(oi_spike, 1) >= 1.5 THEN 'MEDIUM'
            ELSE 'WEAK'
        END as signal_strength
    FROM combined_signals
    WHERE NOT EXISTS (
        SELECT 1 FROM pump.signals s
        WHERE s.trading_pair_id = combined_signals.trading_pair_id
          AND s.signal_timestamp = combined_signals.candle_time
    )
    ORDER BY combined_score DESC
    LIMIT 50;
END;
$$ LANGUAGE plpgsql;

-- Function to track OI changes in real-time
CREATE OR REPLACE FUNCTION pump.track_oi_changes()
RETURNS INTEGER AS $$
DECLARE
    v_record_count INTEGER := 0;
BEGIN
    -- Insert latest OI data
    INSERT INTO pump.oi_tracking (
        trading_pair_id,
        pair_symbol,
        timestamp,
        open_interest,
        oi_value_usd,
        oi_change_1h,
        oi_change_4h,
        oi_change_24h
    )
    SELECT
        c.trading_pair_id,
        tp.pair_symbol,
        to_timestamp(c.open_time / 1000) as timestamp,
        c.open_interest,
        c.open_interest_value,
        -- 1h change
        ((c.open_interest - LAG(c.open_interest, 1) OVER w) /
         NULLIF(LAG(c.open_interest, 1) OVER w, 0)) * 100 as oi_change_1h,
        -- 4h change
        ((c.open_interest - LAG(c.open_interest, 1) OVER w) /
         NULLIF(LAG(c.open_interest, 1) OVER w, 0)) * 100 as oi_change_4h,
        -- 24h change
        ((c.open_interest - LAG(c.open_interest, 6) OVER w) /
         NULLIF(LAG(c.open_interest, 6) OVER w, 0)) * 100 as oi_change_24h
    FROM public.candles c
    INNER JOIN public.trading_pairs tp ON c.trading_pair_id = tp.id
    WHERE tp.exchange_id = 1
      AND tp.is_active = true
      AND tp.contract_type_id = 1
      AND c.interval_id = 4
      AND c.open_interest IS NOT NULL
      AND to_timestamp(c.open_time / 1000) >= NOW() - INTERVAL '4 hours'
      AND NOT EXISTS (
          SELECT 1 FROM pump.oi_tracking ot
          WHERE ot.trading_pair_id = c.trading_pair_id
            AND ot.timestamp = to_timestamp(c.open_time / 1000)
      )
    WINDOW w AS (PARTITION BY c.trading_pair_id ORDER BY c.open_time)
    ON CONFLICT DO NOTHING;

    GET DIAGNOSTICS v_record_count = ROW_COUNT;
    RETURN v_record_count;
END;
$$ LANGUAGE plpgsql;

-- View for OI anomalies
CREATE OR REPLACE VIEW pump.oi_anomalies AS
WITH recent_oi AS (
    SELECT
        trading_pair_id,
        pair_symbol,
        timestamp,
        open_interest,
        oi_change_4h,
        AVG(ABS(oi_change_4h)) OVER (
            PARTITION BY trading_pair_id
            ORDER BY timestamp
            ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING
        ) as avg_change,
        STDDEV(oi_change_4h) OVER (
            PARTITION BY trading_pair_id
            ORDER BY timestamp
            ROWS BETWEEN 42 PRECEDING AND 1 PRECEDING
        ) as stddev_change
    FROM pump.oi_tracking
    WHERE timestamp >= NOW() - INTERVAL '7 days'
)
SELECT
    trading_pair_id,
    pair_symbol,
    timestamp,
    open_interest,
    oi_change_4h,
    avg_change,
    CASE
        WHEN ABS(oi_change_4h) > avg_change + (2 * stddev_change) THEN 'HIGH'
        WHEN ABS(oi_change_4h) > avg_change + stddev_change THEN 'MEDIUM'
        ELSE 'NORMAL'
    END as anomaly_level
FROM recent_oi
WHERE oi_change_4h IS NOT NULL
  AND timestamp >= NOW() - INTERVAL '24 hours'
  AND ABS(oi_change_4h) > COALESCE(avg_change, 0) + COALESCE(stddev_change, 0)
ORDER BY ABS(oi_change_4h) DESC;

-- Statistics view
CREATE OR REPLACE VIEW pump.oi_statistics AS
SELECT
    s.signal_strength,
    COUNT(*) as total_signals,
    COUNT(*) FILTER (WHERE s.futures_oi_spike_ratio IS NOT NULL) as with_oi_data,
    AVG(s.futures_oi_spike_ratio) as avg_oi_spike,
    COUNT(*) FILTER (WHERE s.pump_realized) as pumps,
    COUNT(*) FILTER (WHERE s.pump_realized AND s.futures_oi_spike_ratio > 1.5) as pumps_with_oi,
    ROUND(
        COUNT(*) FILTER (WHERE s.pump_realized AND s.futures_oi_spike_ratio > 1.5)::numeric /
        NULLIF(COUNT(*) FILTER (WHERE s.futures_oi_spike_ratio > 1.5), 0) * 100,
        1
    ) as oi_pump_accuracy
FROM pump.signals s
WHERE s.detected_at >= NOW() - INTERVAL '30 days'
GROUP BY s.signal_strength
ORDER BY s.signal_strength;

\echo 'OI Integration complete!'
\echo 'Run pump.track_oi_changes() to start tracking OI data'
\echo 'Use pump.detect_anomalies_with_oi() for enhanced detection'