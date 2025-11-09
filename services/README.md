# Pump Detector Systemd Services

## Список сервисов

1. **pump-detector.service** - Основной демон детекции сигналов
2. **pump-validator.service** - Демон валидации сигналов
3. **pump-spot-futures.service** - Анализатор корреляции spot/futures
4. **pump-web-api.service** - Web API и интерфейс (НОВЫЙ)

## Установка сервиса pump-web-api

### Автоматическая установка:
```bash
cd /home/elcrypto/pump_detector/scripts
sudo ./install_web_api_service.sh
```

### Ручная установка:
```bash
# 1. Скопировать файл сервиса
sudo cp /home/elcrypto/pump_detector/services/pump-web-api.service /etc/systemd/system/

# 2. Перезагрузить конфигурацию systemd
sudo systemctl daemon-reload

# 3. Включить автозапуск
sudo systemctl enable pump-web-api

# 4. Запустить сервис
sudo systemctl start pump-web-api

# 5. Проверить статус
sudo systemctl status pump-web-api
```

## Управление сервисами

### Все сервисы одновременно:
```bash
# Запустить все
sudo systemctl start pump-detector pump-validator pump-spot-futures pump-web-api

# Остановить все
sudo systemctl stop pump-detector pump-validator pump-spot-futures pump-web-api

# Перезапустить все
sudo systemctl restart pump-detector pump-validator pump-spot-futures pump-web-api

# Статус всех
sudo systemctl status pump-detector pump-validator pump-spot-futures pump-web-api
```

### Отдельные сервисы:
```bash
sudo systemctl [start|stop|restart|status] pump-web-api
```

## Логи

### Просмотр логов через journalctl:
```bash
# Все логи сервиса
sudo journalctl -u pump-web-api

# Логи в реальном времени
sudo journalctl -u pump-web-api -f

# Последние 100 строк
sudo journalctl -u pump-web-api -n 100
```

### Файлы логов:
- `/home/elcrypto/pump_detector/logs/web_api.log` - основной лог
- `/home/elcrypto/pump_detector/logs/web_api_error.log` - ошибки
- `/home/elcrypto/pump_detector/logs/detector.log` - логи детектора
- `/home/elcrypto/pump_detector/logs/validator.log` - логи валидатора
- `/home/elcrypto/pump_detector/logs/spot_futures.log` - логи анализатора

## Доступ к Web интерфейсу

После запуска pump-web-api сервиса, интерфейс доступен по адресу:
- **http://localhost:2537** - локально
- **http://SERVER_IP:2537** - удаленно (замените SERVER_IP на IP вашего сервера)

## Решение проблем

### Если сервис не запускается:
1. Проверьте логи: `sudo journalctl -u pump-web-api -n 50`
2. Проверьте порт 2537: `sudo netstat -tlnp | grep 2537`
3. Убедитесь что виртуальное окружение существует: `ls -la /home/elcrypto/pump_detector/venv`
4. Проверьте права доступа к логам: `ls -la /home/elcrypto/pump_detector/logs`

### Если порт занят:
```bash
# Найти процесс на порту 2537
sudo lsof -i :2537
# или
sudo netstat -tlnp | grep 2537

# Убить процесс по PID
sudo kill -9 PID
```

### Сброс всех pump процессов:
```bash
# Остановить все сервисы
sudo systemctl stop pump-detector pump-validator pump-spot-futures pump-web-api

# Убить все оставшиеся процессы
pkill -f "pump_detector"

# Запустить сервисы заново
sudo systemctl start pump-detector pump-validator pump-spot-futures pump-web-api
```