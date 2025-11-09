# Pump Detector System - Current Status
**Last Updated**: 2025-11-07 19:30 UTC
**Session**: OI Data Collection Implementation

---

## ✅ COMPLETED FIXES

### 1. Deep Research Analysis ✅
- **File**: `/home/elcrypto/pump_detector/docs/DEEP_RESEARCH_ANALYSIS.md`
- **Status**: COMPLETED
- **Key Findings**:
  - Overall success rate: 34.4% (186/541)
  - EXTREME signals: 71.6% success rate (spike ≥10.0x)
  - STRONG/MEDIUM/WEAK: Only 25-28% success rate
  - Best day: Friday (64.1% success)
  - Worst day: Wednesday (19.4% success)
  - Best hours: 4:00-8:00 AM UTC (67-69% success)

### 2. Spot Futures Analyzer SQL Fix ✅
- **File**: `/home/elcrypto/pump_detector/daemons/spot_futures_analyzer.py`
- **Issue**: SQL error "column reference 'pair_symbol' is ambiguous"
- **Fix**: Replaced `s.*` with explicit column selection in CTE
- **Status**: FIXED and RESTARTED
- **Log**: /home/elcrypto/pump_detector/logs/spot_futures.log
- **Result**: No more SQL errors

### 3. OI Data Collection Implementation ✅
- **File**: `/home/elcrypto/pump_detector/daemons/detector_daemon.py`
- **Status**: IMPLEMENTED and DEPLOYED
- **Changes**:
  - Added `get_oi_data(trading_pair_id)` method (lines 259-309)
  - Modified `save_signal()` to collect OI on each signal (lines 203-257)
  - Calculates current OI and 7-day OI change percentage
  - Uses `public.market_data` table (updated every minute)
- **Test Results**:
  - 3/5 test pairs have OI data (60% coverage)
  - FILUSDT: 43.46M OI, +57.61% change
  - SOLUSDT: 94.31M OI, -3.92% change
  - BNBUSDT: 30.97M OI, -6.80% change
  - BTCUSDT/ETHUSDT: No OI data (expected - not in market_data)
- **Daemon Status**: Running (PID 1637708 since 19:21)
- **Next Step**: Wait for new signals to verify OI collection works in production

---

## 🔴 CRITICAL ISSUES REMAINING

### Issue 1: OI Data Missing (0% coverage)
**Impact**: HIGH - 20% of scoring weight lost
**Current State**:
- `oi_value`: NULL for all signals
- `oi_change_pct`: NULL for all signals

**Root Cause**: detector_daemon.py doesn't collect OI data

**Solution Path**: Two options:
1. **Option A (Quick)**: Use Binance API `/fapi/v1/openInterest`
   - Add API calls to detector_daemon.py
   - Collect current OI on each signal
   - Calculate OI change % vs 7-day average

2. **Option B (Proper)**: Use existing `public.market_data` table
   - According to ARCHITECTURE_REBUILD_PLAN.md
   - market_data has `open_interest` field updated every minute
   - 44,331 OI records for FILUSDT alone
   - More reliable, no API rate limits

**Recommended**: Option B (use market_data table)

---

### Issue 2: calibrate_scoring.py Uses RANDOM()
**Impact**: HIGH - 35% of scoring uses fake data
**Current State**:
```python
# Lines 86-89 in calibrate_scoring.py
RANDOM() * 100 as oi_score,      # 20% weight
RANDOM() * 100 as spot_score,    # 15% weight
```

**Dependencies**:
- Blocked by Issue 1 (need real OI data first)
- Spot data should work after spot_futures analyzer fix

**Fix Required**:
```python
# Replace RANDOM() with real calculations
CASE
    WHEN s.oi_change_pct >= 30 THEN 100
    WHEN s.oi_change_pct >= 20 THEN 75
    WHEN s.oi_change_pct >= 10 THEN 50
    WHEN s.oi_change_pct >= 5 THEN 25
    ELSE 0
END as oi_score,

CASE
    WHEN s.has_spot_sync = TRUE AND s.spot_spike_ratio_7d >= 3.0 THEN 100
    WHEN s.has_spot_sync = TRUE AND s.spot_spike_ratio_7d >= 2.0 THEN 75
    WHEN s.has_spot_sync = TRUE AND s.spot_spike_ratio_7d >= 1.5 THEN 50
    WHEN s.has_spot_sync = TRUE THEN 25
    ELSE 0
END as spot_score
```

---

## 📋 ACTION PLAN PRIORITY

### HIGH PRIORITY (Do Next)

#### 1. Add OI Data Collection to detector_daemon.py
**Estimated Time**: 4-6 hours
**Complexity**: Medium

**Implementation Steps**:
1. Read `public.market_data` structure
2. Create function to get current OI for trading pair
3. Calculate OI change % vs 7-day average
4. Update detector_daemon.py to collect OI on each signal
5. Test on FILUSDT first
6. Deploy to all pairs

**Success Criteria**:
- 95%+ of new signals have OI data
- `oi_value` and `oi_change_pct` fields populated

---

#### 2. Fix calibrate_scoring.py (After OI collection works)
**Estimated Time**: 2-3 hours
**Complexity**: Low

**Steps**:
1. Replace RANDOM() with real OI calculation
2. Replace RANDOM() with real Spot calculation
3. Test calibration on historical data
4. Verify correlations improve

---

### MEDIUM PRIORITY

#### 3. Optimize Detection Thresholds
**Current**: min_spike_ratio = 1.5x
**Recommended**: min_spike_ratio = 2.5x

**Reason**:
- spike_ratio < 2.5x has only 25-28% success rate
- spike_ratio ≥ 10.0x has 84.6% success rate

**Changes Needed**:
```python
# config/settings.py
DETECTION = {
    'min_spike_ratio': 2.5,        # Was 1.5
    'extreme_spike_ratio': 10.0,   # Was 5.0
    'strong_spike_ratio': 5.0,     # Was 3.0
    'medium_spike_ratio': 3.0,     # Was 2.0
}
```

---

#### 4. Add Temporal Filters
**Findings**:
- Friday: 64.1% success (BEST)
- 4-8 AM UTC: 67-69% success (BEST)
- Wednesday: 19.4% success (WORST)

**Implementation**:
1. Add `hour_of_day` and `day_of_week` to signals table
2. Add confidence boost for Friday signals
3. Add confidence boost for 4-8 AM UTC signals
4. Optionally: Filter out Wednesday signals entirely

---

#### 5. Create Pair Blacklist/Whitelist
**Top Performers** (100% success):
- ROSEUSDT, ZECUSDT, ARUSDT, 1INCHUSDT, DASHUSDT, etc.

**Worst Performers** (0% success):
- MKRUSDT, PENDLEUSDT, OMGUSDT, etc.

**Implementation**:
1. Create `pump.pair_filters` table
2. Add whitelist logic (boost confidence for top performers)
3. Add blacklist logic (reduce confidence or skip worst performers)

---

### LOW PRIORITY

#### 6. Add Unit Tests for Utility Scripts
#### 7. Centralize Configuration (use pump.config table)
#### 8. Create Web API for Calibration
#### 9. Move monitor_dashboard to Web API
#### 10. Add Email Reports
#### 11. Add Structured Logging

---

## 🔧 CURRENT SYSTEM STATE

### Running Processes
```bash
# Detector Daemon
PID: Unknown (need to check)
Log: /home/elcrypto/pump_detector/logs/detector.log

# Spot Futures Analyzer
PID: 1634726 (running OK, no errors)
Log: /home/elcrypto/pump_detector/logs/spot_futures.log

# Validator Daemon
PID: Unknown (need to check)
Log: /home/elcrypto/pump_detector/logs/validator.log

# Web API
Status: Should be running
Port: 5000 (default Flask)
```

### Data Sources Available
1. **public.candles**: 4h interval data
   - quote_asset_volume: USDT volume (PRIMARY)
   - Both Futures and Spot candles available

2. **public.market_data**: Per-minute OI data
   - open_interest field (futures OI)
   - mark_price field (current futures price)
   - capture_time field (timestamp)
   - 44,331 records for FILUSDT alone

3. **public.trading_pairs**: Pair metadata
   - exchange_id = 1 (Binance)
   - contract_type_id: 1=Futures, 2=Spot
   - is_active, is_stablecoin filters

---

## 📊 STATISTICS (From Deep Research)

### Current Performance
- Total Signals: 541 completed
- Successful Pumps: 186 (34.4%)
- Failed Signals: 355 (65.6%)

### By Strength
| Strength | Count | Success Rate |
|----------|-------|--------------|
| EXTREME  | 95    | 71.6% ✅     |
| STRONG   | 178   | 26.4%        |
| MEDIUM   | 172   | 25.6%        |
| WEAK     | 96    | 28.1%        |

### Key Insights
- EXTREME signals (spike ≥10.0x) are VERY reliable
- Lower tiers need threshold optimization
- Temporal patterns are strong (day/hour matters)
- OI and Spot data critical for improving accuracy

---

## 🎯 NEXT IMMEDIATE STEP

**Task**: Implement OI data collection in detector_daemon.py using public.market_data table

**Why This First**:
1. Blocks calibrate_scoring.py fix
2. Adds 20% scoring weight currently missing
3. Critical data for improving detection accuracy

**Approach**:
1. Study how market_data table is structured
2. Create helper function to query current OI
3. Add OI collection to detector signal creation
4. Test on FILUSDT first
5. Deploy to all pairs

---

## 📝 NOTES

- ARCHITECTURE_REBUILD_PLAN.md suggests full rebuild on FILUSDT first
- Current approach: Fix critical issues incrementally
- spot_futures_analyzer now working, should start collecting spot sync data
- Need to monitor logs for next 10-20 minutes to verify no new errors

---

**Document Owner**: Claude Code
**Location**: /home/elcrypto/pump_detector/docs/CURRENT_STATUS.md
