#!/bin/bash

# Скрипт для установки systemd сервиса pump-web-api
# Запускать с правами sudo

set -e

echo "=== Установка systemd сервиса pump-web-api ==="

# Копируем файл сервиса в системную директорию
echo "1. Копирование файла сервиса..."
sudo cp /home/elcrypto/pump_detector/services/pump-web-api.service /etc/systemd/system/

# Перезагружаем конфигурацию systemd
echo "2. Перезагрузка конфигурации systemd..."
sudo systemctl daemon-reload

# Включаем автозапуск сервиса
echo "3. Включение автозапуска..."
sudo systemctl enable pump-web-api

# Запускаем сервис
echo "4. Запуск сервиса..."
sudo systemctl start pump-web-api

# Проверяем статус
echo "5. Проверка статуса..."
sudo systemctl status pump-web-api --no-pager

echo ""
echo "✅ Сервис pump-web-api успешно установлен!"
echo ""
echo "Полезные команды:"
echo "  sudo systemctl status pump-web-api   # Проверить статус"
echo "  sudo systemctl restart pump-web-api  # Перезапустить"
echo "  sudo systemctl stop pump-web-api     # Остановить"
echo "  sudo journalctl -u pump-web-api -f   # Смотреть логи в реальном времени"
echo ""
echo "Web интерфейс доступен по адресу: http://localhost:2537"