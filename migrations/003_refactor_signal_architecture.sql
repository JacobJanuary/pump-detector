-- Migration: Refactor Signal Architecture
-- Description: Переход от futures-only к универсальной архитектуре с SPOT и FUTURES сигналами
-- Date: 2025-11-07
-- Author: Claude Code

BEGIN;

-- ============================================================================
-- STEP 1: Создать новые универсальные поля
-- ============================================================================

-- Добавить signal_type для различения SPOT/FUTURES сигналов
ALTER TABLE pump.signals
ADD COLUMN signal_type VARCHAR(10) DEFAULT 'FUTURES' NOT NULL;

-- Добавить универсальные поля для объема (заменяют futures_* поля)
ALTER TABLE pump.signals
ADD COLUMN volume NUMERIC(20,2),
ADD COLUMN baseline_7d NUMERIC(20,2),
ADD COLUMN baseline_14d NUMERIC(20,2),
ADD COLUMN baseline_30d NUMERIC(20,2),
ADD COLUMN spike_ratio_7d NUMERIC(10,2),
ADD COLUMN spike_ratio_14d NUMERIC(10,2),
ADD COLUMN spike_ratio_30d NUMERIC(10,2);

-- Добавить поля для цены
ALTER TABLE pump.signals
ADD COLUMN price_at_signal NUMERIC(20,2),
ADD COLUMN price_change_1h NUMERIC(10,2),
ADD COLUMN price_change_4h NUMERIC(10,2),
ADD COLUMN price_change_24h NUMERIC(10,2);

-- Добавить cluster_id для группировки связанных сигналов
ALTER TABLE pump.signals
ADD COLUMN cluster_id INTEGER;

-- ============================================================================
-- STEP 2: Мигрировать существующие данные
-- ============================================================================

-- Скопировать данные из futures_* полей в универсальные поля
UPDATE pump.signals SET
    volume = futures_volume,
    baseline_7d = futures_baseline_7d,
    baseline_14d = futures_baseline_14d,
    baseline_30d = futures_baseline_30d,
    spike_ratio_7d = futures_spike_ratio_7d,
    spike_ratio_14d = futures_spike_ratio_14d,
    spike_ratio_30d = futures_spike_ratio_30d,
    signal_type = 'FUTURES';

-- ============================================================================
-- STEP 3: Удалить старые поля
-- ============================================================================

-- Удалить futures_* поля (теперь используются универсальные)
ALTER TABLE pump.signals
DROP COLUMN IF EXISTS futures_volume CASCADE,
DROP COLUMN IF EXISTS futures_baseline_7d CASCADE,
DROP COLUMN IF EXISTS futures_baseline_14d CASCADE,
DROP COLUMN IF EXISTS futures_baseline_30d CASCADE,
DROP COLUMN IF EXISTS futures_spike_ratio_7d CASCADE,
DROP COLUMN IF EXISTS futures_spike_ratio_14d CASCADE,
DROP COLUMN IF EXISTS futures_spike_ratio_30d CASCADE;

-- Удалить spot_* поля (теперь SPOT будет отдельными сигналами)
ALTER TABLE pump.signals
DROP COLUMN IF EXISTS spot_volume CASCADE,
DROP COLUMN IF EXISTS spot_baseline_7d CASCADE,
DROP COLUMN IF EXISTS spot_spike_ratio_7d CASCADE,
DROP COLUMN IF EXISTS has_spot_sync CASCADE;

-- ============================================================================
-- STEP 4: Создать таблицу signal_clusters
-- ============================================================================

CREATE TABLE IF NOT EXISTS pump.signal_clusters (
    id SERIAL PRIMARY KEY,
    pair_symbol VARCHAR(20) NOT NULL,
    first_signal_time TIMESTAMP WITH TIME ZONE NOT NULL,
    last_signal_time TIMESTAMP WITH TIME ZONE NOT NULL,
    total_score INTEGER DEFAULT 0,
    has_futures_spike BOOLEAN DEFAULT FALSE,
    has_spot_spike BOOLEAN DEFAULT FALSE,
    max_price_change NUMERIC(10,2),
    status VARCHAR(20) DEFAULT 'ACTIVE',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- STEP 5: Создать индексы
-- ============================================================================

-- Индекс для быстрого поиска сигналов по типу
CREATE INDEX idx_signals_type ON pump.signals(signal_type);

-- Индекс для быстрого поиска по символу и времени (для кластеризации)
CREATE INDEX idx_signals_pair_symbol_time ON pump.signals(pair_symbol, signal_timestamp DESC);

-- Индекс для кластера
CREATE INDEX idx_signals_cluster_id ON pump.signals(cluster_id) WHERE cluster_id IS NOT NULL;

-- Индексы для таблицы clusters
CREATE INDEX idx_clusters_pair_symbol ON pump.signal_clusters(pair_symbol);
CREATE INDEX idx_clusters_status ON pump.signal_clusters(status);
CREATE INDEX idx_clusters_time ON pump.signal_clusters(first_signal_time DESC);

-- ============================================================================
-- STEP 6: Добавить constraints
-- ============================================================================

-- Check constraint для signal_type
ALTER TABLE pump.signals
ADD CONSTRAINT signals_signal_type_check
CHECK (signal_type IN ('FUTURES', 'SPOT'));

-- Check constraint для status в clusters
ALTER TABLE pump.signal_clusters
ADD CONSTRAINT clusters_status_check
CHECK (status IN ('ACTIVE', 'CONFIRMED', 'FAILED', 'EXPIRED'));

-- Foreign key для cluster_id
ALTER TABLE pump.signals
ADD CONSTRAINT signals_cluster_id_fkey
FOREIGN KEY (cluster_id) REFERENCES pump.signal_clusters(id) ON DELETE SET NULL;

-- ============================================================================
-- STEP 7: Создать триггер для updated_at в clusters
-- ============================================================================

CREATE TRIGGER update_clusters_updated_at
    BEFORE UPDATE ON pump.signal_clusters
    FOR EACH ROW
    EXECUTE FUNCTION pump.update_updated_at_column();

-- ============================================================================
-- STEP 8: Обновить комментарии
-- ============================================================================

COMMENT ON COLUMN pump.signals.signal_type IS 'Тип сигнала: FUTURES или SPOT';
COMMENT ON COLUMN pump.signals.volume IS 'Объем на свече с аномалией (универсальное поле)';
COMMENT ON COLUMN pump.signals.baseline_7d IS 'Базовый объем за 7 дней';
COMMENT ON COLUMN pump.signals.spike_ratio_7d IS 'Коэффициент спайка (volume / baseline_7d)';
COMMENT ON COLUMN pump.signals.price_at_signal IS 'Цена на момент сигнала';
COMMENT ON COLUMN pump.signals.price_change_1h IS 'Изменение цены через 1 час';
COMMENT ON COLUMN pump.signals.price_change_4h IS 'Изменение цены через 4 часа';
COMMENT ON COLUMN pump.signals.price_change_24h IS 'Изменение цены через 24 часа';
COMMENT ON COLUMN pump.signals.cluster_id IS 'ID кластера связанных сигналов';

COMMENT ON TABLE pump.signal_clusters IS 'Кластеры связанных сигналов (SPOT+FUTURES+OI) для одного символа';
COMMENT ON COLUMN pump.signal_clusters.pair_symbol IS 'Символ торговой пары (BTCUSDT, ETHUSDT, etc.)';
COMMENT ON COLUMN pump.signal_clusters.total_score IS 'Суммарный рейтинг всех сигналов в кластере';
COMMENT ON COLUMN pump.signal_clusters.has_futures_spike IS 'Есть ли аномалия на фьючах';
COMMENT ON COLUMN pump.signal_clusters.has_spot_spike IS 'Есть ли аномалия на споте';
COMMENT ON COLUMN pump.signal_clusters.max_price_change IS 'Максимальное изменение цены в кластере';

COMMIT;

-- ============================================================================
-- Verification queries
-- ============================================================================
-- SELECT 'Migration completed successfully!' as status;
-- SELECT COUNT(*) as total_signals, signal_type FROM pump.signals GROUP BY signal_type;
-- SELECT * FROM pump.signal_clusters LIMIT 5;
