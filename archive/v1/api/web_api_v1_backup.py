#!/usr/bin/env python3
"""
Web API for Pump Detection System
Provides RESTful endpoints for accessing signals and analytics
"""

from flask import Flask, jsonify, request, render_template, send_from_directory, url_for, make_response
from flask_cors import CORS
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import sys
import os
import json
from functools import wraps
import hashlib
import time
from datetime import datetime as dt_datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DATABASE, WEB_API

# Version for cache busting
STATIC_VERSION = str(int(time.time()))

# Configure Flask app with template and static directories
app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates'),
            static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static'))
CORS(app, origins=WEB_API.get('cors_origins', ['*']))

@app.context_processor
def inject_version():
    """Inject version into all templates"""
    return {'version': STATIC_VERSION}

@app.after_request
def add_cache_headers(response):
    """Add cache control headers to prevent caching"""
    if 'static' in request.path or request.path.endswith('.js') or request.path.endswith('.css'):
        # Force no-cache for static files
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response

# Simple API key authentication
API_KEYS = {
    'default_key': hashlib.sha256(b'pump_detector_api').hexdigest()
}

def require_api_key(f):
    """Decorator to require API key for endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')

        if not api_key or api_key not in API_KEYS.values():
            return jsonify({'error': 'Invalid or missing API key'}), 401

        return f(*args, **kwargs)
    return decorated_function

def get_db_connection():
    """Get database connection"""
    if not DATABASE.get('password'):
        conn_params = {
            'dbname': DATABASE['dbname'],
            'cursor_factory': RealDictCursor
        }
    else:
        conn_params = DATABASE.copy()
        conn_params['cursor_factory'] = RealDictCursor

    return psycopg2.connect(**conn_params)

def serialize_datetime(obj):
    """JSON serializer for datetime objects"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

# Dashboard Routes
@app.route('/')
def index():
    """Serve the main dashboard"""
    return render_template('dashboard.html')

@app.route('/dashboard')
def dashboard():
    """Main dashboard page"""
    return render_template('dashboard.html')

@app.route('/signals')
def signals_page():
    """Active signals monitoring page"""
    from flask import redirect
    import random
    # Force cache bypass with random parameter
    return redirect(f'/signals-v2?v={random.randint(1000,9999)}')

@app.route('/signals-v2')
def signals_page_v2():
    """Active signals monitoring page v2"""
    return render_template('signals_v2.html')

@app.route('/history')
def history_page():
    """Historical signals page"""
    return render_template('history.html')

@app.route('/analytics')
def analytics_page():
    """Analytics and statistics page"""
    return render_template('analytics.html')

@app.route('/config')
def config_page():
    """Configuration page"""
    return render_template('config.html')

@app.route('/reports')
def reports_page():
    """Reports and exports page"""
    return render_template('reports.html')

@app.route('/test')
def test_page():
    """Test page without cache"""
    return render_template('test_signals.html')

@app.route('/static/<path:path>')
def send_static(path):
    """Serve static files"""
    return send_from_directory(app.static_folder, path)

@app.route('/api/v1/status', methods=['GET'])
def get_status():
    """Get system status"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # System health check
            cur.execute("SELECT 1")

            # Get statistics for 24 hours
            cur.execute("""
                SELECT
                    COUNT(*) as total_signals,
                    COUNT(*) FILTER (WHERE status = 'DETECTED') as active_detected,
                    COUNT(*) FILTER (WHERE status = 'MONITORING') as active_monitoring,
                    COUNT(*) FILTER (WHERE pump_realized OR max_price_increase > 10) as total_pumps,
                    MAX(detected_at) as last_signal_time
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL '24 hours'
            """)

            stats = cur.fetchone()

            # Also get 7-day statistics for better perspective
            cur.execute("""
                SELECT
                    COUNT(*) as total_signals_7d,
                    COUNT(*) FILTER (WHERE pump_realized OR max_price_increase > 10) as total_pumps_7d,
                    AVG(max_price_increase) FILTER (WHERE max_price_increase IS NOT NULL) as avg_gain
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL '7 days'
            """)

            stats_7d = cur.fetchone()

        conn.close()

        return jsonify({
            'status': 'online',
            'timestamp': datetime.now().isoformat(),
            'statistics': {
                'signals_24h': stats['total_signals'],
                'active_signals': stats['active_detected'] + stats['active_monitoring'],
                'pumps_24h': stats['total_pumps'],
                'last_signal': stats['last_signal_time'].isoformat() if stats['last_signal_time'] else None,
                'signals_7d': stats_7d['total_signals_7d'],
                'pumps_7d': stats_7d['total_pumps_7d'],
                'avg_gain_7d': float(stats_7d['avg_gain']) if stats_7d['avg_gain'] else 0
            }
        })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/v1/signals/active', methods=['GET'])
def get_active_signals():
    """Get currently active signals"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Get only the latest signal per pair
            cur.execute("""
                WITH latest_signals AS (
                    SELECT
                        s.*,
                        sc.total_score,
                        ROW_NUMBER() OVER (
                            PARTITION BY s.pair_symbol
                            ORDER BY s.signal_timestamp DESC
                        ) as rn
                    FROM pump.signals s
                    LEFT JOIN pump.signal_scores sc ON s.id = sc.signal_id
                    WHERE s.status IN ('DETECTED', 'MONITORING')
                )
                SELECT
                    id,
                    pair_symbol,
                    signal_timestamp,
                    detected_at,
                    status,
                    signal_strength,
                    futures_spike_ratio_7d,
                    futures_spike_ratio_14d,
                    futures_spike_ratio_30d as futures_oi_spike_ratio,
                    initial_confidence,
                    max_price_increase,
                    total_score,
                    EXTRACT(HOUR FROM (NOW() - signal_timestamp)) as hours_old
                FROM latest_signals
                WHERE rn = 1
                ORDER BY signal_timestamp DESC
                LIMIT 100
            """)

            signals = cur.fetchall()

        conn.close()

        return jsonify({
            'count': len(signals),
            'signals': [dict(s) for s in signals]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/signals/<int:signal_id>', methods=['GET'])
def get_signal_detail(signal_id):
    """Get detailed information about a specific signal"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Get signal details
            cur.execute("""
                SELECT s.*, sc.*
                FROM pump.signals s
                LEFT JOIN pump.signal_scores sc ON s.id = sc.signal_id
                WHERE s.id = %s
            """, (signal_id,))

            signal = cur.fetchone()

            if not signal:
                return jsonify({'error': 'Signal not found'}), 404

            # Get confirmations
            cur.execute("""
                SELECT *
                FROM pump.signal_confirmations
                WHERE signal_id = %s
                ORDER BY confirmation_timestamp DESC
            """, (signal_id,))

            confirmations = cur.fetchall()

            # Get price tracking
            cur.execute("""
                SELECT *
                FROM pump.signal_tracking
                WHERE signal_id = %s
                ORDER BY tracking_timestamp DESC
                LIMIT 50
            """, (signal_id,))

            tracking = cur.fetchall()

        conn.close()

        return jsonify({
            'signal': dict(signal),
            'confirmations': [dict(c) for c in confirmations],
            'price_tracking': [dict(t) for t in tracking]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/signals/history', methods=['GET'])
def get_signal_history():
    """Get historical signals with filtering"""
    try:
        # Parse query parameters
        days = int(request.args.get('days', 7))
        status = request.args.get('status')
        strength = request.args.get('strength')
        pair = request.args.get('pair')
        limit = min(int(request.args.get('limit', 100)), 500)

        conn = get_db_connection()
        with conn.cursor() as cur:
            query = """
                SELECT
                    s.id,
                    s.pair_symbol,
                    s.signal_timestamp,
                    s.detected_at,
                    s.status,
                    s.signal_strength,
                    s.futures_spike_ratio_7d,
                    s.initial_confidence,
                    s.pump_realized,
                    s.max_price_increase
                FROM pump.signals s
                WHERE s.detected_at >= NOW() - INTERVAL %s
            """

            params = [f'{days} days']

            if status:
                query += " AND s.status = %s"
                params.append(status)

            if strength:
                query += " AND s.signal_strength = %s"
                params.append(strength)

            if pair:
                query += " AND s.pair_symbol = %s"
                params.append(pair)

            query += " ORDER BY s.signal_timestamp DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            signals = cur.fetchall()

        conn.close()

        return jsonify({
            'count': len(signals),
            'filters': {
                'days': days,
                'status': status,
                'strength': strength,
                'pair': pair
            },
            'signals': [dict(s) for s in signals]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/analytics/performance', methods=['GET'])
@require_api_key
def get_performance_analytics():
    """Get performance analytics"""
    try:
        days = int(request.args.get('days', 7))

        conn = get_db_connection()
        with conn.cursor() as cur:
            # Overall performance
            cur.execute("""
                SELECT
                    COUNT(*) as total_signals,
                    COUNT(*) FILTER (WHERE pump_realized) as successful_pumps,
                    ROUND(COUNT(*) FILTER (WHERE pump_realized)::numeric /
                          NULLIF(COUNT(*), 0) * 100, 2) as success_rate,
                    ROUND(AVG(max_price_increase), 2) as avg_pump_size,
                    ROUND(MAX(max_price_increase), 2) as max_pump_size
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL %s
            """, (f'{days} days',))

            overall = cur.fetchone()

            # Performance by strength
            cur.execute("""
                SELECT
                    signal_strength,
                    COUNT(*) as count,
                    ROUND(COUNT(*) FILTER (WHERE pump_realized)::numeric /
                          NULLIF(COUNT(*), 0) * 100, 2) as accuracy
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL %s
                  AND signal_strength IS NOT NULL
                GROUP BY signal_strength
                ORDER BY signal_strength
            """, (f'{days} days',))

            by_strength = cur.fetchall()

            # Top performing pairs
            cur.execute("""
                SELECT
                    pair_symbol,
                    COUNT(*) as signals,
                    COUNT(*) FILTER (WHERE pump_realized) as pumps,
                    ROUND(AVG(max_price_increase), 2) as avg_gain
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL %s
                GROUP BY pair_symbol
                HAVING COUNT(*) >= 2
                ORDER BY COUNT(*) FILTER (WHERE pump_realized) DESC
                LIMIT 10
            """, (f'{days} days',))

            top_pairs = cur.fetchall()

        conn.close()

        return jsonify({
            'period_days': days,
            'overall': dict(overall) if overall else {},
            'by_strength': [dict(s) for s in by_strength],
            'top_pairs': [dict(p) for p in top_pairs]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/statistics', methods=['GET'])
def get_statistics():
    """Get dashboard statistics for charts"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Get hourly signal counts for the last 24 hours
            cur.execute("""
                SELECT
                    EXTRACT(HOUR FROM signal_timestamp)::int as hour,
                    COUNT(*) as count
                FROM pump.signals
                WHERE signal_timestamp >= NOW() - INTERVAL '24 hours'
                GROUP BY EXTRACT(HOUR FROM signal_timestamp)
                ORDER BY hour
            """)

            hourly_data = cur.fetchall()
            hourly_signals = {str(row['hour']): row['count'] for row in hourly_data}

            # Fill missing hours with 0
            for hour in range(24):
                if str(hour) not in hourly_signals:
                    hourly_signals[str(hour)] = 0

            # Get strength distribution
            cur.execute("""
                SELECT
                    signal_strength,
                    COUNT(*) as count
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL '24 hours'
                  AND signal_strength IS NOT NULL
                GROUP BY signal_strength
            """)

            strength_data = cur.fetchall()
            strength_distribution = {row['signal_strength']: row['count'] for row in strength_data}

        conn.close()

        return jsonify({
            'hourly_signals': hourly_signals,
            'strength_distribution': strength_distribution
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/analytics/correlations', methods=['GET'])
@require_api_key
def get_correlations():
    """Get correlation data between spot and futures"""
    try:
        hours = int(request.args.get('hours', 24))

        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                WITH synchronized_signals AS (
                    SELECT
                        s.pair_symbol,
                        s.signal_timestamp,
                        s.futures_spike_ratio_7d,
                        s.spot_volume_change_pct,
                        s.spot_futures_correlation,
                        s.pump_realized
                    FROM pump.signals s
                    WHERE s.signal_timestamp >= NOW() - INTERVAL %s
                      AND s.spot_volume_change_pct IS NOT NULL
                )
                SELECT
                    COUNT(*) as total_synchronized,
                    COUNT(*) FILTER (WHERE pump_realized) as successful,
                    ROUND(AVG(spot_futures_correlation), 3) as avg_correlation,
                    ROUND(AVG(futures_spike_ratio_7d), 2) as avg_futures_spike,
                    ROUND(AVG(spot_volume_change_pct), 2) as avg_spot_change
                FROM synchronized_signals
            """, (f'{hours} hours',))

            sync_stats = cur.fetchone()

        conn.close()

        return jsonify({
            'period_hours': hours,
            'synchronization': dict(sync_stats) if sync_stats else {}
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/alerts/recent', methods=['GET'])
@require_api_key
def get_recent_alerts():
    """Get recent high-confidence alerts"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    s.id,
                    s.pair_symbol,
                    s.signal_timestamp,
                    s.signal_strength,
                    s.futures_spike_ratio_7d,
                    sc.total_score as confidence_score,
                    'HIGH_CONFIDENCE' as alert_type
                FROM pump.signals s
                LEFT JOIN pump.signal_scores sc ON s.id = sc.signal_id
                WHERE s.status IN ('DETECTED', 'MONITORING')
                  AND s.signal_timestamp >= NOW() - INTERVAL '4 hours'
                  AND (s.signal_strength IN ('EXTREME', 'STRONG')
                       OR sc.total_score >= 70)
                ORDER BY s.signal_timestamp DESC
                LIMIT 20
            """)

            alerts = cur.fetchall()

        conn.close()

        return jsonify({
            'count': len(alerts),
            'alerts': [dict(a) for a in alerts]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/config', methods=['GET'])
@require_api_key
def get_config():
    """Get current system configuration"""
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT key, value, description, updated_at
                FROM pump.config
                ORDER BY key
            """)

            config = cur.fetchall()

        conn.close()

        return jsonify({
            'configuration': [dict(c) for c in config]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/health', methods=['GET'])
def health_check():
    """Simple health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'pump_detector_api'
    })

@app.route('/cache-clear', methods=['GET'])
def cache_clear():
    """Page to help users clear their cache"""
    global STATIC_VERSION
    STATIC_VERSION = str(int(time.time()))

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Clear Cache - Pump Detection System</title>
        <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
        <meta http-equiv="Pragma" content="no-cache">
        <meta http-equiv="Expires" content="0">
        <style>
            body {{
                background: #1a1a1a;
                color: #c9d1d9;
                font-family: Arial, sans-serif;
                padding: 50px;
                text-align: center;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: #0d1117;
                border: 1px solid #30363d;
                border-radius: 10px;
                padding: 30px;
            }}
            h1 {{ color: #58a6ff; }}
            .button {{
                display: inline-block;
                margin: 10px;
                padding: 12px 24px;
                background: #238636;
                color: white;
                text-decoration: none;
                border-radius: 6px;
                font-size: 16px;
            }}
            .button:hover {{ background: #2ea043; }}
            .instructions {{
                background: #161b22;
                padding: 20px;
                border-radius: 6px;
                margin: 20px 0;
                text-align: left;
            }}
            code {{
                background: #30363d;
                padding: 2px 6px;
                border-radius: 3px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔄 Cache Cleared!</h1>
            <p>Static file version updated to: <strong>{STATIC_VERSION}</strong></p>

            <div class="instructions">
                <h3>Now clear your browser cache:</h3>
                <ol>
                    <li><strong>Chrome/Edge:</strong> Press <code>Ctrl+Shift+R</code> (Windows) or <code>Cmd+Shift+R</code> (Mac)</li>
                    <li><strong>Firefox:</strong> Press <code>Ctrl+F5</code> (Windows) or <code>Cmd+Shift+R</code> (Mac)</li>
                    <li><strong>Safari:</strong> Press <code>Cmd+Option+R</code></li>
                </ol>

                <h3>Or do a full cache clear:</h3>
                <ol>
                    <li>Press <code>F12</code> to open Developer Tools</li>
                    <li>Right-click the refresh button</li>
                    <li>Select "Empty Cache and Hard Reload"</li>
                </ol>
            </div>

            <div style="margin-top: 30px;">
                <a href="/dashboard" class="button">Go to Dashboard</a>
                <a href="/signals-v2" class="button">Go to Signals</a>
                <a href="/test" class="button">Test Page</a>
            </div>

            <p style="margin-top: 30px; color: #8b949e;">
                If you still see old data, try opening the site in an Incognito/Private window.
            </p>
        </div>
    </body>
    </html>
    """

    response = make_response(html)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.errorhandler(404)
def not_found(error):
    """404 error handler"""
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    """500 error handler"""
    return jsonify({'error': 'Internal server error'}), 500

def main():
    """Main function"""
    print(f"🚀 Starting Pump Detector API on {WEB_API['host']}:{WEB_API['port']}")
    print(f"📝 API Documentation: http://{WEB_API['host']}:{WEB_API['port']}/api/v1/status")
    print(f"🔑 Default API Key: {list(API_KEYS.values())[0]}")

    app.run(
        host=WEB_API['host'],
        port=WEB_API['port'],
        debug=True
    )

if __name__ == "__main__":
    main()