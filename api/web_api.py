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
            # Get candidate info with market cap and CMC rank
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
                    c.cmc_token_id
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

        conn.close()

        # Simple HTML page with candidate details
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{symbol} - Candidate Details</title>
    <style>
        body {{ font-family: Arial; max-width: 1400px; margin: 50px auto; padding: 20px; }}
        h1 {{ color: #1e3c72; }}
        h2 {{ color: #2a5298; margin-top: 30px; }}
        .detail {{ margin: 15px 0; padding: 10px; background: #f5f5f5; border-radius: 5px; }}
        .label {{ font-weight: bold; color: #555; }}
        .value {{ color: #333; }}
        .badge {{ padding: 5px 15px; border-radius: 15px; color: white; display: inline-block; }}
        .high {{ background: #4CAF50; }}
        .medium {{ background: #FF9800; }}
        .actionable {{ background: #2196F3; }}
        .back {{ display: inline-block; margin-top: 20px; padding: 10px 20px; background: #1e3c72; color: white; text-decoration: none; border-radius: 5px; }}

        .signals-table {{ width: 100%; border-collapse: collapse; margin-top: 20px; background: white; }}
        .signals-table th {{ background: #1e3c72; color: white; padding: 12px; text-align: left; font-weight: 600; }}
        .signals-table td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
        .signals-table tr:hover {{ background: #f5f5f5; }}
        .signal-type {{ display: inline-block; padding: 4px 10px; border-radius: 10px; font-size: 0.85em; font-weight: 600; }}
        .type-spot {{ background: #4CAF50; color: white; }}
        .type-futures {{ background: #2196F3; color: white; }}
        .strength {{ display: inline-block; padding: 4px 10px; border-radius: 10px; font-size: 0.85em; font-weight: 600; }}
        .strength-extreme {{ background: #f44336; color: white; }}
        .strength-very-strong {{ background: #FF9800; color: white; }}
        .strength-strong {{ background: #FFC107; color: #333; }}
        .strength-medium {{ background: #9E9E9E; color: white; }}
        .spike-high {{ color: #f44336; font-weight: bold; }}
        .spike-medium {{ color: #FF9800; font-weight: bold; }}
        .baseline-info {{ color: #666; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>{symbol} - Pump Candidate Details</h1>

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
            'ACTIONABLE - Ready to Trade' if candidate['is_actionable'] else 'Watch Only'
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
        <span class="label">Critical Window Signals:</span>
        <span class="value">{candidate['critical_window_signals']}</span>
    </div>

    <div class="detail">
        <span class="label">ETA:</span>
        <span class="value">{candidate['eta_hours']}h</span>
    </div>

    <div class="detail">
        <span class="label">Pattern Time Range:</span>
        <span class="value">{pattern_info['pattern_start']} - {pattern_info['pattern_end']}</span>
    </div>

    <div class="detail">
        <span class="label">Signals in Pattern:</span>
        <span class="value">{pattern_info['signal_count']} signals from market data</span>
    </div>

    <div class="detail">
        <span class="label">Last Updated:</span>
        <span class="value">{candidate['last_updated_at']}</span>
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
            <a href="https://coinmarketcap.com/currencies/{symbol.replace("USDT", "").lower()}/" target="_blank" style="color: #2196F3;">View on CMC →</a>
        </span>
    </div>

    <h2>Все сигналы по паре {symbol}</h2>
    <table class="signals-table">
        <thead>
            <tr>
                <th>Дата/Время</th>
                <th>Тип</th>
                <th>Сила</th>
                <th>Объем</th>
                <th>Цена</th>
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

        html += """
        </tbody>
    </table>

    <a href="/" class="back">← Back to Dashboard</a>
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
        limit = int(request.args.get('limit', 50))

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
