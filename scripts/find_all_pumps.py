#!/usr/bin/env python3
"""
Find All Pumps in 30-Day Period
Detects sustained pumps (+20% in a day) for all symbols, excluding flash crash period
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

def find_pumps_for_all_symbols(conn):
    """
    Find all pumps (+20% in a day) for all symbols in last 30 days
    Excludes: Oct 10-11 (flash crash/bounce period)
    """

    # Period: last 30 days, excluding Oct 10-11
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=30)

    # Flash crash exclusion period
    exclude_start = datetime(2025, 10, 10, 0, 0, 0, tzinfo=timezone.utc)
    exclude_end = datetime(2025, 10, 11, 23, 59, 59, tzinfo=timezone.utc)

    print(f"Поиск пампов в период: {start_date.date()} - {end_date.date()}")
    print(f"Исключен период флеш-краша: {exclude_start.date()} - {exclude_end.date()}")
    print()

    # Convert to milliseconds for candles table
    start_ms = int(start_date.timestamp() * 1000)
    end_ms = int(end_date.timestamp() * 1000)
    exclude_start_ms = int(exclude_start.timestamp() * 1000)
    exclude_end_ms = int(exclude_end.timestamp() * 1000)

    query = """
    WITH daily_changes AS (
        SELECT
            tp.id as trading_pair_id,
            tp.pair_symbol as symbol,
            c.open_time,
            c.open_price,
            c.close_price,
            c.high_price,
            c.low_price,
            -- Price change within the candle
            ((c.high_price - c.open_price) / c.open_price * 100) as intra_candle_gain,
            -- Look ahead to next candles for sustained movement
            LEAD(c.close_price, 1) OVER (PARTITION BY tp.id ORDER BY c.open_time) as next_close_1,
            LEAD(c.close_price, 2) OVER (PARTITION BY tp.id ORDER BY c.open_time) as next_close_2,
            LEAD(c.close_price, 3) OVER (PARTITION BY tp.id ORDER BY c.open_time) as next_close_3,
            LEAD(c.close_price, 6) OVER (PARTITION BY tp.id ORDER BY c.open_time) as next_close_6
        FROM candles c
        JOIN trading_pairs tp ON c.trading_pair_id = tp.id
        WHERE c.interval_id = 4  -- 4h candles
          AND c.open_time >= %s
          AND c.open_time <= %s
          -- Exclude flash crash period
          AND NOT (c.open_time >= %s AND c.open_time <= %s)
          AND c.is_closed = true
          -- FILTERS: Only quality tokens (same as detector)
          AND tp.contract_type_id = 1  -- Futures only
          AND NOT public.is_meme_coin(tp.id)  -- No meme coins
          AND EXISTS (
              SELECT 1 FROM public.tokens t
              JOIN public.cmc_crypto cmc ON t.cmc_token_id = cmc.cmc_token_id
              WHERE t.id = tp.token_id AND cmc.market_cap >= 100000000  -- >= $100M market cap
          )
        ORDER BY tp.id, c.open_time
    ),
    pump_candidates AS (
        SELECT
            trading_pair_id,
            symbol,
            open_time,
            open_price,
            high_price,
            intra_candle_gain,
            -- Calculate max gain over next 24h (6 candles of 4h)
            GREATEST(
                (next_close_1 - open_price) / open_price * 100,
                (next_close_2 - open_price) / open_price * 100,
                (next_close_3 - open_price) / open_price * 100,
                (next_close_6 - open_price) / open_price * 100,
                intra_candle_gain
            ) as max_gain_24h,
            next_close_6
        FROM daily_changes
        WHERE next_close_6 IS NOT NULL  -- Need full 24h lookforward
    )
    SELECT
        trading_pair_id,
        symbol,
        open_time as pump_start_time,
        open_price as start_price,
        high_price,
        max_gain_24h,
        next_close_6 as price_after_24h
    FROM pump_candidates
    WHERE max_gain_24h >= 20.0  -- Minimum 20%% gain
    ORDER BY open_time ASC, max_gain_24h DESC
    """

    with conn.cursor() as cur:
        cur.execute(query, (start_ms, end_ms, exclude_start_ms, exclude_end_ms))
        pumps = cur.fetchall()

    return pumps

def consolidate_pumps(pumps):
    """
    Group pumps by symbol and remove duplicates within 48h window
    Keep the strongest pump for each symbol in each time window
    """
    if not pumps:
        return []

    consolidated = {}

    for pump in pumps:
        symbol = pump['symbol']
        pump_time = datetime.fromtimestamp(pump['pump_start_time'] / 1000, tz=timezone.utc)

        if symbol not in consolidated:
            consolidated[symbol] = []

        # Check if this pump is within 48h of existing pump for this symbol
        is_duplicate = False
        for existing_pump in consolidated[symbol]:
            existing_time = datetime.fromtimestamp(existing_pump['pump_start_time'] / 1000, tz=timezone.utc)
            time_diff_hours = abs((pump_time - existing_time).total_seconds() / 3600)

            if time_diff_hours <= 48:
                # Within 48h window - keep the stronger one
                if pump['max_gain_24h'] > existing_pump['max_gain_24h']:
                    # Replace with stronger pump
                    consolidated[symbol].remove(existing_pump)
                    consolidated[symbol].append(dict(pump))
                is_duplicate = True
                break

        if not is_duplicate:
            consolidated[symbol].append(dict(pump))

    # Flatten and sort
    result = []
    for symbol, symbol_pumps in consolidated.items():
        result.extend(symbol_pumps)

    result.sort(key=lambda x: x['pump_start_time'])
    return result

def main():
    print("="*80)
    print("ПОИСК ВСЕХ ПАМПОВ ЗА 30 ДНЕЙ")
    print("="*80)
    print()

    conn = get_db_connection()

    try:
        # Find all pumps
        print("🔍 Поиск пампов (+20% за 24ч)...")
        all_pumps = find_pumps_for_all_symbols(conn)
        print(f"✓ Найдено сырых кандидатов: {len(all_pumps)}")
        print()

        # Consolidate (remove duplicates within 48h windows)
        print("🔄 Консолидация пампов (удаление дубликатов в 48ч окнах)...")
        unique_pumps = consolidate_pumps(all_pumps)
        print(f"✓ Уникальных пампов: {len(unique_pumps)}")
        print()

        # Display results
        print("="*80)
        print("НАЙДЕННЫЕ ПАМПЫ")
        print("="*80)
        print()

        pumps_by_symbol = {}
        for pump in unique_pumps:
            symbol = pump['symbol']
            if symbol not in pumps_by_symbol:
                pumps_by_symbol[symbol] = []
            pumps_by_symbol[symbol].append(pump)

        print(f"Всего символов с пампами: {len(pumps_by_symbol)}")
        print()

        for idx, (symbol, pumps) in enumerate(sorted(pumps_by_symbol.items()), 1):
            print(f"{idx}. {symbol} - {len(pumps)} памп(ов)")
            for pump in pumps:
                pump_time = datetime.fromtimestamp(pump['pump_start_time'] / 1000, tz=timezone.utc)
                print(f"     Время: {pump_time}")
                print(f"     Старт: ${float(pump['start_price']):.4f}")
                print(f"     Макс gain (24h): +{float(pump['max_gain_24h']):.1f}%")
                print(f"     Цена через 24ч: ${float(pump['price_after_24h']):.4f}")
                print()

        # Save to JSON for next script
        output_file = Path('/tmp/pump_analysis/pumps_found.json')
        output_file.parent.mkdir(exist_ok=True)

        # Convert to JSON-serializable format
        pumps_data = []
        for pump in unique_pumps:
            pump_data = dict(pump)
            # Convert Decimal to float
            for key in ['start_price', 'high_price', 'max_gain_24h', 'price_after_24h']:
                if pump_data[key] is not None:
                    pump_data[key] = float(pump_data[key])
            pumps_data.append(pump_data)

        with open(output_file, 'w') as f:
            json.dump(pumps_data, f, indent=2, default=str)

        print(f"✓ Результаты сохранены в: {output_file}")
        print()

        print("="*80)
        print("СТАТИСТИКА")
        print("="*80)

        total_pumps = len(unique_pumps)
        total_symbols = len(pumps_by_symbol)

        # Gain distribution
        gains = [float(p['max_gain_24h']) for p in unique_pumps]
        avg_gain = sum(gains) / len(gains) if gains else 0
        max_gain = max(gains) if gains else 0
        min_gain = min(gains) if gains else 0

        print(f"Всего пампов: {total_pumps}")
        print(f"Уникальных символов: {total_symbols}")
        print(f"Средний gain: +{avg_gain:.1f}%")
        print(f"Макс gain: +{max_gain:.1f}%")
        print(f"Мин gain: +{min_gain:.1f}%")
        print()

        # Gain brackets
        brackets = {
            '20-50%': len([g for g in gains if 20 <= g < 50]),
            '50-100%': len([g for g in gains if 50 <= g < 100]),
            '100-200%': len([g for g in gains if 100 <= g < 200]),
            '200%+': len([g for g in gains if g >= 200]),
        }

        print("Распределение по gain:")
        for bracket, count in brackets.items():
            pct = count / total_pumps * 100 if total_pumps > 0 else 0
            print(f"  {bracket}: {count} ({pct:.1f}%)")

        print()
        print("="*80)
        print(f"✅ Готово! Найдено {total_pumps} пампов для анализа")
        print("="*80)

    finally:
        conn.close()

if __name__ == "__main__":
    main()
