-- Migration: Update score constraints after OI removal
-- Description: Increase volume_score max from 25 to 50 (since OI score was removed)
-- Date: 2025-11-07
-- Author: Claude Code

BEGIN;

-- Update volume_score constraint (was 0-25, now 0-50)
ALTER TABLE pump.signal_scores
DROP CONSTRAINT IF EXISTS signal_scores_volume_score_check;

ALTER TABLE pump.signal_scores
ADD CONSTRAINT signal_scores_volume_score_check
CHECK (volume_score >= 0 AND volume_score <= 50);

-- Update total_score constraint (still 0-100, but components changed)
ALTER TABLE pump.signal_scores
DROP CONSTRAINT IF EXISTS signal_scores_total_score_check;

ALTER TABLE pump.signal_scores
ADD CONSTRAINT signal_scores_total_score_check
CHECK (total_score >= 0 AND total_score <= 100);

COMMIT;

-- Verification
SELECT 'Migration 007 completed: Score constraints updated!' as status;
