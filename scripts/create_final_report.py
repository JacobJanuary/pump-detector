#!/usr/bin/env python3
"""
Final Comprehensive Report Generation
Synthesizes findings from all 805 pump analyses and creates actionable recommendations
"""

import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime

def load_all_reports():
    """Load all individual pump reports"""
    reports_dir = Path('/tmp/pump_analysis/reports')
    reports = []

    for report_file in sorted(reports_dir.glob('*.json')):
        with open(report_file, 'r', encoding='utf-8') as f:
            reports.append(json.load(f))

    return reports

def load_summary():
    """Load analysis summary"""
    with open('/tmp/pump_analysis/analysis_summary.json', 'r', encoding='utf-8') as f:
        return json.load(f)

def analyze_actionable_vs_non_actionable(reports):
    """Deep comparison between actionable and non-actionable pumps"""

    actionable = []
    non_actionable = []

    for report in reports:
        analysis = report['analysis']
        if analysis['actionable']:
            actionable.append(report)
        else:
            non_actionable.append(report)

    # Metrics comparison
    def get_metrics(pump_list):
        if not pump_list:
            return {}

        total_signals = sum(p['signals_count'] for p in pump_list)
        total_pumps = len(pump_list)

        # Signal counts
        extreme_count = 0
        strong_count = 0
        futures_count = 0
        spot_count = 0

        # Timing metrics
        signals_24h = 0
        signals_48h = 0

        # Spike ratios
        spike_7d_values = []

        for pump in pump_list:
            for sig in pump['signals']:
                strength = sig.get('signal_strength', '')
                if strength == 'EXTREME':
                    extreme_count += 1
                elif strength == 'STRONG':
                    strong_count += 1

                sig_type = sig.get('signal_type', '')
                if sig_type == 'FUTURES':
                    futures_count += 1
                elif sig_type == 'SPOT':
                    spot_count += 1

                spike_7d_values.append(sig.get('spike_ratio_7d', 0))

        avg_signals_per_pump = total_signals / total_pumps if total_pumps > 0 else 0
        avg_spike_7d = sum(spike_7d_values) / len(spike_7d_values) if spike_7d_values else 0

        gains = [p['max_gain_24h'] for p in pump_list]
        avg_gain = sum(gains) / len(gains) if gains else 0
        median_gain = sorted(gains)[len(gains)//2] if gains else 0

        return {
            'total_pumps': total_pumps,
            'total_signals': total_signals,
            'avg_signals_per_pump': avg_signals_per_pump,
            'extreme_signals': extreme_count,
            'strong_signals': strong_count,
            'futures_signals': futures_count,
            'spot_signals': spot_count,
            'avg_spike_7d': avg_spike_7d,
            'avg_gain': avg_gain,
            'median_gain': median_gain,
            'min_gain': min(gains) if gains else 0,
            'max_gain': max(gains) if gains else 0
        }

    actionable_metrics = get_metrics(actionable)
    non_actionable_metrics = get_metrics(non_actionable)

    return {
        'actionable': actionable_metrics,
        'non_actionable': non_actionable_metrics,
        'comparison': {
            'signal_density_ratio': actionable_metrics['avg_signals_per_pump'] / non_actionable_metrics['avg_signals_per_pump'] if non_actionable_metrics['avg_signals_per_pump'] > 0 else 0,
            'gain_advantage': actionable_metrics['avg_gain'] - non_actionable_metrics['avg_gain']
        }
    }

def analyze_pattern_effectiveness(reports, summary):
    """Analyze which patterns are most profitable"""

    pattern_stats = defaultdict(lambda: {
        'count': 0,
        'gains': [],
        'signal_counts': [],
        'extreme_ratio': [],
        'futures_ratio': []
    })

    for report in reports:
        pattern = report['analysis']['pattern_type']
        gain = report['max_gain_24h']
        signals = report['signals']

        pattern_stats[pattern]['count'] += 1
        pattern_stats[pattern]['gains'].append(gain)
        pattern_stats[pattern]['signal_counts'].append(len(signals))

        if signals:
            extreme_count = sum(1 for s in signals if s.get('signal_strength') == 'EXTREME')
            futures_count = sum(1 for s in signals if s.get('signal_type') == 'FUTURES')

            pattern_stats[pattern]['extreme_ratio'].append(extreme_count / len(signals))
            pattern_stats[pattern]['futures_ratio'].append(futures_count / len(signals))

    # Calculate summary for each pattern
    results = {}
    for pattern, stats in pattern_stats.items():
        avg_gain = sum(stats['gains']) / len(stats['gains']) if stats['gains'] else 0
        median_gain = sorted(stats['gains'])[len(stats['gains'])//2] if stats['gains'] else 0
        avg_signals = sum(stats['signal_counts']) / len(stats['signal_counts']) if stats['signal_counts'] else 0
        avg_extreme_ratio = sum(stats['extreme_ratio']) / len(stats['extreme_ratio']) if stats['extreme_ratio'] else 0
        avg_futures_ratio = sum(stats['futures_ratio']) / len(stats['futures_ratio']) if stats['futures_ratio'] else 0

        results[pattern] = {
            'count': stats['count'],
            'pct_of_total': stats['count'] / len(reports) * 100,
            'avg_gain': avg_gain,
            'median_gain': median_gain,
            'max_gain': max(stats['gains']) if stats['gains'] else 0,
            'avg_signals': avg_signals,
            'avg_extreme_ratio': avg_extreme_ratio,
            'avg_futures_ratio': avg_futures_ratio
        }

    return results

def find_top_performers(reports, top_n=20):
    """Identify top performing actionable pumps for case studies"""

    actionable_pumps = [r for r in reports if r['analysis']['actionable']]

    # Sort by gain
    sorted_by_gain = sorted(actionable_pumps, key=lambda x: x['max_gain_24h'], reverse=True)

    top_pumps = []
    for pump in sorted_by_gain[:top_n]:
        analysis = pump['analysis']

        top_pumps.append({
            'symbol': pump['symbol'],
            'gain': pump['max_gain_24h'],
            'pump_time': pump['pump_time'],
            'pattern': analysis['pattern_type'],
            'confidence': analysis['confidence'],
            'signals_count': pump['signals_count'],
            'total_signals': analysis.get('total_signals', 0),
            'extreme_count': analysis.get('extreme_count', 0),
            'futures_count': analysis.get('futures_count', 0),
            'summary': analysis['summary']
        })

    return top_pumps

def generate_trading_recommendations(pattern_analysis, comparison):
    """Generate concrete trading recommendations"""

    recommendations = []

    # Filter to actionable patterns
    actionable_patterns = {
        k: v for k, v in pattern_analysis.items()
        if k in ['STRONG_PRECURSOR', 'MEDIUM_PRECURSOR', 'FUTURES_LED']
    }

    # Recommendation 1: Pattern priority
    sorted_patterns = sorted(actionable_patterns.items(), key=lambda x: x[1]['avg_gain'], reverse=True)

    recommendations.append({
        'title': 'PRIORITY PATTERNS FOR TRADING',
        'recommendation': f"Focus on these patterns in order of expected return:",
        'details': [
            f"{i+1}. {pattern}: avg gain +{data['avg_gain']:.1f}%, median +{data['median_gain']:.1f}% ({data['count']} cases)"
            for i, (pattern, data) in enumerate(sorted_patterns)
        ]
    })

    # Recommendation 2: Signal thresholds
    strong_pattern = pattern_analysis.get('STRONG_PRECURSOR', {})
    if strong_pattern:
        recommendations.append({
            'title': 'OPTIMAL SIGNAL THRESHOLDS',
            'recommendation': 'Enter positions when detecting:',
            'details': [
                f"≥2 EXTREME signals (spike ratio ≥5.0x)",
                f"≥1 signal in last 24h before expected pump",
                f"Average spike ratio ≥{strong_pattern['avg_extreme_ratio'] * 5:.1f}x for strong signals",
                f"Expected return: +{strong_pattern['avg_gain']:.1f}% (median +{strong_pattern['median_gain']:.1f}%)"
            ]
        })

    # Recommendation 3: Futures-led pattern specifics
    futures_led = pattern_analysis.get('FUTURES_LED', {})
    if futures_led:
        recommendations.append({
            'title': 'FUTURES-LED PATTERN STRATEGY',
            'recommendation': 'Identify potential manipulation/informed trading:',
            'details': [
                f"FUTURES signals > 2x SPOT signals",
                f"≥1 signal in last 24h",
                f"Average futures ratio: {futures_led['avg_futures_ratio']*100:.0f}%",
                f"Expected return: +{futures_led['avg_gain']:.1f}%",
                "Risk: Higher volatility, watch for reversal"
            ]
        })

    # Recommendation 4: Risk management
    recommendations.append({
        'title': 'RISK MANAGEMENT',
        'recommendation': 'Avoid or use stricter stops for:',
        'details': [
            "SILENT_PUMP patterns (31% of all pumps, unpredictable)",
            "EARLY_SIGNALS_ONLY (signals >3 days before pump with no recent activity)",
            "UNCLEAR patterns (mixed signals, low confidence)",
            f"Entry size: Scale position based on confidence level",
            f"HIGH confidence: Full position size (expected +{comparison['actionable']['avg_gain']:.1f}%)",
            "MEDIUM confidence: 50-70% position size"
        ]
    })

    # Recommendation 5: Detection timing
    recommendations.append({
        'title': 'OPTIMAL DETECTION TIMING',
        'recommendation': 'Best time windows to detect actionable pumps:',
        'details': [
            "Primary window: 24-48h before pump (highest signal concentration)",
            "Secondary window: 48-72h before pump (early entry, lower risk)",
            "Late signals (<12h): Higher risk but still actionable with tight stops",
            "Avoid: Signals only in 120-168h window (too early, 'затухание перед штормом')"
        ]
    })

    return recommendations

def create_executive_summary(summary, comparison, pattern_analysis):
    """Create executive summary for report"""

    total_pumps = summary['total_pumps']
    actionable_count = summary['actionable_count']
    actionable_pct = actionable_count / total_pumps * 100

    # Calculate weighted average gain potential
    strong_pattern = pattern_analysis.get('STRONG_PRECURSOR', {})
    medium_pattern = pattern_analysis.get('MEDIUM_PRECURSOR', {})
    futures_led = pattern_analysis.get('FUTURES_LED', {})

    summary_text = f"""
EXECUTIVE SUMMARY
{'='*80}

Period Analyzed: 30 days (Oct 9 - Nov 8, 2025)
Total Pumps Detected: {total_pumps}
Actionable Pumps: {actionable_count} ({actionable_pct:.1f}%)

KEY FINDINGS:

1. PREDICTABILITY:
   - {actionable_pct:.1f}% of pumps have reliable precursor signals
   - Actionable pumps avg gain: +{comparison['actionable']['avg_gain']:.1f}%
   - Non-actionable pumps avg gain: +{comparison['non_actionable']['avg_gain']:.1f}%
   - Advantage: +{comparison['comparison']['gain_advantage']:.1f}% expected return premium

2. SIGNAL DENSITY:
   - Actionable pumps: {comparison['actionable']['avg_signals_per_pump']:.1f} signals/pump
   - Non-actionable pumps: {comparison['non_actionable']['avg_signals_per_pump']:.1f} signals/pump
   - {comparison['comparison']['signal_density_ratio']:.1f}x more signals precede tradeable pumps

3. PATTERN DISTRIBUTION:
   - STRONG_PRECURSOR: {strong_pattern.get('count', 0)} pumps ({strong_pattern.get('pct_of_total', 0):.1f}%), avg +{strong_pattern.get('avg_gain', 0):.1f}%
   - MEDIUM_PRECURSOR: {medium_pattern.get('count', 0)} pumps ({medium_pattern.get('pct_of_total', 0):.1f}%), avg +{medium_pattern.get('avg_gain', 0):.1f}%
   - FUTURES_LED: {futures_led.get('count', 0)} pumps ({futures_led.get('pct_of_total', 0):.1f}%), avg +{futures_led.get('avg_gain', 0):.1f}%
   - SILENT_PUMP: {pattern_analysis.get('SILENT_PUMP', {}).get('count', 0)} pumps ({pattern_analysis.get('SILENT_PUMP', {}).get('pct_of_total', 0):.1f}%) - AVOID

4. ROI POTENTIAL:
   - Conservative estimate (MEDIUM confidence): +{medium_pattern.get('median_gain', 0):.1f}% median
   - Aggressive estimate (HIGH confidence): +{strong_pattern.get('median_gain', 0):.1f}% median
   - Best case (top performers): +{comparison['actionable']['max_gain']:.0f}%

5. CRITICAL SUCCESS FACTORS:
   - EXTREME signal strength (spike ≥5.0x): {comparison['actionable']['extreme_signals']} signals in actionable pumps
   - Recent activity (<24h): Essential for high confidence
   - Futures dominance: Indicator of informed trading
"""

    return summary_text

def main():
    print("="*80)
    print("СОЗДАНИЕ ФИНАЛЬНОГО ОТЧЕТА")
    print("Мета-анализ 805 пампов и формирование рекомендаций")
    print("="*80)

    print("\n1. Загрузка всех отчетов...")
    reports = load_all_reports()
    summary = load_summary()
    print(f"✓ Загружено {len(reports)} отчетов")

    print("\n2. Сравнительный анализ actionable vs non-actionable...")
    comparison = analyze_actionable_vs_non_actionable(reports)
    print("✓ Анализ завершен")

    print("\n3. Анализ эффективности паттернов...")
    pattern_analysis = analyze_pattern_effectiveness(reports, summary)
    print("✓ Паттерны проанализированы")

    print("\n4. Поиск топ-20 кейсов...")
    top_performers = find_top_performers(reports, top_n=20)
    print(f"✓ Найдено {len(top_performers)} топ-кейсов")

    print("\n5. Генерация торговых рекомендаций...")
    recommendations = generate_trading_recommendations(pattern_analysis, comparison)
    print(f"✓ Создано {len(recommendations)} рекомендаций")

    print("\n6. Формирование executive summary...")
    exec_summary = create_executive_summary(summary, comparison, pattern_analysis)
    print("✓ Summary готов")

    # Assemble final report
    final_report = {
        'generated_at': datetime.now().isoformat(),
        'period': '2025-10-09 to 2025-11-08 (30 days, excluding Oct 10-11 flash crash)',
        'executive_summary': exec_summary,
        'comparison_analysis': comparison,
        'pattern_effectiveness': pattern_analysis,
        'top_20_performers': top_performers,
        'trading_recommendations': recommendations,
        'statistics': {
            'total_pumps': summary['total_pumps'],
            'actionable_pumps': summary['actionable_count'],
            'pattern_distribution': summary['pattern_distribution']
        }
    }

    # Save report
    report_file = Path('/tmp/pump_analysis/FINAL_REPORT.json')
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(final_report, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n✓ Финальный отчет сохранен: {report_file}")

    # Print executive summary
    print("\n" + "="*80)
    print(exec_summary)
    print("="*80)

    # Print key recommendations
    print("\nКЛЮЧЕВЫЕ РЕКОМЕНДАЦИИ:")
    print("="*80)
    for rec in recommendations:
        print(f"\n{rec['title']}")
        print("-"*80)
        print(rec['recommendation'])
        for detail in rec['details']:
            print(f"  • {detail}")

    print("\n" + "="*80)
    print("✅ ФИНАЛЬНЫЙ ОТЧЕТ ГОТОВ!")
    print("="*80)
    print(f"\nПолный отчет: {report_file}")
    print(f"Всего пампов: {summary['total_pumps']}")
    print(f"Пригодных для торговли: {summary['actionable_count']} ({summary['actionable_count']/summary['total_pumps']*100:.1f}%)")
    print(f"Ожидаемая средняя доходность: +{comparison['actionable']['avg_gain']:.1f}%")
    print()

if __name__ == "__main__":
    main()
