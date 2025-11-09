#!/usr/bin/env python3
"""
DEEP COMPREHENSIVE ANALYSIS
Глубочайший анализ всех 136 пампов для построения системы детекции
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone, timedelta
import sys
import json
from pathlib import Path
from collections import defaultdict
import statistics

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DATABASE

def get_db_connection():
    """Establish database connection"""
    return psycopg2.connect(**DATABASE, cursor_factory=RealDictCursor)

def load_pumps():
    """Load all detected pumps"""
    pumps_file = Path('/tmp/pump_analysis/pumps_found.json')
    with open(pumps_file, 'r') as f:
        return json.load(f)

def load_all_reports():
    """Load all individual pump reports"""
    reports_dir = Path('/tmp/pump_analysis/reports')
    reports = {}

    for report_file in sorted(reports_dir.glob('*.json')):
        with open(report_file, 'r') as f:
            report = json.load(f)
            idx = report['pump_index']
            reports[idx] = report

    return reports

def get_signals_for_pump(conn, pump, lookback_days=7):
    """
    Get ALL signals for a symbol within lookback period before pump
    """
    pump_time_ms = pump['pump_start_time']
    pump_time = datetime.fromtimestamp(pump_time_ms / 1000, tz=timezone.utc)

    lookback_start = pump_time - timedelta(days=lookback_days)
    lookback_start_ms = int(lookback_start.timestamp() * 1000)

    query = """
    SELECT
        s.id,
        s.trading_pair_id,
        tp.pair_symbol,
        tp.contract_type_id,
        s.detection_time,
        s.candle_time,
        s.signal_type,
        s.timeframe,
        s.spike_ratio,
        s.volume_usd,
        s.price_change,
        s.confidence_score,
        CASE
            WHEN tp.contract_type_id = 1 THEN 'FUTURES'
            WHEN tp.contract_type_id = 2 THEN 'SPOT'
            ELSE 'UNKNOWN'
        END as contract_type,
        -- Time to pump
        (%s - s.candle_time) / 1000.0 / 3600.0 as hours_before_pump
    FROM pump.signals s
    JOIN public.trading_pairs tp ON s.trading_pair_id = tp.id
    WHERE tp.pair_symbol = %s
      AND s.candle_time >= %s
      AND s.candle_time < %s
    ORDER BY s.candle_time ASC
    """

    with conn.cursor() as cur:
        cur.execute(query, (pump_time_ms, pump['symbol'], lookback_start_ms, pump_time_ms))
        signals = cur.fetchall()

    return [dict(s) for s in signals]

def analyze_signal_timing_windows(signals):
    """
    Analyze when signals appear in different time windows before pump
    """
    windows = {
        '0-12h': {'count': 0, 'signals': [], 'avg_spike': 0},
        '12-24h': {'count': 0, 'signals': [], 'avg_spike': 0},
        '24-48h': {'count': 0, 'signals': [], 'avg_spike': 0},
        '48-72h': {'count': 0, 'signals': [], 'avg_spike': 0},
        '72-96h': {'count': 0, 'signals': [], 'avg_spike': 0},
        '96-120h': {'count': 0, 'signals': [], 'avg_spike': 0},
        '120-168h': {'count': 0, 'signals': [], 'avg_spike': 0},
    }

    for sig in signals:
        hours = float(sig['hours_before_pump'])
        spike = float(sig['spike_ratio'])

        if hours < 12:
            windows['0-12h']['count'] += 1
            windows['0-12h']['signals'].append(sig)
            windows['0-12h']['avg_spike'] += spike
        elif hours < 24:
            windows['12-24h']['count'] += 1
            windows['12-24h']['signals'].append(sig)
            windows['12-24h']['avg_spike'] += spike
        elif hours < 48:
            windows['24-48h']['count'] += 1
            windows['24-48h']['signals'].append(sig)
            windows['24-48h']['avg_spike'] += spike
        elif hours < 72:
            windows['48-72h']['count'] += 1
            windows['48-72h']['signals'].append(sig)
            windows['48-72h']['avg_spike'] += spike
        elif hours < 96:
            windows['72-96h']['count'] += 1
            windows['72-96h']['signals'].append(sig)
            windows['72-96h']['avg_spike'] += spike
        elif hours < 120:
            windows['96-120h']['count'] += 1
            windows['96-120h']['signals'].append(sig)
            windows['96-120h']['avg_spike'] += spike
        else:
            windows['120-168h']['count'] += 1
            windows['120-168h']['signals'].append(sig)
            windows['120-168h']['avg_spike'] += spike

    # Calculate averages
    for window in windows.values():
        if window['count'] > 0:
            window['avg_spike'] = window['avg_spike'] / window['count']

    return windows

def analyze_signal_strength_distribution(signals):
    """
    Categorize signals by strength
    """
    extreme = []  # spike >= 5.0
    very_strong = []  # 3.0 <= spike < 5.0
    strong = []  # 2.0 <= spike < 3.0
    medium = []  # 1.5 <= spike < 2.0
    weak = []  # spike < 1.5

    for sig in signals:
        spike = float(sig['spike_ratio'])
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
        'extreme': extreme,
        'very_strong': very_strong,
        'strong': strong,
        'medium': medium,
        'weak': weak
    }

def analyze_spot_futures_dynamics(signals):
    """
    Analyze SPOT vs FUTURES signal distribution and timing
    """
    spot_signals = [s for s in signals if s['contract_type'] == 'SPOT']
    futures_signals = [s for s in signals if s['contract_type'] == 'FUTURES']

    # Which came first?
    first_signal = None
    if signals:
        first_signal = signals[0]['contract_type']

    # Ratio analysis
    spot_count = len(spot_signals)
    futures_count = len(futures_signals)

    # Average spike by type
    spot_avg_spike = statistics.mean([float(s['spike_ratio']) for s in spot_signals]) if spot_signals else 0
    futures_avg_spike = statistics.mean([float(s['spike_ratio']) for s in futures_signals]) if futures_signals else 0

    # Timing: when SPOT vs FUTURES appear
    spot_timing = [float(s['hours_before_pump']) for s in spot_signals]
    futures_timing = [float(s['hours_before_pump']) for s in futures_signals]

    return {
        'spot_count': spot_count,
        'futures_count': futures_count,
        'ratio': futures_count / spot_count if spot_count > 0 else (float('inf') if futures_count > 0 else 0),
        'first_signal': first_signal,
        'spot_avg_spike': spot_avg_spike,
        'futures_avg_spike': futures_avg_spike,
        'spot_avg_hours': statistics.mean(spot_timing) if spot_timing else 0,
        'futures_avg_hours': statistics.mean(futures_timing) if futures_timing else 0,
        'spot_earliest': min(spot_timing) if spot_timing else None,
        'futures_earliest': min(futures_timing) if futures_timing else None,
    }

def analyze_signal_escalation(signals):
    """
    Analyze if signals escalate (increase in frequency/strength) before pump
    """
    if not signals:
        return {'escalating': False}

    # Sort by time (earliest first)
    sorted_signals = sorted(signals, key=lambda x: x['candle_time'])

    # Divide into first half and second half
    mid = len(sorted_signals) // 2
    first_half = sorted_signals[:mid] if mid > 0 else []
    second_half = sorted_signals[mid:]

    # Compare counts
    first_half_count = len(first_half)
    second_half_count = len(second_half)

    # Compare average spike ratios
    first_half_avg_spike = statistics.mean([float(s['spike_ratio']) for s in first_half]) if first_half else 0
    second_half_avg_spike = statistics.mean([float(s['spike_ratio']) for s in second_half]) if second_half else 0

    # Escalation = second half has more signals or stronger signals
    escalating = second_half_count > first_half_count or second_half_avg_spike > first_half_avg_spike

    return {
        'escalating': escalating,
        'first_half_count': first_half_count,
        'second_half_count': second_half_count,
        'first_half_avg_spike': first_half_avg_spike,
        'second_half_avg_spike': second_half_avg_spike,
        'escalation_ratio': second_half_count / first_half_count if first_half_count > 0 else 0
    }

def categorize_success(pattern, confidence):
    """
    Determine if pump was actionable/successful
    """
    actionable_patterns = ['STRONG_PRECURSOR', 'MEDIUM_PRECURSOR', 'FUTURES_LED']
    actionable_confidence = ['HIGH', 'MEDIUM']

    is_actionable = pattern in actionable_patterns and confidence in actionable_confidence

    return {
        'is_actionable': is_actionable,
        'pattern': pattern,
        'confidence': confidence
    }

def deep_analyze_single_pump(conn, pump, report):
    """
    Deep analysis of a single pump
    """
    # Get all signals from the report (already collected)
    signals = report['signals']

    # Basic info
    pump_time = datetime.fromtimestamp(pump['pump_start_time'] / 1000, tz=timezone.utc)
    gain = float(pump['max_gain_24h'])

    # Categorize success
    pattern = report['analysis']['pattern_type']
    confidence = report['analysis']['confidence']
    success = categorize_success(pattern, confidence)

    # Timing analysis
    timing_windows = analyze_signal_timing_windows(signals)

    # Strength distribution
    strength_dist = analyze_signal_strength_distribution(signals)

    # SPOT/FUTURES dynamics
    spot_futures = analyze_spot_futures_dynamics(signals)

    # Signal escalation
    escalation = analyze_signal_escalation(signals)

    return {
        'idx': report['pump_index'],
        'symbol': pump['symbol'],
        'pump_time': pump_time.isoformat(),
        'gain': gain,
        'pattern': pattern,
        'confidence': confidence,
        'is_actionable': success['is_actionable'],
        'total_signals': len(signals),
        'timing_windows': timing_windows,
        'strength_distribution': {
            'extreme_count': len(strength_dist['extreme']),
            'very_strong_count': len(strength_dist['very_strong']),
            'strong_count': len(strength_dist['strong']),
            'medium_count': len(strength_dist['medium']),
            'weak_count': len(strength_dist['weak']),
        },
        'spot_futures': spot_futures,
        'escalation': escalation,
        'signals_detail': signals
    }

def main():
    print("="*80)
    print("ГЛУБОКИЙ АНАЛИЗ ВСЕХ ПАМПОВ")
    print("Детальное исследование каждого пампа за 7 дней до события")
    print("="*80)
    print()

    # Load data
    print("📂 Загрузка данных...")
    pumps = load_pumps()
    reports = load_all_reports()
    print(f"✓ Загружено {len(pumps)} пампов и {len(reports)} отчетов")
    print()

    # Connect to DB
    conn = get_db_connection()

    try:
        # Deep analysis of each pump
        print("🔬 Начинаю глубокий анализ каждого пампа...")
        print()

        all_analyses = []

        for idx, pump in enumerate(pumps, 1):
            if idx not in reports:
                print(f"⚠️  Отчет #{idx} не найден, пропускаю...")
                continue

            report = reports[idx]

            print(f"[{idx}/{len(pumps)}] Анализирую {pump['symbol']} (+{pump['max_gain_24h']:.1f}%)...", end=' ')

            analysis = deep_analyze_single_pump(conn, pump, report)
            all_analyses.append(analysis)

            print(f"✓ {analysis['total_signals']} сигналов")

        print()
        print("="*80)
        print("✅ ГЛУБОКИЙ АНАЛИЗ ЗАВЕРШЕН")
        print("="*80)
        print()

        # Save detailed analysis
        output_file = Path('/tmp/pump_analysis/deep_analysis_all_pumps.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_analyses, f, indent=2, ensure_ascii=False, default=str)

        print(f"✓ Детальный анализ сохранен: {output_file}")
        print()

        # Now run aggregated analysis
        print("="*80)
        print("АГРЕГИРОВАННЫЙ АНАЛИЗ ЗАКОНОМЕРНОСТЕЙ")
        print("="*80)
        print()

        # Separate actionable vs non-actionable
        actionable = [a for a in all_analyses if a['is_actionable']]
        non_actionable = [a for a in all_analyses if not a['is_actionable']]

        print(f"Actionable пампов: {len(actionable)} ({len(actionable)/len(all_analyses)*100:.1f}%)")
        print(f"Non-actionable пампов: {len(non_actionable)} ({len(non_actionable)/len(all_analyses)*100:.1f}%)")
        print()

        # === HYPOTHESIS 1: Timing Windows Matter ===
        print("="*80)
        print("ГИПОТЕЗА 1: Временные окна имеют значение")
        print("="*80)
        print()

        # Calculate average signal count per window for actionable vs non-actionable
        windows = ['0-12h', '12-24h', '24-48h', '48-72h', '72-96h', '96-120h', '120-168h']

        print("ACTIONABLE пампы - среднее количество сигналов по окнам:")
        for window in windows:
            counts = [a['timing_windows'][window]['count'] for a in actionable]
            avg = statistics.mean(counts) if counts else 0
            spikes = [a['timing_windows'][window]['avg_spike'] for a in actionable if a['timing_windows'][window]['count'] > 0]
            avg_spike = statistics.mean(spikes) if spikes else 0
            print(f"  {window:12s}: {avg:5.2f} сигналов, avg spike: {avg_spike:.2f}x")

        print()
        print("NON-ACTIONABLE пампы - среднее количество сигналов по окнам:")
        for window in windows:
            counts = [a['timing_windows'][window]['count'] for a in non_actionable]
            avg = statistics.mean(counts) if counts else 0
            spikes = [a['timing_windows'][window]['avg_spike'] for a in non_actionable if a['timing_windows'][window]['count'] > 0]
            avg_spike = statistics.mean(spikes) if spikes else 0
            print(f"  {window:12s}: {avg:5.2f} сигналов, avg spike: {avg_spike:.2f}x")

        print()

        # === HYPOTHESIS 2: Signal Strength Distribution ===
        print("="*80)
        print("ГИПОТЕЗА 2: Распределение силы сигналов критично")
        print("="*80)
        print()

        print("ACTIONABLE пампы - распределение по силе:")
        for strength in ['extreme_count', 'very_strong_count', 'strong_count', 'medium_count', 'weak_count']:
            counts = [a['strength_distribution'][strength] for a in actionable]
            avg = statistics.mean(counts) if counts else 0
            total_with = len([c for c in counts if c > 0])
            print(f"  {strength:20s}: avg {avg:5.2f}, присутствует в {total_with}/{len(actionable)} ({total_with/len(actionable)*100:.1f}%)")

        print()
        print("NON-ACTIONABLE пампы - распределение по силе:")
        for strength in ['extreme_count', 'very_strong_count', 'strong_count', 'medium_count', 'weak_count']:
            counts = [a['strength_distribution'][strength] for a in non_actionable]
            avg = statistics.mean(counts) if counts else 0
            total_with = len([c for c in counts if c > 0])
            print(f"  {strength:20s}: avg {avg:5.2f}, присутствует в {total_with}/{len(non_actionable)} ({total_with/len(non_actionable)*100:.1f}%)")

        print()

        # === HYPOTHESIS 3: SPOT/FUTURES Dynamics ===
        print("="*80)
        print("ГИПОТЕЗА 3: Динамика SPOT/FUTURES предсказывает успех")
        print("="*80)
        print()

        print("ACTIONABLE пампы:")
        spot_counts = [a['spot_futures']['spot_count'] for a in actionable]
        futures_counts = [a['spot_futures']['futures_count'] for a in actionable]
        ratios = [a['spot_futures']['ratio'] for a in actionable if a['spot_futures']['ratio'] != float('inf')]

        print(f"  Avg SPOT signals: {statistics.mean(spot_counts):.2f}")
        print(f"  Avg FUTURES signals: {statistics.mean(futures_counts):.2f}")
        print(f"  Avg FUTURES/SPOT ratio: {statistics.mean(ratios):.2f}" if ratios else "  Avg FUTURES/SPOT ratio: N/A")

        # First signal analysis
        first_spot = len([a for a in actionable if a['spot_futures']['first_signal'] == 'SPOT'])
        first_futures = len([a for a in actionable if a['spot_futures']['first_signal'] == 'FUTURES'])
        print(f"  Первый сигнал SPOT: {first_spot} ({first_spot/len(actionable)*100:.1f}%)")
        print(f"  Первый сигнал FUTURES: {first_futures} ({first_futures/len(actionable)*100:.1f}%)")

        print()
        print("NON-ACTIONABLE пампы:")
        spot_counts = [a['spot_futures']['spot_count'] for a in non_actionable]
        futures_counts = [a['spot_futures']['futures_count'] for a in non_actionable]
        ratios = [a['spot_futures']['ratio'] for a in non_actionable if a['spot_futures']['ratio'] != float('inf') and a['spot_futures']['ratio'] != 0]

        print(f"  Avg SPOT signals: {statistics.mean(spot_counts):.2f}")
        print(f"  Avg FUTURES signals: {statistics.mean(futures_counts):.2f}")
        print(f"  Avg FUTURES/SPOT ratio: {statistics.mean(ratios):.2f}" if ratios else "  Avg FUTURES/SPOT ratio: N/A")

        # First signal analysis
        first_spot = len([a for a in non_actionable if a['spot_futures']['first_signal'] == 'SPOT'])
        first_futures = len([a for a in non_actionable if a['spot_futures']['first_signal'] == 'FUTURES'])
        print(f"  Первый сигнал SPOT: {first_spot} ({first_spot/len(non_actionable)*100:.1f}%)")
        print(f"  Первый сигнал FUTURES: {first_futures} ({first_futures/len(non_actionable)*100:.1f}%)")

        print()

        # === HYPOTHESIS 4: Signal Escalation Predicts Success ===
        print("="*80)
        print("ГИПОТЕЗА 4: Эскалация сигналов предсказывает успех")
        print("="*80)
        print()

        print("ACTIONABLE пампы:")
        escalating_actionable = [a for a in actionable if a['escalation']['escalating']]
        print(f"  Эскалация присутствует: {len(escalating_actionable)}/{len(actionable)} ({len(escalating_actionable)/len(actionable)*100:.1f}%)")

        escalation_ratios = [a['escalation']['escalation_ratio'] for a in actionable if a['escalation']['escalation_ratio'] > 0]
        if escalation_ratios:
            print(f"  Avg escalation ratio: {statistics.mean(escalation_ratios):.2f}x")

        print()
        print("NON-ACTIONABLE пампы:")
        escalating_non_actionable = [a for a in non_actionable if a['escalation']['escalating']]
        print(f"  Эскалация присутствует: {len(escalating_non_actionable)}/{len(non_actionable)} ({len(escalating_non_actionable)/len(non_actionable)*100:.1f}%)")

        escalation_ratios = [a['escalation']['escalation_ratio'] for a in non_actionable if a['escalation']['escalation_ratio'] > 0]
        if escalation_ratios:
            print(f"  Avg escalation ratio: {statistics.mean(escalation_ratios):.2f}x")

        print()

        # === HYPOTHESIS 5: Total Signal Count Correlation ===
        print("="*80)
        print("ГИПОТЕЗА 5: Общее количество сигналов коррелирует с успехом")
        print("="*80)
        print()

        actionable_signal_counts = [a['total_signals'] for a in actionable]
        non_actionable_signal_counts = [a['total_signals'] for a in non_actionable]

        print(f"ACTIONABLE: avg {statistics.mean(actionable_signal_counts):.2f} сигналов")
        print(f"            median {statistics.median(actionable_signal_counts):.0f} сигналов")
        print(f"            min {min(actionable_signal_counts)}, max {max(actionable_signal_counts)}")
        print()
        print(f"NON-ACTIONABLE: avg {statistics.mean(non_actionable_signal_counts):.2f} сигналов")
        print(f"                median {statistics.median(non_actionable_signal_counts):.0f} сигналов")
        print(f"                min {min(non_actionable_signal_counts)}, max {max(non_actionable_signal_counts)}")
        print()

        # Save aggregated analysis
        aggregated = {
            'summary': {
                'total_pumps': len(all_analyses),
                'actionable': len(actionable),
                'non_actionable': len(non_actionable),
                'actionable_pct': len(actionable) / len(all_analyses) * 100
            },
            'hypothesis_1_timing': {
                'actionable_by_window': {window: {
                    'avg_count': statistics.mean([a['timing_windows'][window]['count'] for a in actionable]),
                    'avg_spike': statistics.mean([a['timing_windows'][window]['avg_spike'] for a in actionable if a['timing_windows'][window]['count'] > 0]) if any(a['timing_windows'][window]['count'] > 0 for a in actionable) else 0
                } for window in windows},
                'non_actionable_by_window': {window: {
                    'avg_count': statistics.mean([a['timing_windows'][window]['count'] for a in non_actionable]),
                    'avg_spike': statistics.mean([a['timing_windows'][window]['avg_spike'] for a in non_actionable if a['timing_windows'][window]['count'] > 0]) if any(a['timing_windows'][window]['count'] > 0 for a in non_actionable) else 0
                } for window in windows}
            },
            'hypothesis_2_strength': {
                'actionable': {strength: {
                    'avg_count': statistics.mean([a['strength_distribution'][strength] for a in actionable]),
                    'presence_pct': len([a for a in actionable if a['strength_distribution'][strength] > 0]) / len(actionable) * 100
                } for strength in ['extreme_count', 'very_strong_count', 'strong_count', 'medium_count', 'weak_count']},
                'non_actionable': {strength: {
                    'avg_count': statistics.mean([a['strength_distribution'][strength] for a in non_actionable]),
                    'presence_pct': len([a for a in non_actionable if a['strength_distribution'][strength] > 0]) / len(non_actionable) * 100
                } for strength in ['extreme_count', 'very_strong_count', 'strong_count', 'medium_count', 'weak_count']}
            },
            'hypothesis_3_spot_futures': {
                'actionable': {
                    'avg_spot': statistics.mean([a['spot_futures']['spot_count'] for a in actionable]),
                    'avg_futures': statistics.mean([a['spot_futures']['futures_count'] for a in actionable]),
                    'avg_ratio': statistics.mean([a['spot_futures']['ratio'] for a in actionable if a['spot_futures']['ratio'] != float('inf')]) if any(a['spot_futures']['ratio'] != float('inf') for a in actionable) else None,
                    'first_signal_spot_pct': len([a for a in actionable if a['spot_futures']['first_signal'] == 'SPOT']) / len(actionable) * 100,
                    'first_signal_futures_pct': len([a for a in actionable if a['spot_futures']['first_signal'] == 'FUTURES']) / len(actionable) * 100
                },
                'non_actionable': {
                    'avg_spot': statistics.mean([a['spot_futures']['spot_count'] for a in non_actionable]),
                    'avg_futures': statistics.mean([a['spot_futures']['futures_count'] for a in non_actionable]),
                    'avg_ratio': statistics.mean([a['spot_futures']['ratio'] for a in non_actionable if a['spot_futures']['ratio'] != float('inf') and a['spot_futures']['ratio'] != 0]) if any(a['spot_futures']['ratio'] != float('inf') and a['spot_futures']['ratio'] != 0 for a in non_actionable) else None,
                    'first_signal_spot_pct': len([a for a in non_actionable if a['spot_futures']['first_signal'] == 'SPOT']) / len(non_actionable) * 100 if non_actionable else 0,
                    'first_signal_futures_pct': len([a for a in non_actionable if a['spot_futures']['first_signal'] == 'FUTURES']) / len(non_actionable) * 100 if non_actionable else 0
                }
            },
            'hypothesis_4_escalation': {
                'actionable': {
                    'escalation_pct': len([a for a in actionable if a['escalation']['escalating']]) / len(actionable) * 100,
                    'avg_escalation_ratio': statistics.mean([a['escalation']['escalation_ratio'] for a in actionable if a['escalation']['escalation_ratio'] > 0]) if any(a['escalation']['escalation_ratio'] > 0 for a in actionable) else 0
                },
                'non_actionable': {
                    'escalation_pct': len([a for a in non_actionable if a['escalation']['escalating']]) / len(non_actionable) * 100,
                    'avg_escalation_ratio': statistics.mean([a['escalation']['escalation_ratio'] for a in non_actionable if a['escalation']['escalation_ratio'] > 0]) if any(a['escalation']['escalation_ratio'] > 0 for a in non_actionable) else 0
                }
            },
            'hypothesis_5_total_signals': {
                'actionable': {
                    'avg': statistics.mean(actionable_signal_counts),
                    'median': statistics.median(actionable_signal_counts),
                    'min': min(actionable_signal_counts),
                    'max': max(actionable_signal_counts)
                },
                'non_actionable': {
                    'avg': statistics.mean(non_actionable_signal_counts),
                    'median': statistics.median(non_actionable_signal_counts),
                    'min': min(non_actionable_signal_counts),
                    'max': max(non_actionable_signal_counts)
                }
            }
        }

        aggregated_file = Path('/tmp/pump_analysis/aggregated_hypothesis_analysis.json')
        with open(aggregated_file, 'w', encoding='utf-8') as f:
            json.dump(aggregated, f, indent=2, ensure_ascii=False, default=str)

        print(f"✓ Агрегированный анализ сохранен: {aggregated_file}")
        print()

        print("="*80)
        print("✅ ГЛУБОКИЙ АНАЛИЗ ЗАВЕРШЕН!")
        print("="*80)

    finally:
        conn.close()

if __name__ == "__main__":
    main()
