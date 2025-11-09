#!/home/elcrypto/pump_detector/venv/bin/python3
"""
Health Check для системы детекции пампов
Проверяет все компоненты и выдаёт детальный отчёт
"""

import sys
import psycopg2
import requests
from datetime import datetime, timedelta
import subprocess
import json
import os

# Цвета для вывода
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_header():
    """Печатает заголовок"""
    print(f"{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.BOLD}    PUMP DETECTOR SYSTEM HEALTH CHECK{Colors.ENDC}")
    print(f"{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{Colors.BOLD}{'-'*60}{Colors.ENDC}\n")

def check_database():
    """Проверка доступности БД и статистики"""
    try:
        conn = psycopg2.connect(dbname='fox_crypto_new')
        with conn.cursor() as cur:
            # Проверяем общую статистику
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE detected_at > NOW() - INTERVAL '1 hour') as last_hour,
                    COUNT(*) FILTER (WHERE detected_at > NOW() - INTERVAL '24 hours') as last_day,
                    COUNT(*) FILTER (WHERE status = 'DETECTED') as detected,
                    COUNT(*) FILTER (WHERE status = 'MONITORING') as monitoring,
                    COUNT(*) FILTER (WHERE pump_realized = true) as pumps,
                    COUNT(*) as total
                FROM pump.signals
            """)
            stats = cur.fetchone()

            # Проверяем работу функции
            cur.execute("SELECT pump.calculate_confidence_score(700)")
            confidence_test = cur.fetchone()[0]

        conn.close()

        details = {
            'status': 'OK',
            'signals_last_hour': stats[0],
            'signals_last_day': stats[1],
            'active_detected': stats[2],
            'active_monitoring': stats[3],
            'total_pumps': stats[4],
            'total_signals': stats[5],
            'confidence_function': 'WORKING' if confidence_test else 'ERROR'
        }

        return True, details
    except Exception as e:
        return False, {'status': 'ERROR', 'message': str(e)}

def check_services():
    """Проверка systemd сервисов"""
    services = ['pump-detector', 'pump-spot-futures', 'pump-validator']
    results = {}

    for service in services:
        try:
            # Проверяем статус
            result = subprocess.run(
                ['systemctl', 'is-active', f'{service}.service'],
                capture_output=True, text=True
            )
            status = result.stdout.strip()

            # Получаем детали
            details_result = subprocess.run(
                ['systemctl', 'show', f'{service}.service',
                 '-p', 'MainPID,ActiveEnterTimestamp,NRestarts'],
                capture_output=True, text=True
            )

            details = {}
            for line in details_result.stdout.strip().split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    details[key] = value

            results[service] = {
                'status': status,
                'active': status == 'active',
                'pid': details.get('MainPID', '0'),
                'restarts': details.get('NRestarts', '0'),
                'started': details.get('ActiveEnterTimestamp', 'unknown')
            }
        except:
            results[service] = {'status': 'unknown', 'active': False}

    all_active = all(s['active'] for s in results.values())
    return all_active, results

def check_processes():
    """Проверка запущенных процессов"""
    try:
        # Проверяем количество процессов
        checks = [
            ('web_api.py', 1),  # Должен быть максимум 1
            ('detector_daemon.py', 1),  # Должен быть 1
            ('spot_futures_analyzer.py', 1),  # Должен быть 1
            ('validator_daemon.py', 1)  # Должен быть 1
        ]

        results = {}
        all_good = True

        for process_name, expected_max in checks:
            result = subprocess.run(
                f"ps aux | grep '{process_name}' | grep -v grep | wc -l",
                shell=True, capture_output=True, text=True
            )
            count = int(result.stdout.strip())

            if process_name == 'web_api.py':
                # Для API может быть 0 или 1
                is_ok = count <= expected_max
            else:
                # Для демонов должно быть ровно expected_max
                is_ok = count == expected_max

            if not is_ok:
                all_good = False

            results[process_name] = {
                'count': count,
                'expected': expected_max,
                'status': 'OK' if is_ok else 'ERROR'
            }

        return all_good, results
    except Exception as e:
        return False, {'error': str(e)}

def check_api():
    """Проверка Web API"""
    try:
        response = requests.get('http://localhost:5000/api/v1/status', timeout=5)
        if response.status_code == 200:
            data = response.json()
            return True, {
                'status': 'OK',
                'response_code': 200,
                'statistics': data.get('statistics', {})
            }
        else:
            return False, {
                'status': 'ERROR',
                'response_code': response.status_code
            }
    except requests.exceptions.ConnectionError:
        return False, {'status': 'NOT_RUNNING', 'message': 'Connection refused'}
    except Exception as e:
        return False, {'status': 'ERROR', 'message': str(e)}

def check_logs():
    """Проверка логов на ошибки"""
    log_files = [
        '/home/elcrypto/pump_detector/logs/detector.log',
        '/home/elcrypto/pump_detector/logs/spot_futures.log',
        '/home/elcrypto/pump_detector/logs/validator.log'
    ]

    results = {}
    has_critical = False

    for log_file in log_files:
        try:
            if os.path.exists(log_file):
                # Читаем последние 500 строк
                result = subprocess.run(
                    f"tail -500 {log_file} | grep -E 'ERROR|CRITICAL|WARNING' | wc -l",
                    shell=True, capture_output=True, text=True
                )
                error_count = int(result.stdout.strip())

                # Проверяем критические ошибки
                critical_result = subprocess.run(
                    f"tail -500 {log_file} | grep 'CRITICAL' | wc -l",
                    shell=True, capture_output=True, text=True
                )
                critical_count = int(critical_result.stdout.strip())

                if critical_count > 0:
                    has_critical = True

                # Получаем последнюю ошибку
                last_error_result = subprocess.run(
                    f"tail -100 {log_file} | grep ERROR | tail -1",
                    shell=True, capture_output=True, text=True
                )
                last_error = last_error_result.stdout.strip()[:100] if last_error_result.stdout else "None"

                log_name = os.path.basename(log_file)
                results[log_name] = {
                    'errors': error_count,
                    'critical': critical_count,
                    'last_error': last_error,
                    'status': 'CRITICAL' if critical_count > 0 else
                             'WARNING' if error_count > 10 else 'OK'
                }
            else:
                log_name = os.path.basename(log_file)
                results[log_name] = {'status': 'NOT_FOUND'}
        except Exception as e:
            log_name = os.path.basename(log_file)
            results[log_name] = {'status': 'ERROR', 'message': str(e)}

    return not has_critical, results

def check_disk_space():
    """Проверка свободного места на диске"""
    try:
        result = subprocess.run(
            "df -h /home/elcrypto/pump_detector | tail -1",
            shell=True, capture_output=True, text=True
        )
        parts = result.stdout.strip().split()
        if len(parts) >= 5:
            usage_percent = int(parts[4].replace('%', ''))
            available = parts[3]

            return usage_percent < 90, {
                'usage_percent': usage_percent,
                'available': available,
                'status': 'OK' if usage_percent < 90 else 'WARNING'
            }
    except:
        pass

    return True, {'status': 'UNKNOWN'}

def print_results(check_name, passed, details):
    """Красиво выводит результаты проверки"""
    if passed:
        symbol = f"{Colors.GREEN}✅{Colors.ENDC}"
    else:
        symbol = f"{Colors.RED}❌{Colors.ENDC}"

    print(f"\n{symbol} {Colors.BOLD}{check_name}{Colors.ENDC}")

    if isinstance(details, dict):
        for key, value in details.items():
            if isinstance(value, dict):
                print(f"  {Colors.BLUE}{key}:{Colors.ENDC}")
                for k, v in value.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  {Colors.BLUE}{key}:{Colors.ENDC} {value}")

def main():
    """Основная функция"""
    print_header()

    # Выполняем все проверки
    checks = [
        ("DATABASE", check_database),
        ("SYSTEMD SERVICES", check_services),
        ("PROCESSES", check_processes),
        ("WEB API", check_api),
        ("LOGS", check_logs),
        ("DISK SPACE", check_disk_space)
    ]

    all_passed = True
    results = {}

    for name, check_func in checks:
        passed, details = check_func()
        results[name] = {'passed': passed, 'details': details}
        print_results(name, passed, details)

        if not passed:
            all_passed = False

    # Итоговый результат
    print(f"\n{Colors.BOLD}{'='*60}{Colors.ENDC}")
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}✅ SYSTEM STATUS: HEALTHY{Colors.ENDC}")
        print(f"{Colors.GREEN}All checks passed successfully{Colors.ENDC}")
        exit_code = 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}❌ SYSTEM STATUS: UNHEALTHY{Colors.ENDC}")
        print(f"{Colors.YELLOW}Some checks failed. Please review the details above.{Colors.ENDC}")

        # Выводим рекомендации
        print(f"\n{Colors.BOLD}RECOMMENDATIONS:{Colors.ENDC}")

        if not results['DATABASE']['passed']:
            print(f"  • Check PostgreSQL connection and pump.calculate_confidence_score function")

        if not results['SYSTEMD SERVICES']['passed']:
            print(f"  • Run: sudo systemctl restart pump-*.service")

        if not results['PROCESSES']['passed']:
            print(f"  • Run: ./scripts/fix_phase1.sh to clean duplicate processes")

        if not results['WEB API']['passed']:
            print(f"  • Check if API service is running on port 5000")

        if not results['LOGS']['passed']:
            print(f"  • Review error logs for critical issues")

        exit_code = 1

    print(f"{Colors.BOLD}{'='*60}{Colors.ENDC}\n")

    # Сохраняем результат в JSON для автоматизации
    with open('/tmp/pump_health_check.json', 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'healthy': all_passed,
            'checks': results
        }, f, indent=2, default=str)

    sys.exit(exit_code)

if __name__ == "__main__":
    main()