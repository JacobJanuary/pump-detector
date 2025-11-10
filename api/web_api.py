#!/usr/bin/env python3
"""
Web API V2.0 for Pump Detection System V2.0
Completely replaces old V1 API

Provides RESTful endpoints for:
- Current pump candidates (HIGH confidence)
- Backtest validation metrics
- Signal monitoring
- Engine configuration
"""

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import sys
import os
import json
from pathlib import Path
import requests
from time import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATABASE, WEB_API
from engine.pump_detection_engine import PumpDetectionEngine
from engine.database_helper import PumpDatabaseHelper

# Configure Flask app
app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates'),
            static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'))

CORS(app, origins=WEB_API.get('cors_origins', ['*']))

# Initialize database helper and engine
db_helper = None
detection_engine = None

def get_db_connection():
    """Get PostgreSQL database connection"""
    return psycopg2.connect(**DATABASE, cursor_factory=RealDictCursor)

def init_engine():
    """Initialize detection engine"""
    global db_helper, detection_engine
    try:
        db_helper = PumpDatabaseHelper(DATABASE)
        db_helper.connect()
        detection_engine = PumpDetectionEngine(db_helper)
        app.logger.info("Detection engine initialized successfully")
    except Exception as e:
        app.logger.error(f"Failed to initialize engine: {e}")
        raise

def serialize_datetime(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

# =============================================================================
# DASHBOARD ROUTES
# =============================================================================

@app.route('/')
def index():
    """Main dashboard - pump candidates monitoring"""
    return render_template('pump_dashboard_v2.html')

@app.route('/dashboard')
def dashboard():
    """Main dashboard page"""
    return render_template('pump_dashboard_v2.html')

@app.route('/backtest')
def backtest_page():
    """Backtest results visualization page"""
    return render_template('backtest_results_v2.html')

@app.route('/candidate/<symbol>')
def candidate_details(symbol):
    """Show candidate details page"""
    # Get candidate data from API
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Get candidate info with market cap, CMC rank and slug
            cur.execute("""
                SELECT
                    pc.pair_symbol,
                    pc.trading_pair_id,
                    pc.confidence,
                    pc.score,
                    pc.pattern_type,
                    pc.is_actionable,
                    pc.total_signals,
                    pc.extreme_signals,
                    pc.critical_window_signals,
                    pc.eta_hours,
                    pc.first_detected_at,
                    pc.last_updated_at,
                    pc.status,
                    c.market_cap,
                    c.cmc_rank,
                    c.cmc_token_id,
                    c.slug
                FROM pump.pump_candidates pc
                LEFT JOIN public.trading_pairs tp ON pc.trading_pair_id = tp.id
                LEFT JOIN public.tokens t ON tp.token_id = t.id
                LEFT JOIN public.cmc_crypto c ON t.cmc_token_id = c.cmc_token_id
                WHERE pc.pair_symbol = %s
                  AND pc.status = 'ACTIVE'
                ORDER BY pc.last_updated_at DESC
                LIMIT 1
            """, (symbol,))

            candidate = cur.fetchone()

            if not candidate:
                conn.close()
                return f"<h1>Candidate {symbol} not found</h1><a href='/'>Back to Dashboard</a>", 404

            # Get pattern time range from signals
            cur.execute("""
                SELECT
                    MIN(signal_timestamp) as pattern_start,
                    MAX(signal_timestamp) as pattern_end,
                    COUNT(*) as signal_count
                FROM pump.raw_signals
                WHERE pair_symbol = %s
            """, (symbol,))

            pattern_info = cur.fetchone()

            # Get all signals for this pair
            cur.execute("""
                SELECT
                    signal_timestamp,
                    signal_type,
                    signal_strength,
                    volume,
                    price_at_signal,
                    baseline_7d,
                    baseline_14d,
                    baseline_30d,
                    spike_ratio_7d,
                    spike_ratio_14d,
                    spike_ratio_30d
                FROM pump.raw_signals
                WHERE pair_symbol = %s
                ORDER BY signal_timestamp DESC
            """, (symbol,))

            signals = cur.fetchall()

            # Get technical indicators (4h timeframe)
            cur.execute("""
                SELECT
                    buy_ratio,
                    volume_zscore,
                    oi_delta_pct,
                    timestamp
                FROM fas_v2.indicators
                WHERE trading_pair_id = %s
                  AND timeframe = '4h'
                ORDER BY timestamp DESC
                LIMIT 1
            """, (candidate['trading_pair_id'],))

            indicators = cur.fetchone()

            # Get POC levels
            cur.execute("""
                SELECT
                    poc_24h,
                    poc_7d,
                    poc_30d,
                    calculated_at
                FROM fas_v2.poc_levels
                WHERE trading_pair_id = %s
                ORDER BY calculated_at DESC
                LIMIT 1
            """, (candidate['trading_pair_id'],))

            poc_levels = cur.fetchone()

        conn.close()

        # 2-column HTML page with candidate details and charts
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{symbol} - Candidate Details</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <style>
        body {{ font-family: Arial; margin: 0; padding: 20px; background: #f0f2f5; }}
        h1 {{ color: #1e3c72; margin-bottom: 20px; }}
        .container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; max-width: 1600px; margin: 0 auto; }}

        /* Left panel - Info */
        .info-panel {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .detail {{ margin: 8px 0; padding: 8px; background: #f5f5f5; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; }}
        .label {{ font-weight: 600; color: #555; font-size: 0.9em; }}
        .value {{ color: #333; font-size: 0.9em; }}
        .badge {{ padding: 4px 12px; border-radius: 12px; color: white; font-size: 0.85em; font-weight: 600; }}
        .high {{ background: #4CAF50; }}
        .medium {{ background: #FF9800; }}
        .actionable {{ background: #2196F3; }}

        /* Right panel - Charts */
        .charts-panel {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .chart-container {{ margin-bottom: 30px; height: 300px; position: relative; }}
        .chart-title {{ font-size: 1.1em; font-weight: 600; color: #1e3c72; margin-bottom: 10px; }}

        .back {{ display: inline-block; margin-top: 20px; padding: 10px 20px; background: #1e3c72; color: white; text-decoration: none; border-radius: 5px; }}
        .back:hover {{ background: #2a5298; }}

        /* Signals table */
        .signals-section {{ grid-column: 1 / -1; background: white; padding: 20px; border-radius: 8px; margin-top: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .signals-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        .signals-table th {{ background: #1e3c72; color: white; padding: 10px; text-align: left; font-size: 0.9em; }}
        .signals-table td {{ padding: 8px; border-bottom: 1px solid #ddd; font-size: 0.85em; }}
        .signals-table tr:hover {{ background: #f5f5f5; }}
        .signal-type {{ padding: 3px 8px; border-radius: 8px; font-size: 0.8em; font-weight: 600; }}
        .type-spot {{ background: #4CAF50; color: white; }}
        .type-futures {{ background: #2196F3; color: white; }}
        .strength {{ padding: 3px 8px; border-radius: 8px; font-size: 0.8em; font-weight: 600; }}
        .strength-extreme {{ background: #f44336; color: white; }}
        .strength-very-strong {{ background: #FF9800; color: white; }}
        .strength-strong {{ background: #FFC107; color: #333; }}
        .strength-medium {{ background: #9E9E9E; color: white; }}
        .spike-high {{ color: #f44336; font-weight: bold; }}
        .spike-medium {{ color: #FF9800; font-weight: bold; }}
        .baseline-info {{ color: #666; }}

        /* POC and Indicators section */
        .analytics-section {{ grid-column: 1 / -1; background: white; padding: 20px; border-radius: 8px; margin-top: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .analytics-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 15px; }}
        .analytics-card {{ background: #f9f9f9; padding: 15px; border-radius: 6px; border-left: 4px solid #2196F3; }}
        .analytics-card h3 {{ margin: 0 0 12px 0; color: #1e3c72; font-size: 1em; }}
        .analytics-item {{ display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #e0e0e0; }}
        .analytics-item:last-child {{ border-bottom: none; }}
        .analytics-label {{ font-weight: 600; color: #666; font-size: 0.9em; }}
        .analytics-value {{ color: #333; font-size: 0.9em; font-weight: 600; }}
        .analytics-value.positive {{ color: #4CAF50; }}
        .analytics-value.negative {{ color: #f44336; }}
        .analytics-meta {{ font-size: 0.8em; color: #999; margin-top: 10px; }}
    </style>
</head>
<body>
    <h1><a href="/" style="text-decoration: none; color: #666; font-size: 0.8em; margin-right: 10px;">←</a>{symbol} - Pump Candidate Details</h1>

    <div class="container">
        <!-- Left panel: Candidate info -->
        <div class="info-panel">
            <h2 style="margin-top: 0; color: #1e3c72; font-size: 1.3em;">Candidate Information</h2>

            <div class="detail">
                <span class="label">Confidence:</span>
                <span class="badge {candidate['confidence'].lower()}">{candidate['confidence']}</span>
            </div>

            <div class="detail">
                <span class="label">Score:</span>
                <span class="value">{candidate['score']:.2f}</span>
            </div>

            <div class="detail">
                <span class="label">Pattern Type:</span>
                <span class="value">{candidate['pattern_type']}</span>
            </div>

            <div class="detail">
                <span class="label">Status:</span>
                <span class="badge {'actionable' if candidate['is_actionable'] else ''}">{
                    'ACTIONABLE - Ready' if candidate['is_actionable'] else 'Watch Only'
                }</span>
            </div>

            <div class="detail">
                <span class="label">Total Signals:</span>
                <span class="value">{candidate['total_signals']}</span>
            </div>

            <div class="detail">
                <span class="label">Extreme Signals:</span>
                <span class="value">{candidate['extreme_signals']}</span>
            </div>

            <div class="detail">
                <span class="label">Critical Window:</span>
                <span class="value">{candidate['critical_window_signals']}</span>
            </div>

            <div class="detail">
                <span class="label">ETA:</span>
                <span class="value">{candidate['eta_hours']}h</span>
            </div>

            <div class="detail">
                <span class="label">Market Cap:</span>
                <span class="value">{'$' + f"{candidate['market_cap']:,.0f}" if candidate.get('market_cap') else "N/A"}</span>
            </div>

            <div class="detail">
                <span class="label">CMC Rank:</span>
                <span class="value">{'#' + str(candidate['cmc_rank']) if candidate.get('cmc_rank') else "N/A"}</span>
            </div>

            <div class="detail">
                <span class="label">CoinMarketCap:</span>
                <span class="value">
                    {'<a href="https://coinmarketcap.com/currencies/' + candidate['slug'] + '/" target="_blank" style="color: #2196F3; text-decoration: none;">View →</a>' if candidate.get('slug') else 'N/A'}
                </span>
            </div>

            <div class="detail">
                <span class="label">Pattern Time:</span>
                <span class="value" style="font-size: 0.8em;">{pattern_info['pattern_start'].strftime('%Y-%m-%d %H:%M') if pattern_info['pattern_start'] else 'N/A'}</span>
            </div>

            <div class="detail">
                <span class="label">Last Updated:</span>
                <span class="value" style="font-size: 0.8em;">{candidate['last_updated_at'].strftime('%Y-%m-%d %H:%M') if candidate.get('last_updated_at') else 'N/A'}</span>
            </div>
        </div>

        <!-- Right panel: Charts -->
        <div class="charts-panel">
            <div class="chart-title">Price (Last 30 Days - Hourly)</div>
            <div class="chart-container">
                <canvas id="priceChart"></canvas>
            </div>

            <div class="chart-title" style="margin-top: 40px;">Volume (Last 30 Days - Hourly)</div>
            <div class="chart-container">
                <canvas id="volumeChart"></canvas>
            </div>
        </div>
    </div>

    <!-- Analytics section (POC + Indicators) -->
    <div class="analytics-section">
        <h2 style="margin-top: 0; color: #1e3c72;">Analytics (POC Levels & Technical Indicators)</h2>
        <div class="analytics-grid">
            <!-- POC Levels Card -->
            <div class="analytics-card">
                <h3>POC (Point of Control) Levels</h3>
                {'<div class="analytics-item"><span class="analytics-label">POC 24h:</span><span class="analytics-value">$' + f"{poc_levels['poc_24h']:.8f}" + '</span></div>' if poc_levels and poc_levels.get('poc_24h') else '<p style="color: #999; font-style: italic; margin: 0;">No data</p>'}
                {'<div class="analytics-item"><span class="analytics-label">POC 7d:</span><span class="analytics-value">$' + f"{poc_levels['poc_7d']:.8f}" + '</span></div>' if poc_levels and poc_levels.get('poc_7d') else ''}
                {'<div class="analytics-item"><span class="analytics-label">POC 30d:</span><span class="analytics-value">$' + f"{poc_levels['poc_30d']:.8f}" + '</span></div>' if poc_levels and poc_levels.get('poc_30d') else ''}
                {'<div class="analytics-meta">Updated: ' + poc_levels['calculated_at'].strftime('%Y-%m-%d %H:%M') + '</div>' if poc_levels and poc_levels.get('calculated_at') else ''}
            </div>

            <!-- Technical Indicators Card -->
            <div class="analytics-card">
                <h3>Technical Indicators (4h)</h3>
                {'<div class="analytics-item"><span class="analytics-label">Buy Ratio:</span><span class="analytics-value ' + ('positive' if indicators.get('buy_ratio', 0) > 0.5 else 'negative') + '">' + f"{indicators['buy_ratio']*100:.2f}%" + '</span></div>' if indicators and indicators.get('buy_ratio') is not None else '<p style="color: #999; font-style: italic; margin: 0;">No data</p>'}
                {'<div class="analytics-item"><span class="analytics-label">Volume Z-Score:</span><span class="analytics-value ' + ('positive' if indicators.get('volume_zscore', 0) > 2 else '') + '">' + f"{indicators['volume_zscore']:.2f}" + '</span></div>' if indicators and indicators.get('volume_zscore') is not None else ''}
                {'<div class="analytics-item"><span class="analytics-label">OI Delta %:</span><span class="analytics-value ' + ('positive' if indicators.get('oi_delta_pct', 0) > 0 else 'negative') + '">' + f"{indicators['oi_delta_pct']:.2f}%" + '</span></div>' if indicators and indicators.get('oi_delta_pct') is not None else ''}
                {'<div class="analytics-meta">Updated: ' + indicators['timestamp'].strftime('%Y-%m-%d %H:%M') + '</div>' if indicators and indicators.get('timestamp') else ''}
            </div>
        </div>
    </div>

    <!-- Signals table (full width) -->
    <div class="signals-section">
        <h2 style="margin-top: 0; color: #1e3c72;">All Signals for {symbol}</h2>
        <table class="signals-table">
            <thead>
                <tr>
                    <th>Date/Time</th>
                    <th>Type</th>
                    <th>Strength</th>
                    <th>Volume</th>
                    <th>Price</th>
                    <th>Baseline 7d</th>
                    <th>Baseline 14d</th>
                    <th>Baseline 30d</th>
                    <th>Spike 7d</th>
                    <th>Spike 14d</th>
                    <th>Spike 30d</th>
                </tr>
            </thead>
            <tbody>
"""

        # Generate table rows
        for signal in signals:
            signal_time = signal['signal_timestamp'].strftime('%Y-%m-%d %H:%M') if signal['signal_timestamp'] else 'N/A'
            signal_type_class = 'type-spot' if signal['signal_type'] == 'SPOT' else 'type-futures'

            strength_map = {
                'EXTREME': 'strength-extreme',
                'VERY_STRONG': 'strength-very-strong',
                'STRONG': 'strength-strong',
                'MEDIUM': 'strength-medium'
            }
            strength_class = strength_map.get(signal['signal_strength'], 'strength-medium')

            # Format spike ratios with color coding
            def format_spike(ratio):
                if ratio is None:
                    return 'N/A'
                if ratio >= 3.0:
                    return f'<span class="spike-high">{ratio:.2f}x</span>'
                elif ratio >= 2.0:
                    return f'<span class="spike-medium">{ratio:.2f}x</span>'
                else:
                    return f'{ratio:.2f}x'

            spike_7d = format_spike(signal['spike_ratio_7d'])
            spike_14d = format_spike(signal['spike_ratio_14d'])
            spike_30d = format_spike(signal['spike_ratio_30d'])

            # Format volume and price
            volume_str = f"{signal['volume']:,.0f}" if signal['volume'] else 'N/A'
            price_str = f"{signal['price_at_signal']:.8f}" if signal['price_at_signal'] else 'N/A'
            baseline_7d_str = f"{signal['baseline_7d']:,.0f}" if signal['baseline_7d'] else 'N/A'
            baseline_14d_str = f"{signal['baseline_14d']:,.0f}" if signal['baseline_14d'] else 'N/A'
            baseline_30d_str = f"{signal['baseline_30d']:,.0f}" if signal['baseline_30d'] else 'N/A'

            html += f'''
            <tr>
                <td>{signal_time}</td>
                <td><span class="signal-type {signal_type_class}">{signal['signal_type']}</span></td>
                <td><span class="strength {strength_class}">{signal['signal_strength']}</span></td>
                <td>{volume_str}</td>
                <td>{price_str}</td>
                <td><span class="baseline-info">{baseline_7d_str}</span></td>
                <td><span class="baseline-info">{baseline_14d_str}</span></td>
                <td><span class="baseline-info">{baseline_30d_str}</span></td>
                <td>{spike_7d}</td>
                <td>{spike_14d}</td>
                <td>{spike_30d}</td>
            </tr>
            '''

        html += f"""
            </tbody>
        </table>
    </div>

    <a href="/" class="back">← Back to Dashboard</a>

    <script>
    // Fetch Binance klines and render charts
    async function loadCharts() {{
        try {{
            const response = await fetch('/api/v2/binance/klines/{symbol}?interval=1h&limit=720');
            const data = await response.json();

            if (!data.success) {{
                console.error('Failed to load Binance data:', data.error);
                return;
            }}

            const candles = data.candles;
            const labels = candles.map(c => {{
                const date = new Date(c.timestamp);
                return date.toLocaleDateString('en-US', {{ month: 'short', day: 'numeric' }});
            }});
            const prices = candles.map(c => c.close);
            const volumes = candles.map(c => c.quote_volume);

            // Price Chart
            const priceCtx = document.getElementById('priceChart').getContext('2d');
            new Chart(priceCtx, {{
                type: 'line',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Price (USDT)',
                        data: prices,
                        borderColor: '#2196F3',
                        backgroundColor: 'rgba(33, 150, 243, 0.1)',
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.1,
                        fill: true
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            display: true,
                            position: 'top'
                        }},
                        tooltip: {{
                            mode: 'index',
                            intersect: false
                        }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{
                                display: false
                            }},
                            ticks: {{
                                maxTicksLimit: 15
                            }}
                        }},
                        y: {{
                            grid: {{
                                color: '#e0e0e0'
                            }},
                            ticks: {{
                                callback: function(value) {{
                                    return '$' + value.toFixed(2);
                                }}
                            }}
                        }}
                    }}
                }}
            }});

            // Volume Chart
            const volumeCtx = document.getElementById('volumeChart').getContext('2d');
            new Chart(volumeCtx, {{
                type: 'bar',
                data: {{
                    labels: labels,
                    datasets: [{{
                        label: 'Volume (USDT)',
                        data: volumes,
                        backgroundColor: 'rgba(76, 175, 80, 0.6)',
                        borderColor: '#4CAF50',
                        borderWidth: 1
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{
                            display: true,
                            position: 'top'
                        }},
                        tooltip: {{
                            mode: 'index',
                            intersect: false,
                            callbacks: {{
                                label: function(context) {{
                                    let label = context.dataset.label || '';
                                    if (label) {{
                                        label += ': ';
                                    }}
                                    label += '$' + context.parsed.y.toLocaleString();
                                    return label;
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{
                                display: false
                            }},
                            ticks: {{
                                maxTicksLimit: 15
                            }}
                        }},
                        y: {{
                            grid: {{
                                color: '#e0e0e0'
                            }},
                            ticks: {{
                                callback: function(value) {{
                                    return '$' + (value / 1000000).toFixed(1) + 'M';
                                }}
                            }}
                        }}
                    }}
                }}
            }});

        }} catch (error) {{
            console.error('Error loading charts:', error);
        }}
    }}

    // Load charts on page load
    document.addEventListener('DOMContentLoaded', loadCharts);
    </script>
</body>
</html>
"""
        return html

    except Exception as e:
        app.logger.error(f"Error fetching candidate details: {e}")
        return f"<h1>Error loading {symbol}</h1><p>{str(e)}</p><a href='/'>Back</a>", 500

# =============================================================================
# API V2.0 ENDPOINTS - PUMP CANDIDATES
# =============================================================================

@app.route('/api/v2/candidates', methods=['GET'])
def get_candidates():
    """
    Get current HIGH confidence pump candidates

    Query Parameters:
    - min_confidence: Minimum confidence (HIGH, MEDIUM, LOW) - default: HIGH
    - actionable_only: Return only actionable candidates - default: true
    - limit: Max number of results - default: 50

    Returns:
    - List of pump candidates with scores, signals, ETA
    """
    try:
        min_confidence = request.args.get('min_confidence', 'HIGH').upper()
        actionable_only = request.args.get('actionable_only', 'true').lower() == 'true'
        limit = int(request.args.get('limit', 1000))

        conn = get_db_connection()
        with conn.cursor() as cur:
            query = """
                SELECT
                    pair_symbol,
                    confidence,
                    score,
                    pattern_type,
                    is_actionable,
                    total_signals,
                    extreme_signals,
                    critical_window_signals,
                    eta_hours,
                    first_detected_at,
                    last_updated_at,
                    status,
                    pump_phase,
                    price_change_from_first,
                    price_change_24h,
                    hours_since_last_pump,
                    actual_price,
                    price_updated_at
                FROM pump.pump_candidates
                WHERE status = 'ACTIVE'
            """
            params = []

            # Filter by confidence
            if min_confidence == 'HIGH':
                query += " AND confidence = 'HIGH'"
            elif min_confidence == 'MEDIUM':
                query += " AND confidence IN ('HIGH', 'MEDIUM')"

            # Filter actionable
            if actionable_only:
                query += " AND is_actionable = true"

            # Order by score
            query += " ORDER BY score DESC, last_updated_at DESC"

            # Limit
            query += f" LIMIT {limit}"

            cur.execute(query, params)
            candidates = cur.fetchall()

        conn.close()

        # Convert to list of dicts
        results = []
        for row in candidates:
            results.append({
                'symbol': row['pair_symbol'],
                'confidence': row['confidence'],
                'score': float(row['score']) if row['score'] else 0,
                'pattern_type': row['pattern_type'],
                'is_actionable': row['is_actionable'],
                'total_signals': row['total_signals'],
                'extreme_signals': row['extreme_signals'],
                'critical_window_signals': row['critical_window_signals'],
                'eta_hours': row['eta_hours'],
                'first_detected_at': row['first_detected_at'].isoformat() if row['first_detected_at'] else None,
                'last_updated_at': row['last_updated_at'].isoformat() if row['last_updated_at'] else None,
                'status': row['status'],
                'pump_phase': row['pump_phase'],
                'price_change_from_first': float(row['price_change_from_first']) if row['price_change_from_first'] is not None else None,
                'price_change_24h': float(row['price_change_24h']) if row['price_change_24h'] is not None else None,
                'hours_since_last_pump': row['hours_since_last_pump'],
                'actual_price': float(row['actual_price']) if row['actual_price'] is not None else None,
                'price_updated_at': row['price_updated_at'].isoformat() if row['price_updated_at'] else None
            })

        return jsonify({
            'success': True,
            'count': len(results),
            'candidates': results,
            'filters': {
                'min_confidence': min_confidence,
                'actionable_only': actionable_only,
                'limit': limit
            }
        })

    except Exception as e:
        app.logger.error(f"Error fetching candidates: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/v2/candidates/<symbol>', methods=['GET'])
def get_candidate_details(symbol):
    """
    Get detailed analysis for specific symbol

    Returns:
    - Candidate information
    - Recent signals (last 7 days)
    - Signal breakdown by type
    - Pattern analysis
    """
    try:
        symbol = symbol.upper()

        # Get candidate info
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    pair_symbol,
                    confidence,
                    score,
                    pattern_type,
                    is_actionable,
                    total_signals,
                    extreme_signals,
                    critical_window_signals,
                    eta_hours,
                    first_detected_at,
                    last_updated_at,
                    status
                FROM pump.pump_candidates
                WHERE pair_symbol = %s
                  AND status = 'ACTIVE'
                ORDER BY last_updated_at DESC
                LIMIT 1
            """, (symbol,))

            candidate = cur.fetchone()

            if not candidate:
                return jsonify({
                    'success': False,
                    'error': f'No active candidate found for {symbol}'
                }), 404

            # Get recent signals
            cur.execute("""
                SELECT
                    signal_type,
                    signal_timestamp,
                    spike_ratio_7d,
                    signal_strength,
                    volume,
                    price_at_signal
                FROM pump.raw_signals
                WHERE pair_symbol = %s
                  AND signal_timestamp >= NOW() - INTERVAL '7 days'
                ORDER BY signal_timestamp DESC
            """, (symbol,))

            signals = cur.fetchall()

        conn.close()

        # Format signals
        signal_list = []
        for sig in signals:
            signal_list.append({
                'type': sig['signal_type'],
                'timestamp': sig['signal_timestamp'].isoformat(),
                'spike_ratio': float(sig['spike_ratio_7d']) if sig['spike_ratio_7d'] else 0,
                'strength': sig['signal_strength'],
                'volume': float(sig['volume']) if sig['volume'] else 0,
                'price': float(sig['price_at_signal']) if sig['price_at_signal'] else 0
            })

        # Signal breakdown by type
        signal_breakdown = {}
        for sig in signals:
            sig_type = sig['signal_type']
            if sig_type not in signal_breakdown:
                signal_breakdown[sig_type] = 0
            signal_breakdown[sig_type] += 1

        return jsonify({
            'success': True,
            'symbol': symbol,
            'candidate': {
                'confidence': candidate['confidence'],
                'score': float(candidate['score']) if candidate['score'] else 0,
                'pattern_type': candidate['pattern_type'],
                'is_actionable': candidate['is_actionable'],
                'total_signals': candidate['total_signals'],
                'extreme_signals': candidate['extreme_signals'],
                'critical_window_signals': candidate['critical_window_signals'],
                'eta_hours': candidate['eta_hours'],
                'first_detected_at': candidate['first_detected_at'].isoformat() if candidate['first_detected_at'] else None,
                'last_updated_at': candidate['last_updated_at'].isoformat() if candidate['last_updated_at'] else None,
                'status': candidate['status']
            },
            'signals': {
                'count': len(signal_list),
                'recent': signal_list[:20],  # Last 20 signals
                'breakdown': signal_breakdown
            }
        })

    except Exception as e:
        app.logger.error(f"Error fetching candidate details for {symbol}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# =============================================================================
# API V2.0 ENDPOINTS - BACKTEST METRICS
# =============================================================================

@app.route('/api/v2/backtest/metrics', methods=['GET'])
def get_backtest_metrics():
    """
    Get backtest validation metrics

    Returns:
    - Overall metrics (Precision, Recall, F1, Accuracy)
    - Detection rate by time window
    - Performance by confidence level
    - Performance by pattern type
    """
    try:
        # Load from JSON file (generated by backtest engine)
        metrics_file = Path('/tmp/pump_analysis/backtest_metrics.json')

        if metrics_file.exists():
            with open(metrics_file, 'r') as f:
                metrics = json.load(f)

            return jsonify({
                'success': True,
                'metrics': metrics,
                'source': 'cached'
            })
        else:
            # Calculate from database
            conn = get_db_connection()
            with conn.cursor() as cur:
                # Overall metrics
                cur.execute("""
                    SELECT
                        classification,
                        COUNT(*) as count
                    FROM pump.backtest_results
                    GROUP BY classification
                """)

                classification_counts = {row['classification']: row['count']
                                       for row in cur.fetchall()}

                tp = classification_counts.get('TP', 0)
                fp = classification_counts.get('FP', 0)
                fn = classification_counts.get('FN', 0)
                tn = classification_counts.get('TN', 0)

                precision = tp / (tp + fp) if (tp + fp) > 0 else 0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0
                f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
                accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0

                # Metrics by time window
                cur.execute("""
                    SELECT
                        hours_before_pump,
                        COUNT(*) as total,
                        SUM(CASE WHEN was_detected THEN 1 ELSE 0 END) as detected,
                        SUM(CASE WHEN is_actionable THEN 1 ELSE 0 END) as actionable
                    FROM pump.backtest_results
                    GROUP BY hours_before_pump
                    ORDER BY hours_before_pump DESC
                """)

                window_metrics = []
                for row in cur.fetchall():
                    window_metrics.append({
                        'hours_before': row['hours_before_pump'],
                        'total': row['total'],
                        'detected': row['detected'],
                        'actionable': row['actionable'],
                        'detection_rate': row['detected'] / row['total'] if row['total'] > 0 else 0
                    })

                # Metrics by confidence
                cur.execute("""
                    SELECT
                        confidence,
                        COUNT(*) as count,
                        AVG(score) as avg_score,
                        SUM(CASE WHEN is_actionable THEN 1 ELSE 0 END) as actionable_count
                    FROM pump.backtest_results
                    WHERE was_detected = true
                    GROUP BY confidence
                    ORDER BY
                        CASE confidence
                            WHEN 'HIGH' THEN 1
                            WHEN 'MEDIUM' THEN 2
                            WHEN 'LOW' THEN 3
                        END
                """)

                confidence_metrics = []
                for row in cur.fetchall():
                    confidence_metrics.append({
                        'confidence': row['confidence'],
                        'count': row['count'],
                        'avg_score': float(row['avg_score']) if row['avg_score'] else 0,
                        'actionable_count': row['actionable_count']
                    })

                # Metrics by pattern
                cur.execute("""
                    SELECT
                        pattern_type,
                        COUNT(*) as count,
                        AVG(score) as avg_score
                    FROM pump.backtest_results
                    WHERE was_detected = true
                    GROUP BY pattern_type
                    ORDER BY count DESC
                """)

                pattern_metrics = []
                for row in cur.fetchall():
                    pattern_metrics.append({
                        'pattern_type': row['pattern_type'],
                        'count': row['count'],
                        'avg_score': float(row['avg_score']) if row['avg_score'] else 0
                    })

            conn.close()

            metrics = {
                'overall': {
                    'tp': tp,
                    'fp': fp,
                    'fn': fn,
                    'tn': tn,
                    'precision': precision,
                    'recall': recall,
                    'f1_score': f1,
                    'accuracy': accuracy
                },
                'by_time_window': window_metrics,
                'by_confidence': confidence_metrics,
                'by_pattern': pattern_metrics
            }

            return jsonify({
                'success': True,
                'metrics': metrics,
                'source': 'database'
            })

    except Exception as e:
        app.logger.error(f"Error fetching backtest metrics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/v2/backtest/results', methods=['GET'])
def get_backtest_results():
    """
    Get detailed backtest results

    Query Parameters:
    - symbol: Filter by symbol
    - hours_before: Filter by time window
    - detected_only: Show only detected pumps
    - actionable_only: Show only actionable detections
    - limit: Max results - default: 100

    Returns:
    - List of backtest results with details
    """
    try:
        symbol = request.args.get('symbol', '').upper()
        hours_before = request.args.get('hours_before', type=int)
        detected_only = request.args.get('detected_only', 'false').lower() == 'true'
        actionable_only = request.args.get('actionable_only', 'false').lower() == 'true'
        limit = int(request.args.get('limit', 100))

        conn = get_db_connection()
        with conn.cursor() as cur:
            query = """
                SELECT
                    br.pair_symbol,
                    br.hours_before_pump,
                    br.was_detected,
                    br.confidence,
                    br.score,
                    br.pattern_type,
                    br.is_actionable,
                    br.total_signals,
                    br.extreme_signals,
                    br.critical_window_signals,
                    br.eta_hours,
                    br.classification,
                    br.analysis_time,
                    kp.pump_start,
                    kp.max_gain_24h
                FROM pump.backtest_results br
                JOIN pump.known_pump_events kp ON br.known_pump_id = kp.id
                WHERE 1=1
            """
            params = []

            if symbol:
                query += " AND br.pair_symbol = %s"
                params.append(symbol)

            if hours_before:
                query += " AND br.hours_before_pump = %s"
                params.append(hours_before)

            if detected_only:
                query += " AND br.was_detected = true"

            if actionable_only:
                query += " AND br.is_actionable = true"

            query += " ORDER BY br.score DESC NULLS LAST, br.analysis_time DESC"
            query += f" LIMIT {limit}"

            cur.execute(query, params)
            results = cur.fetchall()

        conn.close()

        # Format results
        backtest_results = []
        for row in results:
            backtest_results.append({
                'symbol': row['pair_symbol'],
                'hours_before_pump': row['hours_before_pump'],
                'was_detected': row['was_detected'],
                'confidence': row['confidence'],
                'score': float(row['score']) if row['score'] else 0,
                'pattern_type': row['pattern_type'],
                'is_actionable': row['is_actionable'],
                'total_signals': row['total_signals'],
                'extreme_signals': row['extreme_signals'],
                'critical_window_signals': row['critical_window_signals'],
                'eta_hours': row['eta_hours'],
                'classification': row['classification'],
                'analysis_time': row['analysis_time'].isoformat() if row['analysis_time'] else None,
                'pump_start': row['pump_start'].isoformat() if row['pump_start'] else None,
                'max_gain': float(row['max_gain_24h']) if row['max_gain_24h'] else 0
            })

        return jsonify({
            'success': True,
            'count': len(backtest_results),
            'results': backtest_results,
            'filters': {
                'symbol': symbol or 'all',
                'hours_before': hours_before or 'all',
                'detected_only': detected_only,
                'actionable_only': actionable_only
            }
        })

    except Exception as e:
        app.logger.error(f"Error fetching backtest results: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# =============================================================================
# API V2.0 ENDPOINTS - SIGNALS
# =============================================================================

@app.route('/api/v2/signals/recent', methods=['GET'])
def get_recent_signals():
    """
    Get recent raw signals

    Query Parameters:
    - symbol: Filter by symbol
    - signal_type: Filter by signal type
    - hours: Lookback period in hours - default: 24
    - limit: Max results - default: 100

    Returns:
    - List of recent signals
    """
    try:
        symbol = request.args.get('symbol', '').upper()
        signal_type = request.args.get('signal_type', '').upper()
        hours = int(request.args.get('hours', 24))
        limit = int(request.args.get('limit', 100))

        conn = get_db_connection()
        with conn.cursor() as cur:
            query = """
                SELECT
                    pair_symbol,
                    signal_type,
                    signal_timestamp,
                    spike_ratio_7d,
                    signal_strength,
                    volume,
                    price_at_signal,
                    baseline_7d,
                    baseline_14d,
                    baseline_30d
                FROM pump.raw_signals
                WHERE signal_timestamp >= NOW() - INTERVAL '%s hours'
            """
            params = [hours]

            if symbol:
                query += " AND pair_symbol = %s"
                params.append(symbol)

            if signal_type:
                query += " AND signal_type = %s"
                params.append(signal_type)

            query += " ORDER BY signal_timestamp DESC"
            query += f" LIMIT {limit}"

            cur.execute(query, params)
            signals = cur.fetchall()

        conn.close()

        # Format signals
        signal_list = []
        for row in signals:
            signal_list.append({
                'symbol': row['pair_symbol'],
                'type': row['signal_type'],
                'timestamp': row['signal_timestamp'].isoformat(),
                'spike_ratio': float(row['spike_ratio_7d']) if row['spike_ratio_7d'] else 0,
                'strength': row['signal_strength'],
                'volume': float(row['volume']) if row['volume'] else 0,
                'price': float(row['price_at_signal']) if row['price_at_signal'] else 0,
                'baseline_7d': float(row['baseline_7d']) if row['baseline_7d'] else 0,
                'baseline_14d': float(row['baseline_14d']) if row['baseline_14d'] else 0,
                'baseline_30d': float(row['baseline_30d']) if row['baseline_30d'] else 0
            })

        return jsonify({
            'success': True,
            'count': len(signal_list),
            'signals': signal_list,
            'filters': {
                'symbol': symbol or 'all',
                'signal_type': signal_type or 'all',
                'hours': hours,
                'limit': limit
            }
        })

    except Exception as e:
        app.logger.error(f"Error fetching recent signals: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# =============================================================================
# API V2.0 ENDPOINTS - CONFIGURATION & HEALTH
# =============================================================================

@app.route('/api/v2/config', methods=['GET'])
def get_config():
    """
    Get current detection engine configuration

    Returns:
    - Engine thresholds and parameters
    """
    try:
        if detection_engine is None:
            init_engine()

        config = {
            'version': '2.0',
            'thresholds': {
                'min_signal_count': detection_engine.min_signal_count,
                'high_confidence': detection_engine.high_conf_threshold,
                'medium_confidence': detection_engine.medium_conf_threshold,
                'critical_window_min_signals': detection_engine.critical_window_min_signals
            },
            'parameters': {
                'lookback_days': 7,
                'critical_window_hours': [48, 72],
                'extreme_spike_threshold': 5.0,
                'strong_spike_threshold': 3.0
            }
        }

        return jsonify({
            'success': True,
            'config': config
        })

    except Exception as e:
        app.logger.error(f"Error fetching config: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/v2/health', methods=['GET'])
def health_check():
    """
    System health check

    Returns:
    - Database connection status
    - Engine status
    - Recent activity statistics
    """
    try:
        # Check database
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Check raw_signals
            cur.execute("""
                SELECT
                    COUNT(*) as total_signals,
                    COUNT(DISTINCT pair_symbol) as unique_symbols,
                    MAX(signal_timestamp) as latest_signal
                FROM pump.raw_signals
                WHERE signal_timestamp >= NOW() - INTERVAL '24 hours'
            """)
            signals_stats = cur.fetchone()

            # Check pump_candidates
            cur.execute("""
                SELECT
                    COUNT(*) as active_candidates,
                    SUM(CASE WHEN confidence = 'HIGH' THEN 1 ELSE 0 END) as high_confidence,
                    SUM(CASE WHEN is_actionable THEN 1 ELSE 0 END) as actionable
                FROM pump.pump_candidates
                WHERE status = 'ACTIVE'
            """)
            candidates_stats = cur.fetchone()

        conn.close()

        # Check engine
        engine_status = 'initialized' if detection_engine else 'not_initialized'

        return jsonify({
            'success': True,
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database': {
                'connected': True,
                'signals_24h': signals_stats['total_signals'],
                'monitored_symbols': signals_stats['unique_symbols'],
                'latest_signal': signals_stats['latest_signal'].isoformat() if signals_stats['latest_signal'] else None
            },
            'candidates': {
                'active': candidates_stats['active_candidates'] or 0,
                'high_confidence': candidates_stats['high_confidence'] or 0,
                'actionable': candidates_stats['actionable'] or 0
            },
            'engine': {
                'status': engine_status,
                'version': '2.0'
            }
        })

    except Exception as e:
        app.logger.error(f"Health check failed: {e}")
        return jsonify({
            'success': False,
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# =============================================================================
# BINANCE API PROXY
# =============================================================================

@app.route('/api/v2/binance/klines/<symbol>', methods=['GET'])
def get_binance_klines(symbol):
    """
    Fetch historical kline data from Binance API

    Query Parameters:
    - interval: Kline interval (default: 1h)
    - limit: Number of candles (default: 720 = 30 days of hourly candles)

    Returns:
    - List of OHLCV candles with timestamps
    """
    try:
        symbol = symbol.upper()
        interval = request.args.get('interval', '1h')
        limit = int(request.args.get('limit', 720))  # 30 days * 24 hours

        # Binance API endpoint
        url = 'https://api.binance.com/api/v3/klines'
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': min(limit, 1000)  # Binance max is 1000
        }

        response = requests.get(url, params=params, timeout=10)

        if response.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'Binance API error: {response.status_code}'
            }), response.status_code

        klines = response.json()

        # Format candles for frontend
        candles = []
        for k in klines:
            candles.append({
                'timestamp': k[0],  # Open time
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
                'quote_volume': float(k[7])
            })

        return jsonify({
            'success': True,
            'symbol': symbol,
            'interval': interval,
            'count': len(candles),
            'candles': candles
        })

    except requests.RequestException as e:
        app.logger.error(f"Binance API request failed: {e}")
        return jsonify({
            'success': False,
            'error': f'Binance API request failed: {str(e)}'
        }), 500
    except Exception as e:
        app.logger.error(f"Error fetching Binance klines: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'Endpoint not found',
        'message': 'Check API documentation for available endpoints'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': 'Internal server error',
        'message': str(error)
    }), 500

# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    import logging

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize engine
    try:
        init_engine()
        app.logger.info("Pump Detection Engine V2.0 - Web API initialized")
    except Exception as e:
        app.logger.error(f"Failed to initialize: {e}")

    # Run Flask app
    host = WEB_API.get('host', '0.0.0.0')
    port = WEB_API.get('port', 5000)
    debug = WEB_API.get('debug', False)

    app.logger.info(f"Starting Web API V2.0 on {host}:{port}")
    app.run(host=host, port=port, debug=debug)
