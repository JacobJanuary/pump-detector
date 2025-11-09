-- Table for storing backtest results
-- Tracks how well the detection engine predicted each known pump event

CREATE TABLE IF NOT EXISTS pump.backtest_results (
    id SERIAL PRIMARY KEY,
    known_pump_id INTEGER NOT NULL REFERENCES pump.known_pump_events(id),
    pair_symbol VARCHAR(20) NOT NULL,

    -- When was the backtest performed
    test_timestamp TIMESTAMPTZ DEFAULT NOW(),

    -- Time-travel parameters
    analysis_time TIMESTAMPTZ NOT NULL,  -- Time when we ran the analysis (X hours before pump)
    hours_before_pump INTEGER NOT NULL,   -- How many hours before the pump was detected

    -- Detection result
    was_detected BOOLEAN NOT NULL,        -- Did the engine detect this pump?
    confidence VARCHAR(10),                -- HIGH, MEDIUM, LOW (if detected)
    score DECIMAL(5, 2),                   -- Detection score 0-100
    pattern_type VARCHAR(50),              -- Pattern type detected
    is_actionable BOOLEAN,                 -- Was it actionable?

    -- Signal statistics at analysis time
    total_signals INTEGER,
    extreme_signals INTEGER,
    critical_window_signals INTEGER,
    eta_hours INTEGER,                     -- Estimated time to pump

    -- Classification for metrics
    classification VARCHAR(20) NOT NULL,   -- TP, FP, TN, FN
    /*
        TP (True Positive):  Detected AND pump happened
        FP (False Positive): Detected BUT pump didn't happen (should not occur with known pumps)
        FN (False Negative): NOT detected BUT pump happened
        TN (True Negative):  NOT detected AND pump didn't happen (should not occur with known pumps)
    */

    -- Metadata
    engine_version VARCHAR(10) DEFAULT '2.0',
    config_snapshot JSONB,  -- Detection config at time of test
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_backtest_known_pump ON pump.backtest_results(known_pump_id);
CREATE INDEX IF NOT EXISTS idx_backtest_symbol ON pump.backtest_results(pair_symbol);
CREATE INDEX IF NOT EXISTS idx_backtest_classification ON pump.backtest_results(classification);
CREATE INDEX IF NOT EXISTS idx_backtest_detected ON pump.backtest_results(was_detected);
CREATE INDEX IF NOT EXISTS idx_backtest_confidence ON pump.backtest_results(confidence);
CREATE INDEX IF NOT EXISTS idx_backtest_hours_before ON pump.backtest_results(hours_before_pump);

COMMENT ON TABLE pump.backtest_results IS 'Results of backtesting detection engine on known pump events';
COMMENT ON COLUMN pump.backtest_results.analysis_time IS 'Simulated time when analysis was performed (time-travel)';
COMMENT ON COLUMN pump.backtest_results.hours_before_pump IS 'How many hours before pump start this analysis was done';
COMMENT ON COLUMN pump.backtest_results.classification IS 'TP=True Positive, FP=False Positive, FN=False Negative, TN=True Negative';
