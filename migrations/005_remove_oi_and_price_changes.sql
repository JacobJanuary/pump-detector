-- Migration: Remove OI and price_change fields
-- Description: OI меняется после пампа (не нужен). price_change будет рассчитываться отдельно
-- Date: 2025-11-07
-- Author: Claude Code

BEGIN;

-- ============================================================================
-- STEP 1: Удалить OI поля из pump.signals
-- ============================================================================

ALTER TABLE pump.signals
DROP COLUMN IF EXISTS oi_change_pct CASCADE,
DROP COLUMN IF EXISTS oi_value CASCADE,
DROP COLUMN IF EXISTS oi_timestamp CASCADE;

-- ============================================================================
-- STEP 2: Удалить price_change поля (оставить только price_at_signal)
-- ============================================================================

ALTER TABLE pump.signals
DROP COLUMN IF EXISTS price_change_1h CASCADE,
DROP COLUMN IF EXISTS price_change_4h CASCADE,
DROP COLUMN IF EXISTS price_change_24h CASCADE;

-- ============================================================================
-- STEP 3: Обновить комментарии
-- ============================================================================

COMMENT ON COLUMN pump.signals.price_at_signal IS 'Цена на момент детекции аномалии';

COMMIT;

-- Verification
SELECT 'Migration 005 completed: OI and price_change fields removed!' as status;
