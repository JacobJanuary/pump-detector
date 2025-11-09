#!/home/elcrypto/pump_detector/venv/bin/python3
"""
Мониторинг покрытия OI данных в новых сигналах
Показывает последние сигналы и проверяет наличие OI данных
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import DATABASE
from datetime import datetime

def monitor_oi_coverage(minutes_back=60):
    """Мониторинг OI покрытия в недавних сигналах"""

    try:
        # Подключение к БД
        if not DATABASE.get('password'):
            conn_params = {
                'dbname': DATABASE['dbname'],
                'cursor_factory': RealDictCursor
            }
        else:
            conn_params = DATABASE.copy()
            conn_params['cursor_factory'] = RealDictCursor

        conn = psycopg2.connect(**conn_params)

        print("=" * 80)
        print(f"МОНИТОРИНГ OI ПОКРЫТИЯ - Последние {minutes_back} минут")
        print("=" * 80)
        print()

        # Последние сигналы с OI данными
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    pair_symbol,
                    signal_timestamp,
                    detected_at,
                    futures_spike_ratio_7d,
                    signal_strength,
                    oi_value,
                    oi_change_pct,
                    CASE
                        WHEN oi_value IS NOT NULL THEN '✓'
                        ELSE '✗'
                    END as has_oi
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL '%s minutes'
                ORDER BY detected_at DESC
                LIMIT 20
            """ % minutes_back)

            recent_signals = cur.fetchall()

            if not recent_signals:
                print(f"⚠️  Нет новых сигналов за последние {minutes_back} минут")
                print()
                print("Ожидание следующего цикла детекции...")
                print("(Детектор запускается каждые 5 минут)")
            else:
                print(f"Найдено {len(recent_signals)} сигналов:\n")

                print(f"{'ID':<6} {'Пара':<12} {'OI?':<5} {'Spike':<8} {'OI Value':<15} {'OI Change':<12} {'Время':<19}")
                print("-" * 80)

                with_oi = 0
                without_oi = 0

                for sig in recent_signals:
                    oi_val_str = f"{sig['oi_value']:,.0f}" if sig['oi_value'] else "N/A"
                    oi_chg_str = f"{sig['oi_change_pct']:+.1f}%" if sig['oi_change_pct'] else "N/A"
                    spike_str = f"{sig['futures_spike_ratio_7d']:.1f}x"
                    time_str = sig['detected_at'].strftime("%Y-%m-%d %H:%M:%S")

                    print(f"{sig['id']:<6} {sig['pair_symbol']:<12} {sig['has_oi']:<5} "
                          f"{spike_str:<8} {oi_val_str:<15} {oi_chg_str:<12} {time_str:<19}")

                    if sig['oi_value']:
                        with_oi += 1
                    else:
                        without_oi += 1

                print()
                print("=" * 80)
                print(f"СТАТИСТИКА:")
                print(f"  С OI данными: {with_oi}/{len(recent_signals)} ({with_oi/len(recent_signals)*100:.1f}%)")
                print(f"  Без OI данных: {without_oi}/{len(recent_signals)} ({without_oi/len(recent_signals)*100:.1f}%)")
                print("=" * 80)

        # Общая статистика за 24 часа
        print()
        print("СТАТИСТИКА ЗА 24 ЧАСА:")
        print("-" * 80)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(oi_value) FILTER (WHERE oi_value IS NOT NULL) as has_oi,
                    COUNT(oi_change_pct) FILTER (WHERE oi_change_pct IS NOT NULL) as has_oi_change,
                    ROUND(AVG(oi_change_pct), 2) as avg_oi_change,
                    MIN(detected_at) as first_signal,
                    MAX(detected_at) as last_signal
                FROM pump.signals
                WHERE detected_at >= NOW() - INTERVAL '24 hours'
            """)

            stats = cur.fetchone()

            if stats['total'] > 0:
                coverage_pct = (stats['has_oi'] / stats['total'] * 100)

                print(f"  Всего сигналов: {stats['total']}")
                print(f"  С OI данными: {stats['has_oi']} ({coverage_pct:.1f}%)")
                print(f"  С OI change: {stats['has_oi_change']}")

                if stats['avg_oi_change']:
                    print(f"  Средний OI change: {stats['avg_oi_change']:+.2f}%")

                print(f"  Первый сигнал: {stats['first_signal'].strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Последний сигнал: {stats['last_signal'].strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                print("  Нет сигналов за последние 24 часа")

        conn.close()
        print()

    except Exception as e:
        print(f"\n✗ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Мониторинг OI покрытия в сигналах')
    parser.add_argument('-m', '--minutes', type=int, default=60,
                      help='Показать сигналы за последние N минут (по умолчанию: 60)')

    args = parser.parse_args()

    monitor_oi_coverage(args.minutes)
