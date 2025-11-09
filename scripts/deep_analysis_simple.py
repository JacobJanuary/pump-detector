#!/usr/bin/env python3
"""
SIMPLIFIED DEEP ANALYSIS
Анализ на основе уже созданных отчетов (без подключения к БД)
"""

import json
from pathlib import Path
from collections import defaultdict
import statistics

def load_all_data():
    """Load pumps and reports"""
    pumps_file = Path('/tmp/pump_analysis/pumps_found.json')
    with open(pumps_file, 'r') as f:
        pumps = json.load(f)

    reports_dir = Path('/tmp/pump_analysis/reports')
    reports = {}
    for report_file in sorted(reports_dir.glob('*.json')):
        with open(report_file, 'r') as f:
            report = json.load(f)
            idx = report['pump_index']
            reports[idx] = report

    return pumps, reports

def analyze_timing_windows(signals):
    """Analyze signal distribution across time windows"""
    windows = {
        '0-12h': [],
        '12-24h': [],
        '24-48h': [],
        '48-72h': [],
        '72-120h': [],
        '120-168h': []
    }

    for sig in signals:
        hours = float(sig['hours_before_pump'])
        spike = float(sig.get('spike_ratio_7d', 0))

        if hours < 12:
            windows['0-12h'].append(spike)
        elif hours < 24:
            windows['12-24h'].append(spike)
        elif hours < 48:
            windows['24-48h'].append(spike)
        elif hours < 72:
            windows['48-72h'].append(spike)
        elif hours < 120:
            windows['72-120h'].append(spike)
        else:
            windows['120-168h'].append(spike)

    result = {}
    for window, spikes in windows.items():
        result[window] = {
            'count': len(spikes),
            'avg_spike': statistics.mean(spikes) if spikes else 0,
            'max_spike': max(spikes) if spikes else 0
        }

    return result

def analyze_strength_distribution(signals):
    """Categorize signals by spike strength"""
    extreme = []  # spike >= 5.0
    very_strong = []  # 3.0 <= spike < 5.0
    strong = []  # 2.0 <= spike < 3.0
    medium = []  # 1.5 <= spike < 2.0
    weak = []  # spike < 1.5

    for sig in signals:
        spike = float(sig.get('spike_ratio_7d', 0))
        if spike >= 5.0:
            extreme.append(sig)
        elif spike >= 3.0:
            very_strong.append(sig)
        elif spike >= 2.0:
            strong.append(sig)
        elif spike >= 1.5:
            medium.append(sig)
        else:
            weak.append(sig)

    return {
        'extreme': len(extreme),
        'very_strong': len(very_strong),
        'strong': len(strong),
        'medium': len(medium),
        'weak': len(weak)
    }

def analyze_spot_futures(signals):
    """Analyze SPOT vs FUTURES dynamics"""
    spot = [s for s in signals if s['signal_type'] == 'SPOT']
    futures = [s for s in signals if s['signal_type'] == 'FUTURES']

    return {
        'spot_count': len(spot),
        'futures_count': len(futures),
        'ratio': len(futures) / len(spot) if spot else (float('inf') if futures else 0),
        'first_signal': signals[0]['signal_type'] if signals else None
    }

def check_escalation(signals):
    """Check if signals escalate over time"""
    if len(signals) < 2:
        return {'escalating': False}

    # Sort by hours_before_pump (descending = earliest first)
    sorted_signals = sorted(signals, key=lambda x: -float(x['hours_before_pump']))

    mid = len(sorted_signals) // 2
    first_half = sorted_signals[:mid]
    second_half = sorted_signals[mid:]

    return {
        'escalating': len(second_half) > len(first_half),
        'first_half_count': len(first_half),
        'second_half_count': len(second_half)
    }

def main():
    print("="*80)
    print("УПРОЩЕННЫЙ ГЛУБОКИЙ АНАЛИЗ")
    print("="*80)
    print()

    # Load data
    print("📂 Загрузка данных...")
    pumps, reports = load_all_data()
    print(f"✓ Загружено {len(pumps)} пампов и {len(reports)} отчетов")
    print()

    # Analyze each pump
    print("🔬 Анализ всех пампов...")
    print()

    all_analyses = []

    for idx, pump in enumerate(pumps, 1):
        if idx not in reports:
            continue

        report = reports[idx]
        signals = report['signals']
        pattern = report['analysis']['pattern_type']
        confidence = report['analysis']['confidence']

        is_actionable = pattern in ['STRONG_PRECURSOR', 'MEDIUM_PRECURSOR', 'FUTURES_LED'] and confidence in ['HIGH', 'MEDIUM']

        analysis = {
            'idx': idx,
            'symbol': pump['symbol'],
            'gain': float(pump['max_gain_24h']),
            'pattern': pattern,
            'confidence': confidence,
            'is_actionable': is_actionable,
            'total_signals': len(signals),
            'timing': analyze_timing_windows(signals),
            'strength': analyze_strength_distribution(signals),
            'spot_futures': analyze_spot_futures(signals),
            'escalation': check_escalation(signals)
        }

        all_analyses.append(analysis)

        if idx % 20 == 0:
            print(f"Обработано {idx}/{len(pumps)} пампов...")

    print(f"✓ Завершен анализ {len(all_analyses)} пампов")
    print()

    # Split by actionability
    actionable = [a for a in all_analyses if a['is_actionable']]
    non_actionable = [a for a in all_analyses if not a['is_actionable']]

    print("="*80)
    print("СРАВНЕНИЕ: ACTIONABLE vs NON-ACTIONABLE")
    print("="*80)
    print()

    print(f"Actionable: {len(actionable)} ({len(actionable)/len(all_analyses)*100:.1f}%)")
    print(f"Non-actionable: {len(non_actionable)} ({len(non_actionable)/len(all_analyses)*100:.1f}%)")
    print()

    # === HYPOTHESIS 1: Timing Windows ===
    print("="*80)
    print("ГИПОТЕЗА 1: Временные окна сигналов")
    print("="*80)
    print()

    windows = ['0-12h', '12-24h', '24-48h', '48-72h', '72-120h', '120-168h']

    print("ACTIONABLE пампы:")
    for window in windows:
        counts = [a['timing'][window]['count'] for a in actionable]
        avg_count = statistics.mean(counts)
        spikes = [a['timing'][window]['avg_spike'] for a in actionable if a['timing'][window]['count'] > 0]
        avg_spike = statistics.mean(spikes) if spikes else 0
        print(f"  {window:12s}: {avg_count:5.2f} сигналов, avg spike: {avg_spike:.2f}x")

    print()
    print("NON-ACTIONABLE пампы:")
    for window in windows:
        counts = [a['timing'][window]['count'] for a in non_actionable]
        avg_count = statistics.mean(counts)
        spikes = [a['timing'][window]['avg_spike'] for a in non_actionable if a['timing'][window]['count'] > 0]
        avg_spike = statistics.mean(spikes) if spikes else 0
        print(f"  {window:12s}: {avg_count:5.2f} сигналов, avg spike: {avg_spike:.2f}x")

    print()

    # === HYPOTHESIS 2: Signal Strength ===
    print("="*80)
    print("ГИПОТЕЗА 2: Распределение силы сигналов")
    print("="*80)
    print()

    strengths = ['extreme', 'very_strong', 'strong', 'medium', 'weak']

    print("ACTIONABLE пампы:")
    for strength in strengths:
        counts = [a['strength'][strength] for a in actionable]
        avg = statistics.mean(counts)
        has_any = len([c for c in counts if c > 0])
        print(f"  {strength:15s}: avg {avg:5.2f}, присутствует в {has_any}/{len(actionable)} ({has_any/len(actionable)*100:.1f}%)")

    print()
    print("NON-ACTIONABLE пампы:")
    for strength in strengths:
        counts = [a['strength'][strength] for a in non_actionable]
        avg = statistics.mean(counts)
        has_any = len([c for c in counts if c > 0])
        print(f"  {strength:15s}: avg {avg:5.2f}, присутствует в {has_any}/{len(non_actionable)} ({has_any/len(non_actionable)*100:.1f}%)")

    print()

    # === HYPOTHESIS 3: SPOT/FUTURES ===
    print("="*80)
    print("ГИПОТЕЗА 3: SPOT vs FUTURES динамика")
    print("="*80)
    print()

    print("ACTIONABLE пампы:")
    spot_counts = [a['spot_futures']['spot_count'] for a in actionable]
    futures_counts = [a['spot_futures']['futures_count'] for a in actionable]
    print(f"  Avg SPOT: {statistics.mean(spot_counts):.2f}")
    print(f"  Avg FUTURES: {statistics.mean(futures_counts):.2f}")

    first_spot = len([a for a in actionable if a['spot_futures']['first_signal'] == 'SPOT'])
    first_futures = len([a for a in actionable if a['spot_futures']['first_signal'] == 'FUTURES'])
    print(f"  Первый SPOT: {first_spot} ({first_spot/len(actionable)*100:.1f}%)")
    print(f"  Первый FUTURES: {first_futures} ({first_futures/len(actionable)*100:.1f}%)")

    print()
    print("NON-ACTIONABLE пампы:")
    spot_counts = [a['spot_futures']['spot_count'] for a in non_actionable]
    futures_counts = [a['spot_futures']['futures_count'] for a in non_actionable]
    print(f"  Avg SPOT: {statistics.mean(spot_counts):.2f}")
    print(f"  Avg FUTURES: {statistics.mean(futures_counts):.2f}")

    first_spot = len([a for a in non_actionable if a['spot_futures']['first_signal'] == 'SPOT'])
    first_futures = len([a for a in non_actionable if a['spot_futures']['first_signal'] == 'FUTURES'])
    if non_actionable:
        print(f"  Первый SPOT: {first_spot} ({first_spot/len(non_actionable)*100:.1f}%)")
        print(f"  Первый FUTURES: {first_futures} ({first_futures/len(non_actionable)*100:.1f}%)")

    print()

    # === HYPOTHESIS 4: Escalation ===
    print("="*80)
    print("ГИПОТЕЗА 4: Эскалация сигналов")
    print("="*80)
    print()

    print("ACTIONABLE пампы:")
    escalating = len([a for a in actionable if a['escalation']['escalating']])
    print(f"  Эскалация: {escalating}/{len(actionable)} ({escalating/len(actionable)*100:.1f}%)")

    print()
    print("NON-ACTIONABLE пампы:")
    escalating = len([a for a in non_actionable if a['escalation']['escalating']])
    print(f"  Эскалация: {escalating}/{len(non_actionable)} ({escalating/len(non_actionable)*100:.1f}%)")

    print()

    # === HYPOTHESIS 5: Total Signals ===
    print("="*80)
    print("ГИПОТЕЗА 5: Общее количество сигналов")
    print("="*80)
    print()

    actionable_counts = [a['total_signals'] for a in actionable]
    non_actionable_counts = [a['total_signals'] for a in non_actionable]

    print(f"ACTIONABLE: avg {statistics.mean(actionable_counts):.2f}, median {statistics.median(actionable_counts):.0f}")
    print(f"NON-ACTIONABLE: avg {statistics.mean(non_actionable_counts):.2f}, median {statistics.median(non_actionable_counts):.0f}")
    print()

    # === KEY INSIGHTS ===
    print("="*80)
    print("КЛЮЧЕВЫЕ НАХОДКИ")
    print("="*80)
    print()

    # 1. Best time window
    print("1. ЛУЧШЕЕ ВРЕМЕННОЕ ОКНО:")
    for window in windows:
        actionable_avg = statistics.mean([a['timing'][window]['count'] for a in actionable])
        non_actionable_avg = statistics.mean([a['timing'][window]['count'] for a in non_actionable])
        diff = actionable_avg - non_actionable_avg
        if diff > 0.5:  # Significant difference
            print(f"   {window}: +{diff:.2f} больше сигналов в actionable пампах")

    print()

    # 2. Critical signal strength
    print("2. КРИТИЧЕСКАЯ СИЛА СИГНАЛОВ:")
    for strength in strengths:
        actionable_avg = statistics.mean([a['strength'][strength] for a in actionable])
        non_actionable_avg = statistics.mean([a['strength'][strength] for a in non_actionable])
        diff = actionable_avg - non_actionable_avg
        if abs(diff) > 0.3:
            direction = "больше" if diff > 0 else "меньше"
            print(f"   {strength}: {abs(diff):.2f} {direction} в actionable пампах")

    print()

    # 3. SPOT vs FUTURES preference
    print("3. SPOT vs FUTURES:")
    actionable_futures_avg = statistics.mean([a['spot_futures']['futures_count'] for a in actionable])
    actionable_spot_avg = statistics.mean([a['spot_futures']['spot_count'] for a in actionable])
    ratio = actionable_futures_avg / actionable_spot_avg if actionable_spot_avg > 0 else 0
    print(f"   В actionable пампах: FUTURES/SPOT ratio = {ratio:.2f}")

    print()

    # Save results
    output = {
        'summary': {
            'total': len(all_analyses),
            'actionable': len(actionable),
            'non_actionable': len(non_actionable)
        },
        'actionable_pumps': actionable,
        'non_actionable_pumps': non_actionable
    }

    output_file = Path('/tmp/pump_analysis/deep_analysis_results.json')
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"✓ Результаты сохранены: {output_file}")
    print()

    print("="*80)
    print("✅ АНАЛИЗ ЗАВЕРШЕН!")
    print("="*80)

if __name__ == "__main__":
    main()
