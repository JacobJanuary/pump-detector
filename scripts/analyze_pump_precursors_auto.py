#!/usr/bin/env python3
"""
Automated Pump Precursor Analysis
AI-powered analysis of signals before each pump by expert crypto analyst
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

def analyze_signals_expert(pump, signals):
    """
    Expert analysis of precursor signals
    Analyzes patterns, timing, strength distribution
    """
    pump_time = datetime.fromtimestamp(pump['pump_start_time'] / 1000, tz=timezone.utc)
    pump_gain = float(pump['max_gain_24h'])

    if not signals:
        return {
            'conclusion': 'NO_SIGNALS',
            'summary': 'Памп произошел без предшествующих сигналов. Возможно внешний катализатор (новости, листинг) или манипуляция.',
            'confidence': 'LOW',
            'pattern_type': 'SILENT_PUMP',
            'actionable': False
        }

    # Process signals
    pump_dt = datetime.fromtimestamp(pump['pump_start_time'] / 1000, tz=timezone.utc)

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

    # Time distribution
    periods = {
        '0-24h': [s for s in signals if s['hours_before_pump'] <= 24],
        '24-48h': [s for s in signals if 24 < s['hours_before_pump'] <= 48],
        '48-72h': [s for s in signals if 48 < s['hours_before_pump'] <= 72],
        '72-120h': [s for s in signals if 72 < s['hours_before_pump'] <= 120],
        '120-168h': [s for s in signals if 120 < s['hours_before_pump'] <= 168],
    }

    # Calculate metrics
    total_signals = len(signals)
    futures_count = len(by_type['FUTURES'])
    spot_count = len(by_type['SPOT'])
    extreme_count = len(by_strength['EXTREME'])
    strong_count = len(by_strength['STRONG'])

    # Average spike ratios
    avg_spike_7d = sum(float(s['spike_ratio_7d']) for s in signals) / len(signals)
    max_spike_7d = max(float(s['spike_ratio_7d']) for s in signals)

    # Timing analysis
    signals_24h_before = len(periods['0-24h'])
    signals_48h_before = len(periods['24-48h'])

    # Build analysis
    analysis = {
        'total_signals': total_signals,
        'futures_count': futures_count,
        'spot_count': spot_count,
        'extreme_count': extreme_count,
        'strong_count': strong_count,
        'avg_spike_7d': round(avg_spike_7d, 1),
        'max_spike_7d': round(max_spike_7d, 1),
        'signals_24h_before': signals_24h_before,
        'signals_48h_before': signals_48h_before,
    }

    # Pattern detection
    if extreme_count >= 2 and signals_24h_before >= 1:
        pattern = 'STRONG_PRECURSOR'
        confidence = 'HIGH'
        actionable = True
        summary = f"Сильный паттерн: {extreme_count} EXTREME сигналов за неделю, {signals_24h_before} в последние 24ч. " + \
                  f"Средний spike {avg_spike_7d:.1f}x. Памп на +{pump_gain:.0f}% был предсказуем."

    elif (extreme_count + strong_count) >= 3 and signals_48h_before >= 2:
        pattern = 'MEDIUM_PRECURSOR'
        confidence = 'MEDIUM'
        actionable = True
        summary = f"Умеренный паттерн: {extreme_count + strong_count} сильных сигналов за неделю. " + \
                  f"Эскалация активности за 48ч до пампа ({signals_48h_before} сигналов). " + \
                  f"Памп +{pump_gain:.0f}% имел предпосылки."

    elif futures_count > spot_count * 2 and signals_24h_before >= 1:
        pattern = 'FUTURES_LED'
        confidence = 'MEDIUM'
        actionable = True
        summary = f"FUTURES-доминирование: {futures_count} vs {spot_count} SPOT. " + \
                  f"Активность на фьючерсах предшествовала пампу. " + \
                  f"Возможная манипуляция или информированная торговля."

    elif total_signals >= 5 and extreme_count == 0:
        pattern = 'WEAK_SIGNALS'
        confidence = 'LOW'
        actionable = False
        summary = f"Слабые сигналы: {total_signals} сигналов без EXTREME уровня. " + \
                  f"Памп +{pump_gain:.0f}% не был очевиден из сигналов. " + \
                  f"Возможно органический рост или внешний катализатор."

    elif signals_24h_before == 0 and total_signals > 0:
        pattern = 'EARLY_SIGNALS_ONLY'
        confidence = 'LOW'
        actionable = False
        summary = f"Ранние сигналы без подтверждения: активность {total_signals} сигналов 3-7 дней назад, " + \
                  f"но затухание перед пампом. Паттерн 'затухание перед штормом' - сложно торговать."

    else:
        pattern = 'UNCLEAR'
        confidence = 'LOW'
        actionable = False
        summary = f"Неоднозначный паттерн: {total_signals} сигналов разной силы. " + \
                  f"Памп +{pump_gain:.0f}% сложно было предсказать из имеющихся данных."

    # Detailed breakdown
    time_analysis = []
    for period_name, period_sigs in periods.items():
        if period_sigs:
            extreme_in_period = len([s for s in period_sigs if s['signal_strength'] == 'EXTREME'])
            time_analysis.append({
                'period': period_name,
                'count': len(period_sigs),
                'extreme': extreme_in_period,
                'avg_spike': round(sum(float(s['spike_ratio_7d']) for s in period_sigs) / len(period_sigs), 1)
            })

    analysis.update({
        'pattern_type': pattern,
        'confidence': confidence,
        'actionable': actionable,
        'summary': summary,
        'time_breakdown': time_analysis
    })

    return analysis

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
    print("АВТОМАТИЧЕСКИЙ АНАЛИЗ СИГНАЛОВ-ПРЕДВЕСТНИКОВ ПАМПОВ")
    print("Экспертный анализ от ведущего аналитика крипто-хедж фонда")
    print("="*80)

    # Load pumps
    print("\n📂 Загрузка списка пампов...")
    pumps = load_pumps()
    print(f"✓ Загружено {len(pumps)} пампов для анализа")

    # Connect to database
    conn = get_db_connection()

    # Statistics
    pattern_stats = {
        'STRONG_PRECURSOR': 0,
        'MEDIUM_PRECURSOR': 0,
        'FUTURES_LED': 0,
        'WEAK_SIGNALS': 0,
        'EARLY_SIGNALS_ONLY': 0,
        'UNCLEAR': 0,
        'SILENT_PUMP': 0
    }

    actionable_pumps = []

    try:
        # Process each pump
        for idx, pump in enumerate(pumps, 1):
            pump_time = datetime.fromtimestamp(pump['pump_start_time'] / 1000, tz=timezone.utc)

            if idx % 50 == 0 or idx == 1:
                print(f"\n{'='*80}")
                print(f"Прогресс: {idx}/{len(pumps)} ({idx/len(pumps)*100:.1f}%%)")
                print(f"{'='*80}")

            print(f"\n[{idx}/{len(pumps)}] {pump['symbol']} | {pump_time} | +{float(pump['max_gain_24h']):.0f}%%")

            # Get signals before pump
            signals = get_signals_before_pump(
                conn,
                pump['symbol'],
                pump['pump_start_time'],
                days_before=7
            )

            # Expert analysis
            analysis = analyze_signals_expert(pump, signals)

            # Update stats
            pattern_stats[analysis['pattern_type']] += 1

            if analysis['actionable']:
                actionable_pumps.append({
                    'idx': idx,
                    'symbol': pump['symbol'],
                    'gain': float(pump['max_gain_24h']),
                    'confidence': analysis['confidence']
                })

            print(f"  📊 Сигналов: {len(signals)} | Паттерн: {analysis['pattern_type']} | Confidence: {analysis['confidence']}")
            print(f"  💡 {analysis['summary']}")

            # Save report
            report_file = save_analysis_report(pump, signals, analysis, idx)

        # Final summary
        print("\n" + "="*80)
        print("✅ АНАЛИЗ ЗАВЕРШЕН!")
        print("="*80)

        print(f"\nВсего проанализировано: {len(pumps)} пампов")
        print(f"Отчеты сохранены в: /tmp/pump_analysis/reports/")

        print("\n" + "="*80)
        print("СТАТИСТИКА ПАТТЕРНОВ:")
        print("="*80)
        for pattern, count in sorted(pattern_stats.items(), key=lambda x: -x[1]):
            pct = count / len(pumps) * 100
            print(f"  {pattern:25s}: {count:4d} ({pct:5.1f}%%)")

        print("\n" + "="*80)
        print(f"ПРИГОДНЫЕ ДЛЯ ТОРГОВЛИ: {len(actionable_pumps)} пампов")
        print("="*80)

        if actionable_pumps:
            # Group by confidence
            high_conf = [p for p in actionable_pumps if p['confidence'] == 'HIGH']
            medium_conf = [p for p in actionable_pumps if p['confidence'] == 'MEDIUM']

            print(f"\nHIGH confidence: {len(high_conf)}")
            print(f"MEDIUM confidence: {len(medium_conf)}")

            avg_gain_actionable = sum(p['gain'] for p in actionable_pumps) / len(actionable_pumps)
            print(f"\nСредний gain пригодных пампов: +{avg_gain_actionable:.1f}%%")

        # Save summary
        summary_file = Path('/tmp/pump_analysis/analysis_summary.json')
        summary = {
            'total_pumps': len(pumps),
            'pattern_distribution': pattern_stats,
            'actionable_count': len(actionable_pumps),
            'actionable_pumps': actionable_pumps
        }

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f"\n✓ Общая сводка сохранена: {summary_file}")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
