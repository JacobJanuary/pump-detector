#!/usr/bin/env python3
"""
Analyze Pump Precursor Signals
Iteratively analyzes signals 7 days before each detected pump
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, timezone
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DATABASE

def get_db_connection():
    """Establish database connection"""
    return psycopg2.connect(**DATABASE, cursor_factory=RealDictCursor)

def load_pumps():
    """Load detected pumps from JSON file"""
    pumps_file = Path('/tmp/pump_analysis/pumps_found.json')

    if not pumps_file.exists():
        print("❌ Файл с пампами не найден. Сначала запустите find_all_pumps.py")
        sys.exit(1)

    with open(pumps_file, 'r') as f:
        return json.load(f)

def get_signals_before_pump(conn, symbol, pump_time_ms, days_before=7):
    """
    Get all signals for a symbol in the period before pump
    """
    # Calculate time window
    pump_dt = datetime.fromtimestamp(pump_time_ms / 1000, tz=timezone.utc)
    window_start_dt = pump_dt - timedelta(days=days_before)

    window_start_ms = int(window_start_dt.timestamp() * 1000)

    query = """
    SELECT
        s.id,
        s.pair_symbol,
        s.signal_type,
        s.detected_at,
        s.signal_timestamp,
        s.spike_ratio_7d,
        s.spike_ratio_14d,
        s.spike_ratio_30d,
        s.signal_strength,
        s.baseline_7d,
        s.baseline_14d,
        s.baseline_30d,
        s.volume,
        s.price_at_signal,
        s.initial_confidence
    FROM pump.signals s
    WHERE s.pair_symbol = %s
      AND EXTRACT(EPOCH FROM s.signal_timestamp) * 1000 >= %s
      AND EXTRACT(EPOCH FROM s.signal_timestamp) * 1000 < %s
    ORDER BY s.signal_timestamp ASC
    """

    with conn.cursor() as cur:
        cur.execute(query, (symbol, window_start_ms, pump_time_ms))
        return cur.fetchall()

def display_pump_info(pump, pump_idx, total_pumps):
    """Display pump information"""
    pump_time = datetime.fromtimestamp(pump['pump_start_time'] / 1000, tz=timezone.utc)

    print("\n" + "="*80)
    print(f"ПАМП {pump_idx}/{total_pumps}")
    print("="*80)
    print(f"\nСимвол: {pump['symbol']}")
    print(f"Время пампа: {pump_time}")
    print(f"Стартовая цена: ${float(pump['start_price']):.4f}")
    print(f"Максимальный рост за 24ч: +{float(pump['max_gain_24h']):.1f}%%")
    print(f"Цена через 24ч: ${float(pump['price_after_24h']):.4f}")

def display_signals(signals, pump_time_ms):
    """Display precursor signals"""
    pump_dt = datetime.fromtimestamp(pump_time_ms / 1000, tz=timezone.utc)

    if not signals:
        print("\n⚠️  Сигналов за 7 дней до пампа не найдено")
        return

    print(f"\n📊 Найдено сигналов: {len(signals)}")
    print("\n" + "-"*80)

    # Group by type and strength
    by_type = {'FUTURES': [], 'SPOT': []}
    by_strength = {'EXTREME': [], 'STRONG': [], 'MEDIUM': [], 'WEAK': []}

    for sig in signals:
        sig_time = sig['signal_timestamp']
        if isinstance(sig_time, str):
            sig_time = datetime.fromisoformat(sig_time.replace('Z', '+00:00'))

        hours_before = (pump_dt - sig_time).total_seconds() / 3600
        sig['hours_before_pump'] = hours_before

        by_type[sig['signal_type']].append(sig)
        by_strength[sig['signal_strength']].append(sig)

    # Summary
    print("\nСТАТИСТИКА:")
    print(f"  FUTURES: {len(by_type['FUTURES'])}")
    print(f"  SPOT: {len(by_type['SPOT'])}")
    print(f"  EXTREME: {len(by_strength['EXTREME'])}")
    print(f"  STRONG: {len(by_strength['STRONG'])}")
    print(f"  MEDIUM: {len(by_strength['MEDIUM'])}")
    print(f"  WEAK: {len(by_strength['WEAK'])}")

    # Time distribution
    periods = {
        '0-24h': [s for s in signals if s['hours_before_pump'] <= 24],
        '24-48h': [s for s in signals if 24 < s['hours_before_pump'] <= 48],
        '48-72h': [s for s in signals if 48 < s['hours_before_pump'] <= 72],
        '72-120h': [s for s in signals if 72 < s['hours_before_pump'] <= 120],
        '120-168h': [s for s in signals if 120 < s['hours_before_pump'] <= 168],
    }

    print("\nРАСПРЕДЕЛЕНИЕ ПО ВРЕМЕНИ:")
    for period, sigs in periods.items():
        if sigs:
            print(f"  {period}: {len(sigs)} сигналов")

    # Detailed list
    print("\n" + "-"*80)
    print("ДЕТАЛЬНЫЙ СПИСОК СИГНАЛОВ:")
    print("-"*80)

    for idx, sig in enumerate(signals, 1):
        sig_time = sig['signal_timestamp']
        if isinstance(sig_time, str):
            sig_time = datetime.fromisoformat(sig_time.replace('Z', '+00:00'))

        print(f"\n[{idx}/{len(signals)}] Signal ID: {sig['id']}")
        print(f"  Type: {sig['signal_type']}")
        print(f"  Strength: {sig['signal_strength']}")
        print(f"  Time: {sig_time}")
        print(f"  Hours before pump: {sig['hours_before_pump']:.1f}h")
        print(f"  Spike Ratios: 7d={float(sig['spike_ratio_7d']):.1f}x, " +
              f"14d={float(sig['spike_ratio_14d']):.1f}x, " +
              f"30d={float(sig['spike_ratio_30d']):.1f}x")
        print(f"  Volume: {float(sig['volume']):,.0f}")
        if sig['price_at_signal']:
            print(f"  Price: ${float(sig['price_at_signal']):.4f}")

def save_analysis_report(pump, signals, analysis, pump_idx):
    """Save individual pump analysis report"""
    reports_dir = Path('/tmp/pump_analysis/reports')
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    symbol = pump['symbol'].replace('/', '_')
    pump_time = datetime.fromtimestamp(pump['pump_start_time'] / 1000, tz=timezone.utc)
    filename = f"{pump_idx:03d}_{symbol}_{pump_time.strftime('%Y%m%d_%H%M')}.json"

    report = {
        'pump_index': pump_idx,
        'symbol': pump['symbol'],
        'pump_time': pump_time.isoformat(),
        'pump_start_price': float(pump['start_price']),
        'max_gain_24h': float(pump['max_gain_24h']),
        'price_after_24h': float(pump['price_after_24h']),
        'signals_count': len(signals),
        'signals': [dict(s) for s in signals],
        'analysis': analysis
    }

    # Convert datetime objects to strings
    for sig in report['signals']:
        if 'signal_timestamp' in sig and not isinstance(sig['signal_timestamp'], str):
            sig['signal_timestamp'] = sig['signal_timestamp'].isoformat()
        if 'detected_at' in sig and not isinstance(sig['detected_at'], str):
            sig['detected_at'] = sig['detected_at'].isoformat()
        # Convert Decimal to float
        for key in sig:
            if sig[key] is not None and hasattr(sig[key], '__float__'):
                sig[key] = float(sig[key])

    report_file = reports_dir / filename
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    return report_file

def main():
    print("="*80)
    print("ИТЕРАТИВНЫЙ АНАЛИЗ СИГНАЛОВ-ПРЕДВЕСТНИКОВ ПАМПОВ")
    print("="*80)

    # Load pumps
    print("\n📂 Загрузка списка пампов...")
    pumps = load_pumps()
    print(f"✓ Загружено {len(pumps)} пампов для анализа")

    # Connect to database
    conn = get_db_connection()

    try:
        # Process each pump
        for idx, pump in enumerate(pumps, 1):
            # Display pump info
            display_pump_info(pump, idx, len(pumps))

            # Get signals before pump
            print("\n🔍 Загрузка сигналов за 7 дней до пампа...")
            signals = get_signals_before_pump(
                conn,
                pump['symbol'],
                pump['pump_start_time'],
                days_before=7
            )

            # Display signals
            display_signals(signals, pump['pump_start_time'])

            # Ask user for analysis
            print("\n" + "="*80)
            print("АНАЛИЗ")
            print("="*80)
            print("\nПроанализируйте сигналы и предоставьте краткие выводы.")
            print("Варианты:")
            print("  1. Введите анализ (многострочный, закончите пустой строкой)")
            print("  2. Введите 'SKIP' чтобы пропустить")
            print("  3. Введите 'QUIT' чтобы завершить")
            print()

            analysis_lines = []
            while True:
                line = input()
                if line == '':
                    break
                if line.upper() == 'SKIP':
                    analysis_lines = ['SKIPPED']
                    break
                if line.upper() == 'QUIT':
                    print("\n⚠️  Завершение по запросу пользователя")
                    return
                analysis_lines.append(line)

            analysis = '\n'.join(analysis_lines) if analysis_lines else 'NO ANALYSIS'

            # Save report
            report_file = save_analysis_report(pump, signals, analysis, idx)
            print(f"\n✓ Отчет сохранен: {report_file}")

            # Progress
            print(f"\n{'='*80}")
            print(f"Прогресс: {idx}/{len(pumps)} ({idx/len(pumps)*100:.1f}%%)")
            print(f"{'='*80}\n")

        print("\n" + "="*80)
        print("✅ АНАЛИЗ ЗАВЕРШЕН!")
        print("="*80)
        print(f"\nВсего проанализировано: {len(pumps)} пампов")
        print(f"Отчеты сохранены в: /tmp/pump_analysis/reports/")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
