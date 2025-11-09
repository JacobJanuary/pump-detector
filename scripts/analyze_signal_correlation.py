#!/usr/bin/env python3
"""
Signal Success Correlation Analysis
Analyzes correlation between signal success and token characteristics:
- Meme coins vs non-meme coins
- Market cap tiers
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
import sys
import json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.settings import DATABASE

def get_db_connection():
    """Establish database connection"""
    return psycopg2.connect(**DATABASE, cursor_factory=RealDictCursor)

def load_pumps():
    """Load detected pumps from JSON file"""
    pumps_file = Path('/tmp/pump_analysis/pumps_found.json')

    if not pumps_file.exists():
        print("❌ Файл с пампами не найден")
        sys.exit(1)

    with open(pumps_file, 'r') as f:
        return json.load(f)

def get_token_characteristics(conn, symbol):
    """
    Get token characteristics: is_meme_coin and market_cap
    """
    query = """
    SELECT
        tp.id as trading_pair_id,
        tp.pair_symbol,
        public.is_meme_coin(tp.id) as is_meme_coin,
        c.market_cap
    FROM public.trading_pairs as tp
    LEFT JOIN public.tokens as t ON t.id = tp.token_id
    LEFT JOIN public.cmc_crypto as c ON t.cmc_token_id = c.cmc_token_id
    WHERE tp.pair_symbol = %s
    """

    with conn.cursor() as cur:
        cur.execute(query, (symbol,))
        result = cur.fetchone()

        if result:
            return {
                'trading_pair_id': result['trading_pair_id'],
                'is_meme_coin': result['is_meme_coin'],
                'market_cap': float(result['market_cap']) if result['market_cap'] else None
            }
        else:
            return {
                'trading_pair_id': None,
                'is_meme_coin': None,
                'market_cap': None
            }

def categorize_market_cap(market_cap):
    """Categorize market cap into tiers"""
    if market_cap is None:
        return 'UNKNOWN'
    elif market_cap < 10_000_000:  # < $10M
        return 'MICRO_CAP'
    elif market_cap < 100_000_000:  # $10M - $100M
        return 'SMALL_CAP'
    elif market_cap < 1_000_000_000:  # $100M - $1B
        return 'MID_CAP'
    elif market_cap < 10_000_000_000:  # $1B - $10B
        return 'LARGE_CAP'
    else:  # > $10B
        return 'MEGA_CAP'

def analyze_correlation(conn, pumps):
    """
    Analyze correlation between pump success and token characteristics
    """
    print("\n🔍 Анализ корреляции характеристик токенов с успешностью пампов...")
    print("="*80)

    # Load analysis summary to know which pumps are actionable
    summary_file = Path('/tmp/pump_analysis/analysis_summary.json')
    with open(summary_file, 'r') as f:
        summary = json.load(f)

    actionable_indices = {p['idx'] for p in summary['actionable_pumps']}

    # Statistics by category
    meme_stats = {
        'meme_coin': {'total': 0, 'actionable': 0, 'gains': []},
        'non_meme_coin': {'total': 0, 'actionable': 0, 'gains': []},
        'unknown': {'total': 0, 'actionable': 0, 'gains': []}
    }

    mcap_stats = defaultdict(lambda: {'total': 0, 'actionable': 0, 'gains': [], 'market_caps': []})

    # Pattern distribution by category
    meme_patterns = defaultdict(int)
    non_meme_patterns = defaultdict(int)
    mcap_patterns = defaultdict(lambda: defaultdict(int))

    # Process each pump
    for idx, pump in enumerate(pumps, 1):
        symbol = pump['symbol']
        gain = float(pump['max_gain_24h'])
        is_actionable = idx in actionable_indices

        # Get token characteristics
        chars = get_token_characteristics(conn, symbol)

        # Get pattern from report
        report_files = list(Path('/tmp/pump_analysis/reports').glob(f"{idx:03d}_*.json"))
        pattern = 'UNKNOWN'
        if report_files:
            with open(report_files[0], 'r') as f:
                report = json.load(f)
                pattern = report['analysis'].get('pattern_type', 'UNKNOWN')

        # Meme coin analysis
        if chars['is_meme_coin'] is True:
            category = 'meme_coin'
        elif chars['is_meme_coin'] is False:
            category = 'non_meme_coin'
        else:
            category = 'unknown'

        meme_stats[category]['total'] += 1
        meme_stats[category]['gains'].append(gain)
        if is_actionable:
            meme_stats[category]['actionable'] += 1

        if chars['is_meme_coin'] is True:
            meme_patterns[pattern] += 1
        elif chars['is_meme_coin'] is False:
            non_meme_patterns[pattern] += 1

        # Market cap analysis
        mcap_category = categorize_market_cap(chars['market_cap'])
        mcap_stats[mcap_category]['total'] += 1
        mcap_stats[mcap_category]['gains'].append(gain)
        if is_actionable:
            mcap_stats[mcap_category]['actionable'] += 1
        if chars['market_cap']:
            mcap_stats[mcap_category]['market_caps'].append(chars['market_cap'])
        mcap_patterns[mcap_category][pattern] += 1

        if idx % 100 == 0:
            print(f"Processed {idx}/{len(pumps)} pumps...")

    print(f"✓ Обработано {len(pumps)} пампов")

    return {
        'meme_stats': meme_stats,
        'mcap_stats': dict(mcap_stats),
        'meme_patterns': dict(meme_patterns),
        'non_meme_patterns': dict(non_meme_patterns),
        'mcap_patterns': {k: dict(v) for k, v in mcap_patterns.items()}
    }

def print_analysis(analysis):
    """Print detailed analysis results"""

    print("\n" + "="*80)
    print("КОРРЕЛЯЦИЯ: МЕМКОИНЫ vs НЕ-МЕМКОИНЫ")
    print("="*80)

    meme_stats = analysis['meme_stats']

    for category in ['meme_coin', 'non_meme_coin', 'unknown']:
        stats = meme_stats[category]
        if stats['total'] == 0:
            continue

        avg_gain = sum(stats['gains']) / len(stats['gains']) if stats['gains'] else 0
        median_gain = sorted(stats['gains'])[len(stats['gains'])//2] if stats['gains'] else 0
        actionable_pct = (stats['actionable'] / stats['total'] * 100) if stats['total'] > 0 else 0

        category_name = {
            'meme_coin': 'МЕМКОИНЫ',
            'non_meme_coin': 'НЕ-МЕМКОИНЫ',
            'unknown': 'НЕИЗВЕСТНО'
        }[category]

        print(f"\n{category_name}:")
        print(f"  Всего пампов: {stats['total']}")
        print(f"  Actionable: {stats['actionable']} ({actionable_pct:.1f}%)")
        print(f"  Средний gain: +{avg_gain:.1f}%")
        print(f"  Медианный gain: +{median_gain:.1f}%")
        print(f"  Max gain: +{max(stats['gains']):.1f}%")
        print(f"  Min gain: +{min(stats['gains']):.1f}%")

    # Top patterns for meme coins
    if analysis['meme_patterns']:
        print(f"\nТоп-5 паттернов для МЕМКОИНОВ:")
        sorted_patterns = sorted(analysis['meme_patterns'].items(), key=lambda x: -x[1])
        for pattern, count in sorted_patterns[:5]:
            pct = count / meme_stats['meme_coin']['total'] * 100 if meme_stats['meme_coin']['total'] > 0 else 0
            print(f"  {pattern}: {count} ({pct:.1f}%)")

    if analysis['non_meme_patterns']:
        print(f"\nТоп-5 паттернов для НЕ-МЕМКОИНОВ:")
        sorted_patterns = sorted(analysis['non_meme_patterns'].items(), key=lambda x: -x[1])
        for pattern, count in sorted_patterns[:5]:
            pct = count / meme_stats['non_meme_coin']['total'] * 100 if meme_stats['non_meme_coin']['total'] > 0 else 0
            print(f"  {pattern}: {count} ({pct:.1f}%)")

    # Market cap analysis
    print("\n" + "="*80)
    print("КОРРЕЛЯЦИЯ: MARKET CAP")
    print("="*80)

    mcap_stats = analysis['mcap_stats']

    # Sort by market cap size
    mcap_order = ['MEGA_CAP', 'LARGE_CAP', 'MID_CAP', 'SMALL_CAP', 'MICRO_CAP', 'UNKNOWN']

    for mcap_category in mcap_order:
        if mcap_category not in mcap_stats:
            continue

        stats = mcap_stats[mcap_category]
        if stats['total'] == 0:
            continue

        avg_gain = sum(stats['gains']) / len(stats['gains']) if stats['gains'] else 0
        median_gain = sorted(stats['gains'])[len(stats['gains'])//2] if stats['gains'] else 0
        actionable_pct = (stats['actionable'] / stats['total'] * 100) if stats['total'] > 0 else 0

        avg_mcap = sum(stats['market_caps']) / len(stats['market_caps']) if stats['market_caps'] else 0

        mcap_range = {
            'MEGA_CAP': '> $10B',
            'LARGE_CAP': '$1B - $10B',
            'MID_CAP': '$100M - $1B',
            'SMALL_CAP': '$10M - $100M',
            'MICRO_CAP': '< $10M',
            'UNKNOWN': 'Unknown'
        }[mcap_category]

        print(f"\n{mcap_category} ({mcap_range}):")
        print(f"  Всего пампов: {stats['total']}")
        print(f"  Actionable: {stats['actionable']} ({actionable_pct:.1f}%)")
        print(f"  Средний gain: +{avg_gain:.1f}%")
        print(f"  Медианный gain: +{median_gain:.1f}%")
        if avg_mcap > 0:
            print(f"  Средний market cap: ${avg_mcap:,.0f}")

        # Top patterns for this mcap tier
        if mcap_category in analysis['mcap_patterns']:
            patterns = analysis['mcap_patterns'][mcap_category]
            sorted_patterns = sorted(patterns.items(), key=lambda x: -x[1])[:3]
            if sorted_patterns:
                print(f"  Топ-3 паттерна:")
                for pattern, count in sorted_patterns:
                    pct = count / stats['total'] * 100
                    print(f"    {pattern}: {count} ({pct:.1f}%)")

    # Key insights
    print("\n" + "="*80)
    print("КЛЮЧЕВЫЕ ВЫВОДЫ")
    print("="*80)

    # Meme coin actionability comparison
    meme_actionable_pct = (meme_stats['meme_coin']['actionable'] / meme_stats['meme_coin']['total'] * 100) if meme_stats['meme_coin']['total'] > 0 else 0
    non_meme_actionable_pct = (meme_stats['non_meme_coin']['actionable'] / meme_stats['non_meme_coin']['total'] * 100) if meme_stats['non_meme_coin']['total'] > 0 else 0

    meme_avg_gain = sum(meme_stats['meme_coin']['gains']) / len(meme_stats['meme_coin']['gains']) if meme_stats['meme_coin']['gains'] else 0
    non_meme_avg_gain = sum(meme_stats['non_meme_coin']['gains']) / len(meme_stats['non_meme_coin']['gains']) if meme_stats['non_meme_coin']['gains'] else 0

    print(f"\n1. МЕМКОИНЫ vs НЕ-МЕМКОИНЫ:")
    print(f"   - Мемкоины actionable: {meme_actionable_pct:.1f}%")
    print(f"   - Не-мемкоины actionable: {non_meme_actionable_pct:.1f}%")
    print(f"   - Разница: {meme_actionable_pct - non_meme_actionable_pct:+.1f}%")
    print(f"   - Мемкоины средний gain: +{meme_avg_gain:.1f}%")
    print(f"   - Не-мемкоины средний gain: +{non_meme_avg_gain:.1f}%")
    print(f"   - Разница gain: {meme_avg_gain - non_meme_avg_gain:+.1f}%")

    # Best market cap tier
    best_mcap_actionable = None
    best_mcap_pct = 0
    best_mcap_gain = None
    best_gain_value = 0

    for mcap_category in mcap_order:
        if mcap_category not in mcap_stats or mcap_category == 'UNKNOWN':
            continue
        stats = mcap_stats[mcap_category]
        if stats['total'] < 10:  # Skip categories with too few samples
            continue

        actionable_pct = (stats['actionable'] / stats['total'] * 100) if stats['total'] > 0 else 0
        avg_gain = sum(stats['gains']) / len(stats['gains']) if stats['gains'] else 0

        if actionable_pct > best_mcap_pct:
            best_mcap_pct = actionable_pct
            best_mcap_actionable = mcap_category

        if avg_gain > best_gain_value:
            best_gain_value = avg_gain
            best_mcap_gain = mcap_category

    print(f"\n2. MARKET CAP:")
    if best_mcap_actionable:
        print(f"   - Наибольшая actionability: {best_mcap_actionable} ({best_mcap_pct:.1f}%)")
    if best_mcap_gain:
        print(f"   - Наибольший средний gain: {best_mcap_gain} (+{best_gain_value:.1f}%)")

    # Inverse correlation check
    mcap_actionable_by_tier = []
    for mcap_category in ['MICRO_CAP', 'SMALL_CAP', 'MID_CAP', 'LARGE_CAP', 'MEGA_CAP']:
        if mcap_category in mcap_stats and mcap_stats[mcap_category]['total'] >= 5:
            stats = mcap_stats[mcap_category]
            actionable_pct = (stats['actionable'] / stats['total'] * 100) if stats['total'] > 0 else 0
            mcap_actionable_by_tier.append((mcap_category, actionable_pct))

    if len(mcap_actionable_by_tier) >= 3:
        print(f"\n3. КОРРЕЛЯЦИЯ С РАЗМЕРОМ MARKET CAP:")
        for tier, pct in mcap_actionable_by_tier:
            print(f"   - {tier}: {pct:.1f}% actionable")

def main():
    print("="*80)
    print("АНАЛИЗ КОРРЕЛЯЦИИ УСПЕШНОСТИ СИГНАЛОВ")
    print("Мемкоины vs Не-мемкоины | Market Cap тиры")
    print("="*80)

    # Load pumps
    print("\n📂 Загрузка списка пампов...")
    pumps = load_pumps()
    print(f"✓ Загружено {len(pumps)} пампов")

    # Connect to database
    conn = get_db_connection()

    try:
        # Analyze correlation
        analysis = analyze_correlation(conn, pumps)

        # Print results
        print_analysis(analysis)

        # Save results
        output_file = Path('/tmp/pump_analysis/correlation_analysis.json')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n✓ Результаты сохранены: {output_file}")

    finally:
        conn.close()

    print("\n" + "="*80)
    print("✅ АНАЛИЗ ЗАВЕРШЕН!")
    print("="*80)

if __name__ == "__main__":
    main()
