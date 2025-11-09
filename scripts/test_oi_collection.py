#!/home/elcrypto/pump_detector/venv/bin/python3
"""
Тестовый скрипт для проверки сбора OI данных
Проверяет работу метода get_oi_data() на нескольких парах
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from daemons.detector_daemon import PumpDetectorDaemon
import psycopg2
from psycopg2.extras import RealDictCursor

# Тестовые пары (trading_pair_id, pair_symbol)
TEST_PAIRS = [
    (2169, 'FILUSDT'),   # FIL
    (2061, 'BTCUSDT'),   # BTC
    (2062, 'ETHUSDT'),   # ETH
    (2233, 'SOLUSDT'),   # SOL
    (2289, 'BNBUSDT'),   # BNB
]

def test_oi_collection():
    """Тестирование сбора OI данных"""

    print("="*60)
    print("ТЕСТ: Сбор OI данных из market_data")
    print("="*60)

    # Создаём экземпляр детектора
    detector = PumpDetectorDaemon()
    detector.connect()

    print(f"\n✓ Подключено к БД: {detector.db_config['dbname']}\n")

    # Тестируем каждую пару
    success_count = 0
    fail_count = 0

    for pair_id, pair_symbol in TEST_PAIRS:
        print(f"Проверка {pair_symbol} (ID: {pair_id})...")

        oi_data = detector.get_oi_data(pair_id)

        if oi_data:
            success_count += 1
            print(f"  ✓ Текущий OI: {oi_data['current_oi']:,.2f}")
            print(f"  ✓ OI change 7d: {oi_data['oi_change_pct']:+.2f}%")

            # Проверка на разумность значений
            if oi_data['current_oi'] <= 0:
                print(f"  ⚠️  ПРЕДУПРЕЖДЕНИЕ: OI <= 0")
            if abs(oi_data['oi_change_pct']) > 1000:
                print(f"  ⚠️  ПРЕДУПРЕЖДЕНИЕ: Экстремальное изменение OI")
        else:
            fail_count += 1
            print(f"  ✗ Нет OI данных")

        print()

    # Итоги
    print("="*60)
    print(f"РЕЗУЛЬТАТЫ:")
    print(f"  Успешно: {success_count}/{len(TEST_PAIRS)}")
    print(f"  Провалено: {fail_count}/{len(TEST_PAIRS)}")
    print("="*60)

    # Проверка покрытия в существующих сигналах
    print("\nПроверка существующих сигналов на наличие OI данных...")

    with detector.conn.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(oi_value) FILTER (WHERE oi_value IS NOT NULL) as has_oi,
                COUNT(oi_change_pct) FILTER (WHERE oi_change_pct IS NOT NULL) as has_oi_change,
                ROUND(AVG(oi_change_pct), 2) as avg_oi_change
            FROM pump.signals
            WHERE detected_at >= NOW() - INTERVAL '7 days'
        """)

        stats = cur.fetchone()

        total = stats['total']
        has_oi = stats['has_oi']
        has_oi_change = stats['has_oi_change']
        avg_oi_change = stats['avg_oi_change']

        coverage_pct = (has_oi / total * 100) if total > 0 else 0

        print(f"  Всего сигналов (7 дней): {total}")
        print(f"  С OI данными: {has_oi} ({coverage_pct:.1f}%)")
        print(f"  С OI change: {has_oi_change}")
        print(f"  Средний OI change: {avg_oi_change}%")

    # Закрываем соединение
    detector.conn.close()

    print("\n✓ Тест завершён\n")

    return success_count == len(TEST_PAIRS)

if __name__ == "__main__":
    try:
        success = test_oi_collection()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
