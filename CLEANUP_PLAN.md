# ПЛАН ОЧИСТКИ ПРОЕКТА PUMP DETECTOR

**Дата:** 2025-11-13
**Основание:** AUDIT_REPORT.md
**Цель:** Удаление устаревших, неиспользуемых и тестовых файлов

---

## ПРИОРИТЕТЫ

🔴 **КРИТИЧНО** - Требует немедленного действия (ошибки, сломанные ссылки)
🟡 **ВАЖНО** - Устаревшие компоненты, занимают место
🟢 **РЕКОМЕНДУЕТСЯ** - Улучшение структуры проекта

---

## ФАЗА 1: КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ 🔴

### 1.1 Удалить сломанные systemd сервисы

#### Действие 1.1.1: Остановить и удалить pump-spot-futures.service
```bash
# Остановить сервис (если запущен)
sudo systemctl stop pump-spot-futures.service

# Отключить автозапуск
sudo systemctl disable pump-spot-futures.service

# Удалить файл сервиса
sudo rm /etc/systemd/system/pump-spot-futures.service

# Удалить из репозитория
rm /home/elcrypto/pump_detector/systemd/pump-spot-futures.service

# Перезагрузить systemd
sudo systemctl daemon-reload
```

**Причина:** Сервис ссылается на несуществующий файл `spot_futures_analyzer.py`

#### Действие 1.1.2: Удалить pump-validator.service
```bash
# Остановить сервис (если запущен)
sudo systemctl stop pump-validator.service

# Отключить автозапуск
sudo systemctl disable pump-validator.service

# Удалить файл сервиса
sudo rm /etc/systemd/system/pump-validator.service

# Удалить из репозитория
rm /home/elcrypto/pump_detector/systemd/pump-validator.service

# Перезагрузить systemd
sudo systemctl daemon-reload
```

**Причина:** Сервис ссылается на устаревший validator_daemon.py (V1), статус FAILED

#### Действие 1.1.3: Удалить pump-detector.service
```bash
# Остановить сервис (если запущен)
sudo systemctl stop pump-detector.service

# Отключить автозапуск
sudo systemctl disable pump-detector.service

# Удалить файл сервиса
sudo rm /etc/systemd/system/pump-detector.service

# Удалить из репозитория
rm /home/elcrypto/pump_detector/systemd/pump-detector.service

# Перезагрузить systemd
sudo systemctl daemon-reload
```

**Причина:** Сервис запускает устаревший detector_daemon.py (V1), используется cron вместо него

#### Действие 1.1.4: Удалить дубликат pump-web-api.service
```bash
# Остановить сервис (если запущен)
sudo systemctl stop pump-web-api.service

# Отключить автозапуск
sudo systemctl disable pump-web-api.service

# Удалить файл сервиса (если существует)
sudo rm -f /etc/systemd/system/pump-web-api.service

# Перезагрузить systemd
sudo systemctl daemon-reload
```

**Причина:** Дубликат pump-detector-web-api.service

### 1.2 Закоммитить удаленные файлы

```bash
cd /home/elcrypto/pump_detector

# Проверить статус
git status

# Закоммитить удаления
git add -A
git commit -m "Remove obsolete test files and scripts

- Remove crontab (replaced by active crontab)
- Remove debug_test.html, test_frontend.html (test files)
- Remove install.sh (obsolete installer)
- Remove test_engine_v2.py, test_telegram.py (one-time tests)
- Remove update_pump_phases.py (obsolete script)
"
```

**Результат:** Очистка git истории от помеченных на удаление файлов

---

## ФАЗА 2: АРХИВИРОВАНИЕ УСТАРЕВШИХ КОМПОНЕНТОВ 🟡

### 2.1 Создать директорию archive/

```bash
cd /home/elcrypto/pump_detector
mkdir -p archive/v1
mkdir -p archive/v1/daemons
mkdir -p archive/v1/api
mkdir -p archive/v1/systemd
```

### 2.2 Переместить устаревшие демоны V1

```bash
cd /home/elcrypto/pump_detector

# Переместить V1 демоны
mv daemons/detector_daemon.py archive/v1/daemons/
mv daemons/validator_daemon.py archive/v1/daemons/
mv daemons/signal_correlator_daemon.py archive/v1/daemons/

# Закоммитить изменения
git add -A
git commit -m "Archive V1 daemons - replaced by V2.0 architecture

Moved to archive/v1/daemons/:
- detector_daemon.py (replaced by detector_daemon_v2.py)
- validator_daemon.py (not used in V2.0)
- signal_correlator_daemon.py (functionality integrated into PumpDetectionEngine)
"
```

**Результат:** Устаревшие демоны сохранены для истории, но не используются

### 2.3 Переместить backup API

```bash
cd /home/elcrypto/pump_detector

# Переместить V1 API backup
mv api/web_api_v1_backup.py archive/v1/api/

# Закоммитить
git add -A
git commit -m "Archive V1 API backup - using web_api.py (V2.0)"
```

**Результат:** Старый backup API перенесен в архив

---

## ФАЗА 3: ОБНОВЛЕНИЕ КОНФИГУРАЦИЙ 🟡

### 3.1 Обновить check_daemons.sh

**Проблема:** Скрипт проверяет устаревшие демоны (detector, validator)

**Решение A: Удалить скрипт (если не используется)**
```bash
cd /home/elcrypto/pump_detector
rm scripts/check_daemons.sh

git add -A
git commit -m "Remove check_daemons.sh - V2.0 uses cron, not daemon processes"
```

**Решение B: Обновить скрипт (если нужен health check)**
```bash
# Отредактировать scripts/check_daemons.sh
# Заменить проверки на:
# - Проверка cron задач (detector_daemon_v2.py, analysis_runner_v2.py)
# - Проверка Web API (pump-detector-web-api.service)
# - Проверка последних логов
```

**Рекомендация:** Решение A (удалить), т.к. в V2.0 нет постоянных daemon процессов

### 3.2 Создать корректный systemd сервис для Web API

**Проблема:** Сервис `pump-detector-web-api.service` работает, но файла нет в репозитории

**Решение:** Создать файл в репозитории
```bash
cat > /home/elcrypto/pump_detector/systemd/pump-detector-web-api.service << 'EOF'
[Unit]
Description=Pump Detector Web API V2.0
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=elcrypto
Group=elcrypto
WorkingDirectory=/home/elcrypto/pump_detector
Environment="PYTHONPATH=/home/elcrypto/pump_detector"
Environment="FLASK_APP=api/web_api.py"
ExecStart=/home/elcrypto/pump_detector/venv/bin/python3 /home/elcrypto/pump_detector/api/web_api.py
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
Restart=on-failure
RestartSec=30s
StandardOutput=append:/home/elcrypto/pump_detector/logs/web_api.log
StandardError=append:/home/elcrypto/pump_detector/logs/web_api_error.log

[Install]
WantedBy=multi-user.target
EOF

# Закоммитить
git add systemd/pump-detector-web-api.service
git commit -m "Add pump-detector-web-api.service configuration file"
```

---

## ФАЗА 4: АНАЛИЗ И ОЧИСТКА СКРИПТОВ 🟢

### 4.1 Категоризация скриптов (scripts/)

#### АКТИВНЫЕ (оставить):
- `manage_daemons.sh` - Полезен для отладки
- `install_web_api_service.sh` - Установка сервиса

#### SQL СКРИПТЫ (оставить):
- `load_historical_signals.sql`
- `oi_integration.sql`

#### АНАЛИЗ/ИССЛЕДОВАНИЯ (проверить использование):
```bash
# Эти скрипты могут быть:
# - Одноразовые тесты → УДАЛИТЬ
# - Исследовательские → АРХИВИРОВАТЬ
# - Полезные утилиты → ОСТАВИТЬ

scripts/analyze_filusdt_pump.py
scripts/analyze_pump_precursors.py
scripts/analyze_pump_precursors_auto.py
scripts/analyze_signal_correlation.py
scripts/deep_analysis.py
scripts/deep_analysis_simple.py
scripts/find_all_pumps.py
scripts/load_known_pumps.py
```

**Действие:** Провести ручной анализ каждого скрипта:
1. Проверить последнее использование (`git log <file>`)
2. Проверить импорты в других файлах (`grep -r "import <script>"`)
3. Решить: ОСТАВИТЬ / АРХИВИРОВАТЬ / УДАЛИТЬ

#### ПРЕДВАРИТЕЛЬНАЯ РЕКОМЕНДАЦИЯ:

**Архивировать (одноразовые анализы):**
```bash
mkdir -p archive/analysis_scripts
mv scripts/analyze_filusdt_pump.py archive/analysis_scripts/
mv scripts/analyze_pump_precursors*.py archive/analysis_scripts/
mv scripts/find_all_pumps.py archive/analysis_scripts/
mv scripts/deep_analysis*.py archive/analysis_scripts/
```

**Оставить (утилиты):**
- `generate_reports.py` (если используется)
- `health_check.py`
- `validate_signals.py`
- `backtest_engine.py`
- `calibrate_scoring.py`

---

## ФАЗА 5: ОЧИСТКА ЛОГОВ И ВРЕМЕННЫХ ФАЙЛОВ 🟢

### 5.1 Удалить старые логи

```bash
cd /home/elcrypto/pump_detector/logs

# Удалить логи старше 30 дней
find . -name "*.log" -mtime +30 -delete

# Удалить пустые логи
find . -name "*.log" -size 0 -delete
```

### 5.2 Очистить __pycache__

```bash
cd /home/elcrypto/pump_detector
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete
find . -name "*.pyo" -delete
```

### 5.3 Очистить старые PID файлы

```bash
cd /home/elcrypto/pump_detector/pids

# Проверить каждый PID файл
for pid_file in *.pid; do
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if ! ps -p $pid > /dev/null 2>&1; then
            echo "Removing stale PID file: $pid_file"
            rm "$pid_file"
        fi
    fi
done
```

---

## ФАЗА 6: ОБНОВЛЕНИЕ ДОКУМЕНТАЦИИ 🟢

### 6.1 Обновить README.md

```bash
# Добавить секции:
# - V2.0 Architecture
# - Active Components
# - Cron Schedule
# - Systemd Services
# - API Endpoints
```

### 6.2 Создать ARCHITECTURE_V2.md

```bash
# Документировать:
# - Схему работы V2.0
# - Поток данных (raw_signals → pump_candidates)
# - Cron задачи
# - Web API
# - База данных (таблицы)
```

### 6.3 Обновить SYSTEM_STATUS.md

```bash
# Обновить статусы:
# - Активные демоны → V2.0 cron tasks
# - Удаленные сервисы
# - Архивированные компоненты
```

---

## ФАЗА 7: ФИНАЛЬНАЯ ПРОВЕРКА ✅

### 7.1 Чеклист после очистки

```bash
# 1. Проверить systemd сервисы
systemctl list-units --type=service --all | grep pump

# Ожидается только:
# - pump-detector-web-api.service (ACTIVE)

# 2. Проверить cron
crontab -l | grep pump_detector

# Должны быть 4 задачи:
# - detector_daemon_v2.py --once
# - analysis_runner_v2.py --once
# - pump_start_monitor.py --once
# - price_updater.py

# 3. Проверить Web API
curl http://localhost:5001/api/v2/status

# 4. Проверить структуру проекта
ls -la /home/elcrypto/pump_detector/

# 5. Проверить git status
git status

# 6. Запустить тесты (если есть)
# pytest tests/

# 7. Проверить логи
tail -f logs/detector_v2.log
tail -f logs/analysis_runner_v2.log
tail -f logs/web_api.log
```

### 7.2 Создать backup перед очисткой

```bash
# ВАЖНО! Создать backup перед началом очистки
cd /home/elcrypto
tar -czf pump_detector_backup_$(date +%Y%m%d).tar.gz pump_detector/
```

---

## ИТОГОВАЯ ТАБЛИЦА ДЕЙСТВИЙ

| # | Действие | Приоритет | Время | Риск |
|---|----------|-----------|-------|------|
| 1 | Создать backup | 🔴 | 5 мин | Низкий |
| 2 | Удалить systemd сервисы | 🔴 | 10 мин | Низкий |
| 3 | Закоммитить удаленные файлы | 🔴 | 2 мин | Низкий |
| 4 | Архивировать V1 демоны | 🟡 | 5 мин | Низкий |
| 5 | Архивировать V1 API backup | 🟡 | 2 мин | Низкий |
| 6 | Удалить/обновить check_daemons.sh | 🟡 | 3 мин | Низкий |
| 7 | Создать systemd файл для Web API | 🟡 | 5 мин | Низкий |
| 8 | Анализ и архивирование скриптов | 🟢 | 30 мин | Средний |
| 9 | Очистка логов и временных файлов | 🟢 | 5 мин | Низкий |
| 10 | Обновление документации | 🟢 | 20 мин | Низкий |
| 11 | Финальная проверка | ✅ | 10 мин | Низкий |

**Общее время:** ~1.5 часа
**Общий риск:** Низкий (при наличии backup)

---

## КОМАНДЫ ДЛЯ БЫСТРОГО ВЫПОЛНЕНИЯ

### Выполнить все критические действия (Фаза 1):

```bash
#!/bin/bash
# cleanup_critical.sh

set -e  # Exit on error

echo "=== PUMP DETECTOR CLEANUP - CRITICAL PHASE ==="
echo ""

# Backup
echo "[1/5] Creating backup..."
cd /home/elcrypto
tar -czf pump_detector_backup_$(date +%Y%m%d_%H%M%S).tar.gz pump_detector/
echo "✓ Backup created"
echo ""

# Stop and remove systemd services
echo "[2/5] Removing obsolete systemd services..."
for service in pump-spot-futures pump-validator pump-detector pump-web-api; do
    sudo systemctl stop $service.service 2>/dev/null || true
    sudo systemctl disable $service.service 2>/dev/null || true
    sudo rm -f /etc/systemd/system/$service.service
    echo "✓ Removed $service.service"
done
sudo systemctl daemon-reload
echo "✓ Systemd reloaded"
echo ""

# Remove service files from repo
echo "[3/5] Removing service files from repository..."
cd /home/elcrypto/pump_detector
rm -f systemd/pump-spot-futures.service
rm -f systemd/pump-validator.service
rm -f systemd/pump-detector.service
echo "✓ Service files removed"
echo ""

# Commit deleted files
echo "[4/5] Committing deleted files..."
git add -A
git commit -m "Cleanup: Remove obsolete files and systemd services

Phase 1 - Critical:
- Remove obsolete systemd services (pump-spot-futures, pump-validator, pump-detector)
- Commit deletion of test files (debug_test.html, test_*.py, etc.)
- Remove old install.sh and crontab file
"
echo "✓ Changes committed"
echo ""

# Verify
echo "[5/5] Verifying cleanup..."
echo "Active systemd services:"
systemctl list-units --type=service --all | grep pump || echo "  (none found)"
echo ""
echo "Git status:"
git status --short
echo ""

echo "=== CRITICAL PHASE COMPLETE ==="
echo "Next: Run 'bash cleanup_archive.sh' for Phase 2"
```

### Выполнить архивирование (Фаза 2):

```bash
#!/bin/bash
# cleanup_archive.sh

set -e

echo "=== PUMP DETECTOR CLEANUP - ARCHIVE PHASE ==="
echo ""

cd /home/elcrypto/pump_detector

# Create archive directory
echo "[1/3] Creating archive structure..."
mkdir -p archive/v1/{daemons,api,systemd}
echo "✓ Archive directories created"
echo ""

# Move V1 daemons
echo "[2/3] Moving V1 daemons to archive..."
mv daemons/detector_daemon.py archive/v1/daemons/
mv daemons/validator_daemon.py archive/v1/daemons/
mv daemons/signal_correlator_daemon.py archive/v1/daemons/
echo "✓ V1 daemons archived"
echo ""

# Move V1 API backup
echo "[3/3] Moving V1 API backup to archive..."
mv api/web_api_v1_backup.py archive/v1/api/
echo "✓ V1 API backup archived"
echo ""

# Commit
git add -A
git commit -m "Archive V1 components - replaced by V2.0

Moved to archive/v1/:
- daemons: detector_daemon.py, validator_daemon.py, signal_correlator_daemon.py
- api: web_api_v1_backup.py

V2.0 uses cron-based architecture with:
- detector_daemon_v2.py
- analysis_runner_v2.py
- pump_start_monitor.py
- price_updater.py
"

echo "=== ARCHIVE PHASE COMPLETE ==="
```

---

## ЗАКЛЮЧЕНИЕ

После выполнения плана очистки проект будет:
- ✅ Свободен от устаревших компонентов V1
- ✅ Не будет сломанных systemd сервисов
- ✅ Архитектура V2.0 четко документирована
- ✅ Git история очищена от удаленных файлов
- ✅ Структура проекта прозрачна и понятна

**Следующий шаг:** Выполнить `bash cleanup_critical.sh`

---

**Автор плана:** Claude Code
**Дата:** 2025-11-13
**Основание:** AUDIT_REPORT.md
