-- Migration: Fix calculate_confidence_score to remove OI references
-- Description: Remove oi_change_pct from scoring function (OI removed from schema)
-- Date: 2025-11-07
-- Author: Claude Code

BEGIN;

-- Drop old function
DROP FUNCTION IF EXISTS pump.calculate_confidence_score(integer) CASCADE;

-- Recreate without OI references
CREATE OR REPLACE FUNCTION pump.calculate_confidence_score(p_signal_id INTEGER)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_signal pump.signals%ROWTYPE;
    v_confirmations_count INTEGER;
    v_score INTEGER := 0;
    v_volume_score INTEGER := 0;
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

    -- 1. Volume Score (0-50) - increased weight since OI removed
    IF v_signal.spike_ratio_7d >= 10.0 THEN
        v_volume_score := 50;
    ELSIF v_signal.spike_ratio_7d >= 5.0 THEN
        v_volume_score := 40;
    ELSIF v_signal.spike_ratio_7d >= 3.0 THEN
        v_volume_score := 30;
    ELSIF v_signal.spike_ratio_7d >= 2.0 THEN
        v_volume_score := 20;
    ELSE
        v_volume_score := 10;
    END IF;

    -- 2. Spot Sync Score (0-20) - TEMPORARILY DISABLED (will be calculated via clusters)
    v_spot_score := 0;

    -- 3. Confirmation Score (0-20)
    SELECT COUNT(*) INTO v_confirmations_count
    FROM pump.signal_confirmations
    WHERE signal_id = p_signal_id;

    v_confirmation_score := LEAST(20, v_confirmations_count * 5);

    -- 4. Timing Score (0-10)
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

    -- Total score (max 100)
    v_score := v_volume_score + v_spot_score + v_confirmation_score + v_timing_score;

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
        0,  -- OI score = 0
        v_spot_score,
        v_confirmation_score,
        v_timing_score,
        v_score,
        CASE
            WHEN v_score >= 70 THEN 'EXTREME'
            WHEN v_score >= 50 THEN 'HIGH'
            WHEN v_score >= 30 THEN 'MEDIUM'
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
SELECT 'Migration 006 completed: calculate_confidence_score fixed (OI removed)!' as status;
