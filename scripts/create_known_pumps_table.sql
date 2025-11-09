-- Create table for known pump events (for backtesting)
-- These are the 136 historical pumps used to validate the detection engine

CREATE TABLE IF NOT EXISTS pump.known_pump_events (
    id SERIAL PRIMARY KEY,
    trading_pair_id INTEGER NOT NULL REFERENCES trading_pairs(id),
    pair_symbol VARCHAR(20) NOT NULL,

    -- Pump timing
    pump_start TIMESTAMPTZ NOT NULL,  -- When the pump started
    pump_peak TIMESTAMPTZ,             -- When price peaked (if available)
    pump_end TIMESTAMPTZ,              -- When pump ended (if available)

    -- Price data
    start_price DECIMAL(20, 8) NOT NULL,
    high_price DECIMAL(20, 8),
    price_after_24h DECIMAL(20, 8),

    -- Performance metrics
    max_gain_24h DECIMAL(10, 4) NOT NULL,  -- Max gain within 24h
    pump_duration_hours INTEGER,

    -- Metadata
    data_source VARCHAR(50) DEFAULT 'historical_analysis',  -- Where this pump was identified
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(pair_symbol, pump_start)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_known_pumps_symbol ON pump.known_pump_events(pair_symbol);
CREATE INDEX IF NOT EXISTS idx_known_pumps_start ON pump.known_pump_events(pump_start);
CREATE INDEX IF NOT EXISTS idx_known_pumps_trading_pair ON pump.known_pump_events(trading_pair_id);

COMMENT ON TABLE pump.known_pump_events IS 'Known historical pump events for backtesting and validation';
COMMENT ON COLUMN pump.known_pump_events.max_gain_24h IS 'Maximum price gain within 24 hours of pump start (%)';
COMMENT ON COLUMN pump.known_pump_events.data_source IS 'Source of pump identification (e.g., historical_analysis, manual_review)';
