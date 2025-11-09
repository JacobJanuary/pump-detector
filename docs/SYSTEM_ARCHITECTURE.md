# Pump Detection System - Architecture Documentation

## Overview

The Pump Detection System is a multi-daemon cryptocurrency trading anomaly detection system designed to identify and track unusual volume spikes (pumps) in Binance futures markets. The system uses time-series analysis, statistical methods, and multi-factor scoring to detect, validate, and monitor pump events.

## System Components

### 1. Core Daemons

The system consists of three independent daemons that work together:

#### 1.1 Detector Daemon (`detector_daemon.py`)
- **Purpose**: Primary anomaly detection engine
- **Interval**: Every 5 minutes
- **Function**: Scans 4-hour candle data for volume spikes
- **Output**: New signals saved to `pump.signals` table

**Key Responsibilities**:
- Query candles from `public.candles` table (4h interval, Binance Futures)
- Calculate rolling baselines (7-day, 14-day, 30-day moving averages)
- Compute spike ratios (current_volume / baseline)
- Classify signals (EXTREME, STRONG, MEDIUM, WEAK)
- Calculate initial confidence scores
- Save signals to database

#### 1.2 Validator Daemon (`validator_daemon.py`)
- **Purpose**: Signal validation and price tracking
- **Interval**: Every 15 minutes
- **Function**: Monitors price movements after signal detection
- **Output**: Updates signal status and tracking data

**Key Responsibilities**:
- Track price movement for DETECTED and MONITORING signals
- Calculate max gain%, current gain%, drawdown%
- Update signal status based on price action:
  - `DETECTED` → `MONITORING` (after 4 hours)
  - `MONITORING` → `CONFIRMED` (if price rises ≥10%)
  - `MONITORING` → `FAILED` (if expired >7 days or drawdown >15%)
- Record tracking data in `pump.signal_tracking`
- Recalculate confidence scores

#### 1.3 Spot-Futures Analyzer (`spot_futures_analyzer.py`)
- **Purpose**: Cross-market correlation analysis
- **Interval**: Every 10 minutes
- **Function**: Detects synchronized pumps across spot and futures markets
- **Output**: Updates signals with spot correlation data

**Key Responsibilities**:
- Compare futures signals with spot market activity
- Identify synchronized volume spikes
- Calculate spot spike ratios
- Update signals with `has_spot_sync` and `spot_spike_ratio_7d`
- Record confirmations in `pump.signal_confirmations`

### 2. Database Schema

#### 2.1 Core Tables

```
pump.signals
├── Detection Data (volume, baselines, spike ratios)
├── Signal Classification (strength, confidence)
├── Price Tracking (entry price, max increase)
└── Status Management (status, timestamps)

pump.signal_tracking
├── Time-series price data
├── Volume ratios
├── OI changes
└── Confidence updates

pump.signal_confirmations
├── Confirmation types
├── Timestamps
└── Supporting data

pump.signal_scores
├── Multi-factor breakdown
├── Total score
└── Confidence level
```

### 3. Web API

#### 3.1 Flask API (`api/web_api.py`)
- **Purpose**: HTTP REST API for external access
- **Port**: 2537
- **Mode**: Development (Flask built-in server)

**Endpoints**:
- `GET /` - Dashboard HTML
- `GET /api/v1/status` - System status
- `GET /api/v1/signals/active` - Active signals
- `GET /api/v1/signals/history` - Historical signals
- `GET /api/v1/statistics` - System statistics

## Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                                  │
│   public.candles (4h Binance Futures) + trading_pairs            │
└────────────────────────┬─────────────────────────────────────────┘
                         │
                         ↓
┌──────────────────────────────────────────────────────────────────┐
│              DETECTOR DAEMON (Every 5 min)                        │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ 1. Query recent 4h candles                                │  │
│  │ 2. Calculate baselines (7d/14d/30d moving averages)       │  │
│  │ 3. Compute spike ratios (volume / baseline)               │  │
│  │ 4. Classify signal strength                               │  │
│  │ 5. Calculate initial confidence                           │  │
│  │ 6. Save to pump.signals                                   │  │
│  └────────────────────────────────────────────────────────────┘  │
└────────────────────────┬─────────────────────────────────────────┘
                         │
                         ↓
┌──────────────────────────────────────────────────────────────────┐
│                    pump.signals                                   │
│         (Status: DETECTED, initial_confidence: 30-75)            │
└───────┬──────────────────────────────────────────────────────────┘
        │
        ├────────────────────────────────────┐
        │                                    │
        ↓                                    ↓
┌───────────────────────────────┐  ┌────────────────────────────────┐
│  VALIDATOR DAEMON             │  │ SPOT-FUTURES ANALYZER          │
│  (Every 15 min)               │  │ (Every 10 min)                 │
│  ┌─────────────────────────┐  │  │ ┌──────────────────────────┐  │
│  │ 1. Get DETECTED/        │  │  │ │ 1. Get recent signals    │  │
│  │    MONITORING signals   │  │  │ │ 2. Check spot volume     │  │
│  │ 2. Track price changes  │  │  │ │ 3. Calculate spot ratios │  │
│  │ 3. Calculate gains/     │  │  │ │ 4. Update signals with   │  │
│  │    drawdowns            │  │  │ │    spot_sync data        │  │
│  │ 4. Update status:       │  │  │ │ 5. Record confirmations  │  │
│  │    • CONFIRMED (≥10%)   │  │  │ └──────────────────────────┘  │
│  │    • FAILED (expired)   │  │  └────────────┬───────────────────┘
│  │ 5. Record tracking      │  │               │
│  │ 6. Update confidence    │  │               │
│  └─────────────────────────┘  │               │
└───────────┬───────────────────┘               │
            │                                   │
            ↓                                   ↓
┌───────────────────────┐           ┌─────────────────────────┐
│ pump.signal_tracking  │           │ pump.signal_confirmations│
│ (Time-series data)    │           │ (Correlation data)       │
└───────────────────────┘           └──────────────────────────┘
            │
            ↓
┌──────────────────────────────────────────────────────────────────┐
│              pump.calculate_confidence_score()                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Multi-factor scoring:                                     │  │
│  │ • Volume Score (0-25): Based on spike ratio               │  │
│  │ • OI Score (0-25): Based on OI change%                    │  │
│  │ • Spot Sync Score (0-20): Spot/futures correlation        │  │
│  │ • Confirmation Score (0-20): Number of confirmations      │  │
│  │ • Timing Score (0-10): Time decay factor                  │  │
│  │ Total: 0-100                                              │  │
│  └────────────────────────────────────────────────────────────┘  │
└────────────────────────┬─────────────────────────────────────────┘
                         │
                         ↓
              ┌──────────────────────┐
              │ pump.signal_scores   │
              │ (Confidence breakdown)│
              └──────────────────────┘
                         │
                         ↓
┌──────────────────────────────────────────────────────────────────┐
│                    WEB API (Flask)                                │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Endpoints:                                                │  │
│  │ • GET /api/v1/signals/active                             │  │
│  │ • GET /api/v1/signals/history                            │  │
│  │ • GET /api/v1/statistics                                 │  │
│  │ • GET /dashboard (HTML)                                  │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

## Signal Lifecycle

```
┌─────────┐
│ CANDLE  │  Volume spike detected
│  DATA   │
└────┬────┘
     │
     ↓
┌──────────┐
│ DETECTED │  Initial detection, saved to DB
└────┬─────┘
     │
     │ (4 hours later)
     ↓
┌────────────┐
│ MONITORING │  Active price tracking
└──┬────┬────┘
   │    │
   │    │ (7 days, no pump)
   │    └──────────────────┐
   │                       │
   │ (price ≥ +10%)        │ (drawdown > 15%)
   │                       │
   ↓                       ↓
┌──────────┐         ┌─────────┐
│CONFIRMED │         │ FAILED  │
└──────────┘         └─────────┘
   │                       │
   │                       │
   └───────────┬───────────┘
               │
               ↓
           [ARCHIVED]
```

## Configuration

### Detection Parameters (`config/settings.py`)

```python
DETECTION = {
    'interval_minutes': 5,         # Detector cycle time
    'lookback_hours': 4,           # How far back to check for new signals
    'min_spike_ratio': 1.5,        # Minimum threshold for detection
    'extreme_spike_ratio': 5.0,    # EXTREME classification
    'strong_spike_ratio': 3.0,     # STRONG classification
    'medium_spike_ratio': 2.0,     # MEDIUM classification
    'timeframe': '4h',             # Candle interval
    'pump_threshold_pct': 10,      # % gain to confirm pump
    'monitoring_hours': 168,       # 7 days monitoring period
}

SCORING = {
    'volume_weight': 0.25,         # 25% weight
    'oi_weight': 0.25,             # 25% weight
    'spot_sync_weight': 0.20,      # 20% weight
    'confirmation_weight': 0.20,   # 20% weight
    'timing_weight': 0.10,         # 10% weight
}
```

## Deployment

### Process Management

The system uses systemd for process management:

```bash
# Detector
systemctl start pump-detector
systemctl enable pump-detector

# Validator
systemctl start pump-validator
systemctl enable pump-validator

# Spot-Futures Analyzer
systemctl start pump-spot-futures
systemctl enable pump-spot-futures

# Web API
systemctl start pump-web-api
systemctl enable pump-web-api
```

### Monitoring

Logs are written to `/home/elcrypto/pump_detector/logs/`:
- `detector.log` - Detection daemon logs
- `validator.log` - Validation daemon logs
- `spot_futures.log` - Analyzer daemon logs
- `web_api.log` - API server logs

### Maintenance

#### Cron Jobs (`/tmp/crontab_backup`)

```cron
# Daily calibration at 2 AM
0 2 * * * cd /home/elcrypto/pump_detector && python3 scripts/calibrate_scoring.py

# Weekly report generation (Sunday at 3 AM)
0 3 * * 0 cd /home/elcrypto/pump_detector && python3 scripts/generate_reports.py

# Hourly OI data tracking
0 * * * * psql -d fox_crypto_new -c "SELECT pump.track_oi_changes();"

# Daily cleanup of old signals (keep 30 days)
0 4 * * * psql -d fox_crypto_new -c "DELETE FROM pump.signal_tracking WHERE check_timestamp < NOW() - INTERVAL '30 days';"

# Backup database daily at 5 AM
0 5 * * * pg_dump -d fox_crypto_new -n pump -f /home/elcrypto/pump_detector/backups/pump_$(date +\%Y\%m\%d).sql
```

## Performance Characteristics

### Resource Usage

- **Detector**: ~50MB RAM, <1% CPU (idle), 5-10% CPU (active)
- **Validator**: ~40MB RAM, <1% CPU (idle), 3-5% CPU (active)
- **Analyzer**: ~35MB RAM, <1% CPU (idle), 2-4% CPU (active)
- **Web API**: ~60MB RAM, <1% CPU (idle)

### Database Load

- **Detector**: 1 SELECT query (50-100 rows) + 1-50 INSERT queries per cycle
- **Validator**: 1 SELECT query (10-100 rows) + 10-100 UPDATE queries per cycle
- **Analyzer**: 2 SELECT queries + occasional UPDATE queries per cycle

### Processing Times

- **Detector cycle**: 2-5 seconds
- **Validator cycle**: 5-15 seconds
- **Analyzer cycle**: 1-3 seconds

## Validation

The system includes a comprehensive validation script (`scripts/validate_signals.py`) that independently recalculates all metrics from source data to verify accuracy.

**Validation Results** (10 random signals tested):
- **100% accuracy** on volume calculations
- **100% accuracy** on baseline calculations
- **100% accuracy** on spike ratio calculations
- **100% accuracy** on signal strength classification

## Future Enhancements

1. **Real-time Notifications**: Telegram/Discord bot integration
2. **Machine Learning**: Pattern recognition for pump prediction
3. **Multi-Exchange Support**: Expand beyond Binance
4. **Advanced Analytics**: Correlation analysis, market regime detection
5. **API Rate Limiting**: Throttling and authentication
6. **Historical Backtesting**: Performance analysis on historical data

## Dependencies

- Python 3.8+
- PostgreSQL 12+
- psycopg2
- Flask (for Web API)
- Standard library: logging, datetime, signal, time

## Security Considerations

1. **Database Access**: Peer authentication for local connections
2. **API Security**: Currently no authentication (development mode)
3. **Input Validation**: All database queries use parameterized statements
4. **Error Handling**: Graceful degradation with retry logic

## Troubleshooting

### Common Issues

1. **Detector not finding signals**: Check if candles table is up-to-date
2. **Validator not updating status**: Verify price data availability
3. **Confidence scores not calculating**: Check if calculate_confidence_score() function exists

### Debug Commands

```bash
# Check daemon status
ps aux | grep -E 'detector|validator|spot_futures'

# View recent logs
tail -f /home/elcrypto/pump_detector/logs/*.log

# Test database connection
psql -d fox_crypto_new -c "SELECT COUNT(*) FROM pump.signals;"

# Run validation script
cd /home/elcrypto/pump_detector
./venv/bin/python3 scripts/validate_signals.py --random 10
```

---

**Last Updated**: 2025-11-07
**Version**: 1.0
**Author**: Automated Analysis System
