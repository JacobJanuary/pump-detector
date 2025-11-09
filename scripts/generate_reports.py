#!/usr/bin/env python3
"""
Performance Reporting System
Generates comprehensive reports on pump detection performance
"""

import psycopg2
from psycopg2.extras import RealDictCursor
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import DATABASE

class ReportGenerator:
    """Generates performance and analysis reports"""

    def __init__(self):
        self.conn = self.connect()
        self.report_dir = "/tmp/pump_detector/reports"
        os.makedirs(self.report_dir, exist_ok=True)

        # Set style for plots
        sns.set_style("whitegrid")
        plt.rcParams['figure.figsize'] = (12, 6)

    def connect(self):
        """Connect to database"""
        if not DATABASE.get('password'):
            conn_params = {
                'dbname': DATABASE['dbname'],
                'cursor_factory': RealDictCursor
            }
        else:
            conn_params = DATABASE.copy()
            conn_params['cursor_factory'] = RealDictCursor

        return psycopg2.connect(**conn_params)

    def generate_daily_report(self, date=None):
        """Generate daily performance report"""

        if date is None:
            date = datetime.now().date()

        print(f"📊 Generating Daily Report for {date}")
        print("="*60)

        report = {
            'date': str(date),
            'generated_at': datetime.now().isoformat(),
            'metrics': {}
        }

        # 1. Signal Statistics
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_signals,
                    COUNT(*) FILTER (WHERE status = 'DETECTED') as detected,
                    COUNT(*) FILTER (WHERE status = 'MONITORING') as monitoring,
                    COUNT(*) FILTER (WHERE status = 'CONFIRMED') as confirmed,
                    COUNT(*) FILTER (WHERE status = 'FAILED') as failed,
                    AVG(futures_spike_ratio_7d) as avg_spike_ratio,
                    MAX(futures_spike_ratio_7d) as max_spike_ratio
                FROM pump.signals
                WHERE DATE(detected_at) = %s
            """, (date,))

            daily_stats = cur.fetchone()
            report['metrics']['daily_signals'] = dict(daily_stats) if daily_stats else {}

            # 2. Success Rate by Hour
            cur.execute("""
                SELECT
                    EXTRACT(HOUR FROM signal_timestamp) as hour,
                    COUNT(*) as signals,
                    COUNT(*) FILTER (WHERE pump_realized) as pumps,
                    ROUND(AVG(max_price_increase), 2) as avg_gain
                FROM pump.signals
                WHERE DATE(detected_at) = %s
                GROUP BY EXTRACT(HOUR FROM signal_timestamp)
                ORDER BY hour
            """, (date,))

            hourly_data = cur.fetchall()
            report['metrics']['hourly_performance'] = [dict(row) for row in hourly_data]

            # 3. Top Performers
            cur.execute("""
                SELECT
                    pair_symbol,
                    futures_spike_ratio_7d,
                    max_price_increase,
                    signal_strength,
                    status
                FROM pump.signals
                WHERE DATE(detected_at) = %s
                  AND pump_realized = TRUE
                ORDER BY max_price_increase DESC
                LIMIT 10
            """, (date,))

            top_pumps = cur.fetchall()
            report['metrics']['top_pumps'] = [dict(row) for row in top_pumps]

        # Generate visualizations
        self._plot_daily_performance(report, date)

        # Save report
        report_path = os.path.join(self.report_dir, f"daily_report_{date}.json")
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        print(f"✅ Daily report saved to: {report_path}")
        return report

    def generate_weekly_report(self):
        """Generate weekly performance analysis"""

        print("\n📈 Generating Weekly Report")
        print("="*60)

        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=7)

        report = {
            'period': f"{start_date} to {end_date}",
            'generated_at': datetime.now().isoformat(),
            'analysis': {}
        }

        with self.conn.cursor() as cur:
            # 1. Overall Performance
            cur.execute("""
                SELECT
                    COUNT(*) as total_signals,
                    COUNT(*) FILTER (WHERE pump_realized) as successful_pumps,
                    ROUND(COUNT(*) FILTER (WHERE pump_realized)::numeric /
                          NULLIF(COUNT(*), 0) * 100, 2) as success_rate,
                    ROUND(AVG(max_price_increase), 2) as avg_pump_size,
                    ROUND(MAX(max_price_increase), 2) as max_pump_size
                FROM pump.signals
                WHERE detected_at BETWEEN %s AND %s
            """, (start_date, end_date))

            weekly_stats = cur.fetchone()
            report['analysis']['overall'] = dict(weekly_stats) if weekly_stats else {}

            # 2. Performance by Signal Strength
            cur.execute("""
                SELECT
                    signal_strength,
                    COUNT(*) as count,
                    COUNT(*) FILTER (WHERE pump_realized) as pumps,
                    ROUND(COUNT(*) FILTER (WHERE pump_realized)::numeric /
                          NULLIF(COUNT(*), 0) * 100, 2) as accuracy,
                    ROUND(AVG(max_price_increase), 2) as avg_gain
                FROM pump.signals
                WHERE detected_at BETWEEN %s AND %s
                  AND signal_strength IS NOT NULL
                GROUP BY signal_strength
                ORDER BY
                    CASE signal_strength
                        WHEN 'EXTREME' THEN 1
                        WHEN 'STRONG' THEN 2
                        WHEN 'MEDIUM' THEN 3
                        WHEN 'WEAK' THEN 4
                    END
            """, (start_date, end_date))

            by_strength = cur.fetchall()
            report['analysis']['by_strength'] = [dict(row) for row in by_strength]

            # 3. Daily Trend
            cur.execute("""
                SELECT
                    DATE(detected_at) as date,
                    COUNT(*) as signals,
                    COUNT(*) FILTER (WHERE pump_realized) as pumps,
                    ROUND(AVG(max_price_increase), 2) as avg_gain
                FROM pump.signals
                WHERE detected_at BETWEEN %s AND %s
                GROUP BY DATE(detected_at)
                ORDER BY date
            """, (start_date, end_date))

            daily_trend = cur.fetchall()
            report['analysis']['daily_trend'] = [dict(row) for row in daily_trend]

            # 4. Best Performing Pairs
            cur.execute("""
                SELECT
                    pair_symbol,
                    COUNT(*) as signal_count,
                    COUNT(*) FILTER (WHERE pump_realized) as pump_count,
                    ROUND(AVG(max_price_increase), 2) as avg_gain,
                    ROUND(MAX(max_price_increase), 2) as best_gain
                FROM pump.signals
                WHERE detected_at BETWEEN %s AND %s
                GROUP BY pair_symbol
                HAVING COUNT(*) >= 2
                ORDER BY COUNT(*) FILTER (WHERE pump_realized) DESC, avg_gain DESC
                LIMIT 10
            """, (start_date, end_date))

            best_pairs = cur.fetchall()
            report['analysis']['best_pairs'] = [dict(row) for row in best_pairs]

        # Generate visualizations
        self._plot_weekly_analysis(report)

        # Save report
        report_path = os.path.join(self.report_dir, f"weekly_report_{end_date}.json")
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        print(f"✅ Weekly report saved to: {report_path}")
        return report

    def generate_correlation_matrix(self):
        """Generate correlation matrix between different factors"""

        print("\n🔗 Generating Correlation Analysis")
        print("="*60)

        query = """
        SELECT
            futures_spike_ratio_7d,
            futures_spike_ratio_14d,
            COALESCE(futures_oi_spike_ratio, 1) as oi_spike_ratio,
            COALESCE(spot_volume_change_pct, 0) as spot_change,
            initial_confidence,
            CASE WHEN pump_realized THEN 1 ELSE 0 END as pump_success,
            COALESCE(max_price_increase, 0) as price_increase
        FROM pump.signals
        WHERE detected_at >= NOW() - INTERVAL '30 days'
          AND futures_spike_ratio_7d IS NOT NULL
        """

        df = pd.read_sql(query, self.conn)

        # Calculate correlation matrix
        corr_matrix = df.corr()

        # Plot heatmap
        plt.figure(figsize=(10, 8))
        sns.heatmap(corr_matrix, annot=True, fmt='.2f', cmap='coolwarm',
                   center=0, vmin=-1, vmax=1)
        plt.title('Feature Correlation Matrix')
        plt.tight_layout()

        plot_path = os.path.join(self.report_dir, 'correlation_matrix.png')
        plt.savefig(plot_path)
        plt.close()

        print(f"✅ Correlation matrix saved to: {plot_path}")

        # Find strongest correlations with success
        success_corr = corr_matrix['pump_success'].sort_values(ascending=False)
        print("\n📊 Correlation with Pump Success:")
        for factor, corr in success_corr.items():
            if factor != 'pump_success':
                print(f"  {factor:20}: {corr:+.3f}")

        return corr_matrix

    def _plot_daily_performance(self, report, date):
        """Create daily performance visualizations"""

        if not report['metrics']['hourly_performance']:
            return

        df = pd.DataFrame(report['metrics']['hourly_performance'])

        fig, axes = plt.subplots(2, 1, figsize=(12, 8))

        # Hourly signal distribution
        axes[0].bar(df['hour'], df['signals'], color='skyblue', label='Total Signals')
        axes[0].bar(df['hour'], df['pumps'], color='green', alpha=0.7, label='Successful Pumps')
        axes[0].set_xlabel('Hour of Day')
        axes[0].set_ylabel('Count')
        axes[0].set_title(f'Signal Distribution by Hour - {date}')
        axes[0].legend()
        axes[0].set_xticks(range(0, 24))

        # Average gain by hour
        axes[1].plot(df['hour'], df['avg_gain'], marker='o', color='orange', linewidth=2)
        axes[1].set_xlabel('Hour of Day')
        axes[1].set_ylabel('Average Gain (%)')
        axes[1].set_title('Average Pump Size by Hour')
        axes[1].grid(True, alpha=0.3)
        axes[1].set_xticks(range(0, 24))

        plt.tight_layout()
        plot_path = os.path.join(self.report_dir, f'daily_performance_{date}.png')
        plt.savefig(plot_path)
        plt.close()

    def _plot_weekly_analysis(self, report):
        """Create weekly analysis visualizations"""

        # Daily trend
        if report['analysis']['daily_trend']:
            df_daily = pd.DataFrame(report['analysis']['daily_trend'])

            fig, axes = plt.subplots(2, 1, figsize=(12, 8))

            # Signals and pumps over time
            axes[0].plot(pd.to_datetime(df_daily['date']), df_daily['signals'],
                        marker='o', label='Total Signals', linewidth=2)
            axes[0].plot(pd.to_datetime(df_daily['date']), df_daily['pumps'],
                        marker='s', label='Successful Pumps', linewidth=2, color='green')
            axes[0].set_xlabel('Date')
            axes[0].set_ylabel('Count')
            axes[0].set_title('Weekly Signal Trend')
            axes[0].legend()
            axes[0].grid(True, alpha=0.3)

            # Average gain trend
            axes[1].bar(pd.to_datetime(df_daily['date']), df_daily['avg_gain'],
                       color='orange', alpha=0.7)
            axes[1].set_xlabel('Date')
            axes[1].set_ylabel('Average Gain (%)')
            axes[1].set_title('Daily Average Pump Size')
            axes[1].grid(True, alpha=0.3)

            plt.tight_layout()
            plot_path = os.path.join(self.report_dir, 'weekly_trend.png')
            plt.savefig(plot_path)
            plt.close()

        # Performance by signal strength
        if report['analysis']['by_strength']:
            df_strength = pd.DataFrame(report['analysis']['by_strength'])

            fig, ax = plt.subplots(figsize=(10, 6))

            x = np.arange(len(df_strength))
            width = 0.35

            bars1 = ax.bar(x - width/2, df_strength['count'], width,
                          label='Total Signals', color='skyblue')
            bars2 = ax.bar(x + width/2, df_strength['pumps'], width,
                          label='Successful Pumps', color='green')

            # Add accuracy labels
            for i, (bar1, bar2, acc) in enumerate(zip(bars1, bars2, df_strength['accuracy'])):
                ax.text(bar1.get_x() + bar1.get_width()/2, bar1.get_height() + 1,
                       f"{acc:.1f}%", ha='center', va='bottom', fontsize=10)

            ax.set_xlabel('Signal Strength')
            ax.set_ylabel('Count')
            ax.set_title('Performance by Signal Strength')
            ax.set_xticks(x)
            ax.set_xticklabels(df_strength['signal_strength'])
            ax.legend()

            plt.tight_layout()
            plot_path = os.path.join(self.report_dir, 'performance_by_strength.png')
            plt.savefig(plot_path)
            plt.close()

    def generate_backtest_report(self, start_date, end_date):
        """Generate backtest performance report"""

        print(f"\n🔄 Generating Backtest Report ({start_date} to {end_date})")
        print("="*60)

        with self.conn.cursor() as cur:
            # Simulate trading based on signals
            cur.execute("""
                WITH trades AS (
                    SELECT
                        signal_timestamp,
                        pair_symbol,
                        futures_spike_ratio_7d,
                        signal_strength,
                        pump_realized,
                        COALESCE(max_price_increase, -5) as pnl,  -- -5% stop loss
                        initial_confidence
                    FROM pump.signals
                    WHERE detected_at BETWEEN %s AND %s
                      AND signal_strength IN ('EXTREME', 'STRONG')  -- Only trade strong signals
                    ORDER BY signal_timestamp
                ),
                cumulative AS (
                    SELECT
                        *,
                        SUM(pnl) OVER (ORDER BY signal_timestamp) as cumulative_pnl,
                        COUNT(*) OVER (ORDER BY signal_timestamp) as trade_count
                    FROM trades
                )
                SELECT
                    COUNT(*) as total_trades,
                    COUNT(*) FILTER (WHERE pnl > 0) as winning_trades,
                    COUNT(*) FILTER (WHERE pnl < 0) as losing_trades,
                    ROUND(COUNT(*) FILTER (WHERE pnl > 0)::numeric /
                          NULLIF(COUNT(*), 0) * 100, 2) as win_rate,
                    ROUND(AVG(pnl), 2) as avg_pnl,
                    ROUND(AVG(pnl) FILTER (WHERE pnl > 0), 2) as avg_win,
                    ROUND(AVG(pnl) FILTER (WHERE pnl < 0), 2) as avg_loss,
                    ROUND(MAX(cumulative_pnl), 2) as max_cumulative_pnl,
                    ROUND(MIN(cumulative_pnl), 2) as max_drawdown,
                    ROUND(SUM(pnl), 2) as total_pnl
                FROM cumulative
            """, (start_date, end_date))

            backtest_stats = cur.fetchone()

            if backtest_stats:
                print("\n📊 BACKTEST RESULTS")
                print("-"*40)
                print(f"Total Trades: {backtest_stats['total_trades']}")
                print(f"Win Rate: {backtest_stats['win_rate']}%")
                print(f"Average P&L: {backtest_stats['avg_pnl']}%")
                print(f"Average Win: {backtest_stats['avg_win']}%")
                print(f"Average Loss: {backtest_stats['avg_loss']}%")
                print(f"Total P&L: {backtest_stats['total_pnl']}%")
                print(f"Max Drawdown: {backtest_stats['max_drawdown']}%")

                # Calculate Sharpe ratio (simplified)
                if backtest_stats['total_trades'] > 0:
                    sharpe = (backtest_stats['avg_pnl'] / 5) * np.sqrt(252)  # Annualized
                    print(f"Sharpe Ratio: {sharpe:.2f}")

            return dict(backtest_stats) if backtest_stats else {}

    def generate_all_reports(self):
        """Generate all report types"""

        print("📊 GENERATING COMPREHENSIVE REPORTS")
        print("="*60)

        # Daily report
        self.generate_daily_report()

        # Weekly report
        self.generate_weekly_report()

        # Correlation analysis
        self.generate_correlation_matrix()

        # Backtest for last 30 days
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        self.generate_backtest_report(start_date, end_date)

        print("\n✅ All reports generated successfully!")
        print(f"📁 Reports saved to: {self.report_dir}")

def main():
    """Main function"""
    generator = ReportGenerator()

    # Generate all reports
    generator.generate_all_reports()

    # Close connection
    generator.conn.close()

if __name__ == "__main__":
    main()