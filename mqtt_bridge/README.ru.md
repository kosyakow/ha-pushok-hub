# Pushok Hub MQTT Bridge

MQTT мост для Pushok Zigbee Hub в формате, совместимом с Zigbee2MQTT.

## Возможности

- Публикация состояний устройств в MQTT в формате Zigbee2MQTT
- Отдельные топики для каждого свойства для простых интеграций
- Поддержка нескольких форматов команд
- Поддержка автообнаружения Home Assistant MQTT
- Поддержка всех типов устройств (сенсоры, выключатели, числовые, выбор)
- Автоматическое переподключение при потере связи с хабом

## MQTT топики

Топики используют стабильный `device_id` (IEEE адрес) вместо понятного имени для надёжности.

### Топики состояния
- `pushok_hub/{device_id}` - Состояние устройства (JSON со всеми свойствами)
- `pushok_hub/{device_id}/{property}` - Значение отдельного свойства
- `pushok_hub/{device_id}/ack/{property}` - Подтверждение доставки (true/false)
- `pushok_hub/{device_id}/name` - Понятное имя устройства
- `pushok_hub/{device_id}/availability` - Доступность устройства (online/offline)

### Топики команд (поддерживаются все форматы)
- `pushok_hub/{device_id}/set` - JSON команда `{"state": true}`
- `pushok_hub/{device_id}` - JSON команда (тот же формат)
- `pushok_hub/{device_id}/{property}` - Прямое значение `true`
- `pushok_hub/{device_id}/{property}/set` - Прямое значение `true`

### Топики моста
- `pushok_hub/bridge/state` - Состояние моста (online/offline)
- `pushok_hub/bridge/devices` - Список устройств

### Пример

```bash
# Чтение состояния устройства
mosquitto_sub -t "pushok_hub/00158d0001234567/#" -v

# Вывод:
# pushok_hub/00158d0001234567 {"state":"on","power":45.2,"name":"Kitchen Socket","linkquality":120}
# pushok_hub/00158d0001234567/state on
# pushok_hub/00158d0001234567/ack/state true
# pushok_hub/00158d0001234567/power 45.2
# pushok_hub/00158d0001234567/ack/power true
# pushok_hub/00158d0001234567/name Kitchen Socket

# Отправка команд (все эквивалентны)
mosquitto_pub -t "pushok_hub/00158d0001234567/set" -m '{"state": false}'
mosquitto_pub -t "pushok_hub/00158d0001234567/state" -m "false"
mosquitto_pub -t "pushok_hub/00158d0001234567/state/set" -m "false"
```

## Установка

### Быстрый старт

```bash
# 1. Создайте виртуальное окружение и установите зависимости
cd mqtt_bridge
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Скопируйте шаблон конфигурации
cp config.example.yaml config.yaml

# 3. Зарегистрируйтесь на хабе (только в первый раз)
#    Сначала включите режим регистрации на хабе!
#    Адрес хаба и ключи будут автоматически сохранены в config.yaml
./run.sh --register --hub-host 192.168.1.151

# 4. (Опционально) Отредактируйте конфиг, если нужен другой MQTT брокер
nano config.yaml

# 5. Запустите
./run.sh
```

### Два режима работы

**Режим регистрации** - первоначальная настройка:
```bash
# Включите регистрацию на хабе, затем запустите:
./run.sh --register --hub-host 192.168.1.151

# Адрес хаба и ключи будут автоматически сохранены в config.yaml
```

**Обычный режим** - штатная работа:
```bash
# Использует сохранённые ключи из config.yaml
./run.sh

# С другим MQTT брокером
./run.sh --mqtt-host 192.168.1.100
```

### Ручной запуск

```bash
# Из директории mqtt_bridge
.venv/bin/python -m mqtt_bridge -c config.yaml

# Режим регистрации
.venv/bin/python -m mqtt_bridge --register -c config.yaml --hub-host 192.168.1.151

# С параметрами командной строки
.venv/bin/python -m mqtt_bridge -c config.yaml \
  --mqtt-host 192.168.1.100 \
  --mqtt-port 1883 \
  --log-level DEBUG
```

### Использование Docker

```bash
docker-compose up -d
```

## Конфигурация

### Файл конфигурации (config.yaml)

```yaml
hub:
  host: "192.168.1.151"    # автоматически сохраняется после --register
  port: 3001               # автоматически сохраняется после --register
  private_key: "..."       # автоматически сохраняется после --register
  user_id: "..."           # автоматически сохраняется после --register
  use_ssl: false

mqtt:
  host: "localhost"
  port: 1883
  base_topic: "pushok_hub"
  discovery_enabled: true

log_level: "INFO"
```

### Переменные окружения

- `PUSHOK_HUB_HOST` - IP адрес хаба
- `PUSHOK_HUB_PORT` - Порт хаба (по умолчанию: 3001)
- `PUSHOK_HUB_SSL` - Использовать SSL (по умолчанию: false)
- `PUSHOK_HUB_PRIVATE_KEY` - Приватный ключ аутентификации
- `PUSHOK_HUB_USER_ID` - ID пользователя
- `MQTT_HOST` - Хост MQTT брокера
- `MQTT_PORT` - Порт MQTT брокера (по умолчанию: 1883)
- `MQTT_USERNAME` - Имя пользователя MQTT
- `MQTT_PASSWORD` - Пароль MQTT
- `MQTT_BASE_TOPIC` - Базовый топик (по умолчанию: pushok_hub)
- `MQTT_DISCOVERY_ENABLED` - Включить автообнаружение HA (по умолчанию: true)
- `LOG_LEVEL` - Уровень логирования (по умолчанию: INFO)

## Пример использования с Home Assistant

1. Запустите мост
2. Добавьте интеграцию MQTT в Home Assistant
3. Устройства будут обнаружены автоматически

Или используйте в автоматизациях:

```yaml
automation:
  # Использование JSON топика
  - trigger:
      platform: mqtt
      topic: "pushok_hub/00158d0001234567"
    action:
      service: notify.mobile_app
      data:
        message: "Температура: {{ trigger.payload_json.temperature }}°C"

  # Использование топика свойства (проще)
  - trigger:
      platform: mqtt
      topic: "pushok_hub/00158d0001234567/temperature"
    action:
      service: notify.mobile_app
      data:
        message: "Температура: {{ trigger.payload }}°C"
```

## Обработка соединения

Мост автоматически обрабатывает потерю соединения:
- Публикует статус `offline` при потере связи с хабом
- Пытается переподключиться каждые 10 секунд
- Повторно публикует все состояния и discovery после переподключения

## Подтверждение доставки (ack)

Каждое свойство имеет соответствующий топик в `/ack/`, указывающий статус доставки:
- `pushok_hub/{device_id}/ack/{property}` - `true` или `false`

Значения:
- `true` - значение подтверждено Zigbee устройством
- `false` - значение установлено, но ещё не подтверждено

Это полезно для обнаружения ненадёжных устройств или проблем с сетью.
