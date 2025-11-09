#!/usr/bin/env python3
"""
Скрипт для обновления pump_phase для всех ACTIVE кандидатов
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import DATABASE
from engine.pump_detection_engine import PumpDetectionEngine
from engine.database_helper import PumpDatabaseHelper
from datetime import datetime

def main():
    # Initialize database and engine
    db = PumpDatabaseHelper(DATABASE)
    db.connect()

    engine = PumpDetectionEngine(db)

    # Get all active candidates
    candidates = db.get_active_candidates()

    print(f"Найдено {len(candidates)} активных кандидатов")
    print("Обновляем pump_phase для каждого...")

    for candidate in candidates:
        symbol = candidate['pair_symbol']
        print(f"\n{symbol}:", end=' ')

        try:
            # Get signals for this symbol
            signals = db.get_signals_last_n_days(symbol, days=30)

            if not signals:
                print("нет сигналов, пропуск")
                continue

            # Calculate pump phase
            pump_phase, phase_metrics = engine.calculate_pump_phase(symbol, signals)

            print(f"{pump_phase} | Price: {phase_metrics['price_change_from_first']}% | 24h: {phase_metrics['price_change_24h']}% | Last pump: {phase_metrics['hours_since_last_pump']}h")

            # Update in DB
            update_data = {
                'pair_symbol': symbol,
                'trading_pair_id': candidate['trading_pair_id'],
                'confidence': candidate['confidence'],
                'score': candidate['score'],
                'pattern_type': candidate['pattern_type'],
                'total_signals': candidate['total_signals'],
                'extreme_signals': candidate['extreme_signals'],
                'critical_window_signals': candidate['critical_window_signals'],
                'eta_hours': candidate['eta_hours'],
                'is_actionable': candidate['is_actionable'],
                'pump_phase': pump_phase,
                'price_change_from_first': phase_metrics['price_change_from_first'],
                'price_change_24h': phase_metrics['price_change_24h'],
                'hours_since_last_pump': phase_metrics['hours_since_last_pump']
            }

            db.create_or_update_candidate(update_data)

        except Exception as e:
            print(f"ОШИБКА: {e}")
            continue

    db.close()
    print("\n\nГотово!")

if __name__ == '__main__':
    main()
