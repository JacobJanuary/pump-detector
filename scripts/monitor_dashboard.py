#!/usr/bin/env python3
"""
Simple monitoring dashboard for pump detection system
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import sys
import os
import time
import argparse

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DATABASE

# ANSI color codes
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
MAGENTA = '\033[95m'
CYAN = '\033[96m'
WHITE = '\033[97m'
RESET = '\033[0m'
BOLD = '\033[1m'

def connect():
    """Connect to database"""
    if not DATABASE.get('password'):
        conn_params = {
            'dbname': DATABASE['dbname'],
            'cursor_factory': RealDictCursor
        }
    else:
        conn_params = {
            'dbname': DATABASE['dbname'],
            'user': DATABASE.get('user'),
            'password': DATABASE.get('password'),
            'host': DATABASE.get('host', 'localhost'),
            'port': DATABASE.get('port', 5432),
            'cursor_factory': RealDictCursor
        }

    return psycopg2.connect(**conn_params)

def clear_screen():
    """Clear terminal screen"""
    os.system('clear' if os.name == 'posix' else 'cls')

def print_header():
    """Print dashboard header"""
    print(f"{CYAN}{BOLD}{'='*80}{RESET}")
    print(f"{CYAN}{BOLD}{'PUMP DETECTION SYSTEM DASHBOARD'.center(80)}{RESET}")
    print(f"{CYAN}{BOLD}{'='*80}{RESET}")
    print(f"{WHITE}Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print()

def get_system_stats(conn):
    """Get overall system statistics"""
    with conn.cursor() as cur:
        # Overall stats
        cur.execute("""
            SELECT
                COUNT(*) as total_signals,
                COUNT(*) FILTER (WHERE status = 'DETECTED') as detected,
                COUNT(*) FILTER (WHERE status = 'MONITORING') as monitoring,
                COUNT(*) FILTER (WHERE status = 'CONFIRMED') as confirmed,
                COUNT(*) FILTER (WHERE status = 'FAILED') as failed,
                COUNT(*) FILTER (WHERE pump_realized = TRUE) as pumps,
                AVG(max_price_increase) FILTER (WHERE pump_realized = TRUE) as avg_pump_size
            FROM pump.signals
            WHERE detected_at >= NOW() - INTERVAL '7 days'
        """)

        return cur.fetchone()

def get_active_signals(conn):
    """Get currently active signals"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                s.pair_symbol,
                s.signal_timestamp,
                s.signal_strength,
                s.futures_spike_ratio_7d,
                s.futures_spike_ratio_14d,
                s.status,
                s.max_price_increase,
                s.initial_confidence,
                sc.total_score,
                EXTRACT(HOUR FROM (NOW() - s.signal_timestamp)) as hours_old
            FROM pump.signals s
            LEFT JOIN pump.signal_scores sc ON s.id = sc.signal_id
            WHERE s.status IN ('DETECTED', 'MONITORING')
            ORDER BY s.signal_timestamp DESC
            LIMIT 10
        """)

        return cur.fetchall()

def get_recent_pumps(conn):
    """Get recently confirmed pumps"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                pair_symbol,
                detected_at,
                signal_strength,
                futures_spike_ratio_7d,
                max_price_increase,
                EXTRACT(HOUR FROM (signal_timestamp - detected_at)) as detection_lag_hours
            FROM pump.signals
            WHERE status = 'CONFIRMED'
              AND pump_realized = TRUE
              AND detected_at >= NOW() - INTERVAL '24 hours'
            ORDER BY detected_at DESC
            LIMIT 5
        """)

        return cur.fetchall()

def get_top_performers(conn):
    """Get top performing pairs"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                pair_symbol,
                COUNT(*) as signal_count,
                COUNT(*) FILTER (WHERE pump_realized = TRUE) as pump_count,
                ROUND(
                    COUNT(*) FILTER (WHERE pump_realized = TRUE)::numeric /
                    NULLIF(COUNT(*), 0) * 100, 1
                ) as success_rate,
                ROUND(AVG(max_price_increase) FILTER (WHERE pump_realized = TRUE), 1) as avg_pump_size
            FROM pump.signals
            WHERE detected_at >= NOW() - INTERVAL '7 days'
            GROUP BY pair_symbol
            HAVING COUNT(*) >= 2
            ORDER BY success_rate DESC, pump_count DESC
            LIMIT 5
        """)

        return cur.fetchall()

def format_signal_strength(strength):
    """Format signal strength with color"""
    colors = {
        'EXTREME': RED + BOLD,
        'STRONG': YELLOW + BOLD,
        'MEDIUM': BLUE,
        'WEAK': WHITE
    }
    return f"{colors.get(strength, WHITE)}{strength:8}{RESET}"

def format_percentage(value, threshold=10):
    """Format percentage with color based on threshold"""
    if value is None:
        return f"{WHITE}{'N/A':>6}{RESET}"

    if value >= threshold:
        color = GREEN + BOLD
    elif value >= threshold / 2:
        color = YELLOW
    else:
        color = WHITE

    return f"{color}{value:>6.1f}%{RESET}"

def display_dashboard(conn, refresh_interval=30):
    """Display the monitoring dashboard"""

    while True:
        try:
            clear_screen()
            print_header()

            # System statistics
            stats = get_system_stats(conn)

            print(f"{BOLD}📊 SYSTEM STATISTICS (Last 7 Days){RESET}")
            print(f"{'-'*80}")

            if stats:
                success_rate = (stats['pumps'] / stats['total_signals'] * 100) if stats['total_signals'] > 0 else 0

                print(f"Total Signals: {GREEN}{stats['total_signals']:>4}{RESET} | "
                      f"Detected: {YELLOW}{stats['detected']:>3}{RESET} | "
                      f"Monitoring: {BLUE}{stats['monitoring']:>3}{RESET} | "
                      f"Confirmed: {GREEN}{stats['confirmed']:>3}{RESET} | "
                      f"Failed: {RED}{stats['failed']:>3}{RESET}")

                print(f"Success Rate: {format_percentage(success_rate)} | "
                      f"Avg Pump Size: {format_percentage(stats['avg_pump_size'])}")

            print()

            # Active signals
            active = get_active_signals(conn)

            print(f"{BOLD}🔍 ACTIVE SIGNALS{RESET}")
            print(f"{'-'*80}")

            if active:
                print(f"{'Symbol':<10} {'Age':>5} {'Strength':<10} {'7d Spike':>8} {'14d Spike':>9} "
                      f"{'Confidence':>10} {'Score':>6} {'Gain':>6}")
                print(f"{'-'*80}")

                for signal in active:
                    print(f"{signal['pair_symbol']:<10} "
                          f"{signal['hours_old']:>3.0f}h "
                          f"{format_signal_strength(signal['signal_strength'])} "
                          f"{signal['futures_spike_ratio_7d']:>7.1f}x "
                          f"{signal['futures_spike_ratio_14d'] or 0:>8.1f}x "
                          f"{signal['initial_confidence']:>9}% "
                          f"{signal['total_score'] or 0:>6.0f} "
                          f"{format_percentage(signal['max_price_increase'] or 0, 5)}")
            else:
                print(f"{WHITE}No active signals currently{RESET}")

            print()

            # Recent pumps
            pumps = get_recent_pumps(conn)

            print(f"{BOLD}🚀 RECENT CONFIRMED PUMPS (24h){RESET}")
            print(f"{'-'*80}")

            if pumps:
                print(f"{'Symbol':<10} {'Time':<20} {'Strength':<10} {'Spike':>8} {'Gain':>8}")
                print(f"{'-'*80}")

                for pump in pumps:
                    print(f"{pump['pair_symbol']:<10} "
                          f"{pump['detected_at'].strftime('%Y-%m-%d %H:%M'):<20} "
                          f"{format_signal_strength(pump['signal_strength'])} "
                          f"{pump['futures_spike_ratio_7d']:>7.1f}x "
                          f"{format_percentage(pump['max_price_increase'])}")
            else:
                print(f"{WHITE}No confirmed pumps in last 24 hours{RESET}")

            print()

            # Top performers
            top = get_top_performers(conn)

            print(f"{BOLD}🏆 TOP PERFORMING PAIRS (7 Days){RESET}")
            print(f"{'-'*80}")

            if top:
                print(f"{'Symbol':<10} {'Signals':>8} {'Pumps':>6} {'Success':>9} {'Avg Size':>10}")
                print(f"{'-'*80}")

                for pair in top:
                    print(f"{pair['pair_symbol']:<10} "
                          f"{pair['signal_count']:>8} "
                          f"{pair['pump_count']:>6} "
                          f"{format_percentage(pair['success_rate'])} "
                          f"{format_percentage(pair['avg_pump_size'])}")
            else:
                print(f"{WHITE}No performance data available{RESET}")

            print()
            print(f"{'-'*80}")
            print(f"{WHITE}Refreshing in {refresh_interval} seconds... (Press Ctrl+C to exit){RESET}")

            time.sleep(refresh_interval)

        except KeyboardInterrupt:
            print(f"\n{YELLOW}Dashboard stopped by user{RESET}")
            break
        except Exception as e:
            print(f"\n{RED}Error: {e}{RESET}")
            print(f"{YELLOW}Retrying in {refresh_interval} seconds...{RESET}")
            time.sleep(refresh_interval)

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Pump Detection System Dashboard')
    parser.add_argument(
        '--refresh',
        type=int,
        default=30,
        help='Refresh interval in seconds (default: 30)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Display once and exit (no refresh)'
    )

    args = parser.parse_args()

    print(f"{CYAN}Connecting to database...{RESET}")
    conn = connect()

    try:
        if args.once:
            clear_screen()
            print_header()
            # Display once
            stats = get_system_stats(conn)
            # ... (display other sections)
            print(f"\n{GREEN}Dashboard display complete{RESET}")
        else:
            display_dashboard(conn, args.refresh)
    finally:
        conn.close()

if __name__ == "__main__":
    main()