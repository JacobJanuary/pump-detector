-- Migration: Fix calculate_confidence_score function
-- Description: Replace old field names (futures_spike_ratio_7d) with new universal names (spike_ratio_7d)
-- Date: 2025-11-07
-- Author: Claude Code

BEGIN;

-- Drop old overloads
DROP FUNCTION IF EXISTS pump.calculate_confidence_score(bigint) CASCADE;
DROP FUNCTION IF EXISTS pump.calculate_confidence_score(integer) CASCADE;

-- Recreate with new field names
CREATE OR REPLACE FUNCTION pump.calculate_confidence_score(p_signal_id INTEGER)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_signal pump.signals%ROWTYPE;
    v_confirmations_count INTEGER;
    v_score INTEGER := 0;
    v_volume_score INTEGER := 0;
    v_oi_score INTEGER := 0;
    v_spot_score INTEGER := 0;
    v_confirmation_score INTEGER := 0;
    v_timing_score INTEGER := 0;
    v_hours_since NUMERIC;
BEGIN
    -- Get signal record
    SELECT * INTO v_signal FROM pump.signals WHERE id = p_signal_id;

    IF NOT FOUND THEN
        RETURN 0;
    END IF;

    -- 1. Volume Score (0-25) - USE NEW FIELD spike_ratio_7d
    IF v_signal.spike_ratio_7d >= 5.0 THEN
        v_volume_score := 25;
    ELSIF v_signal.spike_ratio_7d >= 3.0 THEN
        v_volume_score := 20;
    ELSIF v_signal.spike_ratio_7d >= 2.0 THEN
        v_volume_score := 15;
    ELSE
        v_volume_score := 10;
    END IF;

    -- 2. OI Score (0-25)
    IF v_signal.oi_change_pct >= 50 THEN
        v_oi_score := 25;
    ELSIF v_signal.oi_change_pct >= 30 THEN
        v_oi_score := 20;
    ELSIF v_signal.oi_change_pct >= 15 THEN
        v_oi_score := 15;
    ELSIF v_signal.oi_change_pct >= 5 THEN
        v_oi_score := 10;
    END IF;

    -- 3. Spot Sync Score (0-20) - TEMPORARILY DISABLED (will be calculated via clusters)
    -- has_spot_sync field removed, spot_score = 0 for now
    v_spot_score := 0;

    -- 4. Confirmation Score (0-20)
    SELECT COUNT(*) INTO v_confirmations_count
    FROM pump.signal_confirmations
    WHERE signal_id = p_signal_id;

    v_confirmation_score := LEAST(20, v_confirmations_count * 5);

    -- 5. Timing Score (0-10)
    v_hours_since := EXTRACT(EPOCH FROM (NOW() - v_signal.detected_at)) / 3600;

    IF v_hours_since <= 4 THEN
        v_timing_score := 10;
    ELSIF v_hours_since <= 12 THEN
        v_timing_score := 7;
    ELSIF v_hours_since <= 24 THEN
        v_timing_score := 5;
    ELSIF v_hours_since <= 48 THEN
        v_timing_score := 3;
    END IF;

    -- Total score
    v_score := v_volume_score + v_oi_score + v_spot_score + v_confirmation_score + v_timing_score;

    -- Update scores table
    INSERT INTO pump.signal_scores (
        signal_id,
        volume_score,
        oi_score,
        spot_sync_score,
        confirmation_score,
        timing_score,
        total_score,
        confidence_level
    ) VALUES (
        p_signal_id,
        v_volume_score,
        v_oi_score,
        v_spot_score,
        v_confirmation_score,
        v_timing_score,
        v_score,
        CASE
            WHEN v_score >= 80 THEN 'EXTREME'
            WHEN v_score >= 60 THEN 'HIGH'
            WHEN v_score >= 40 THEN 'MEDIUM'
            ELSE 'LOW'
        END
    )
    ON CONFLICT (signal_id) DO UPDATE SET
        volume_score = EXCLUDED.volume_score,
        oi_score = EXCLUDED.oi_score,
        spot_sync_score = EXCLUDED.spot_sync_score,
        confirmation_score = EXCLUDED.confirmation_score,
        timing_score = EXCLUDED.timing_score,
        total_score = EXCLUDED.total_score,
        confidence_level = EXCLUDED.confidence_level,
        updated_at = NOW();

    RETURN v_score;
END;
$$;

COMMIT;

-- Verification
SELECT 'Migration 004 completed: calculate_confidence_score fixed!' as status;
