# Frigate Telegram Bot

Telegram-бот для [Frigate NVR](https://frigate.video): присылает клипы с камеры при обнаружении движения и отвечает на команды. Работает в Docker рядом с Frigate.

Образ: `ghcr.io/mrkvka/frigate-telegram-bot:latest`

## Что делает

**Автоуведомления.** Бот опрашивает Frigate API, ждёт готовности клипа и отправляет MP4 всем владельцам (`OWNER_CHAT_ID`). Клип кодируется один раз на событие, рассылка идёт параллельно.

**Объединение событий.** Frigate иногда создаёт несколько event id на одно движение (кратковременная потеря трека). Бот группирует перекрывающиеся события с одной меткой и камерой и шлёт один клип — самый длинный из группы.

**Нормализация видео.** Frigate отдаёт клип как есть; бот при необходимости прогоняет через ffmpeg: H.264 + AAC, loudnorm, опционально RNNoise (`arnndn`). В Telegram передаются `width`, `height`, `supports_streaming` — видео не становится квадратным и воспроизводится inline.

**Надёжная доставка.** До 5 попыток `sendVideo`, fallback на `sendDocument`, динамический таймаут загрузки по размеру файла.

**Мониторинг Frigate.** Фоновый поток проверяет API, fps камеры и свежесть записей. При зависании — уведомление в Telegram и опциональный рестарт контейнера Frigate через docker.sock.

**Команды** (только для владельцев):

| Команда | Действие |
|---|---|
| `/start`, `/help` | Справка |
| `/status` | Версия Frigate, uptime, fps, inference, события за сегодня |
| `/snapshot` | Текущий кадр с камеры |
| `/last` | Последнее событие с клипом |

## Структура проекта

```
bot/
├── app.py              # long-polling Telegram + запуск фоновых потоков
├── config.py           # настройки из env
├── telegram_client.py  # API Telegram, retry, fallback
├── frigate_client.py   # API Frigate
├── events/
│   ├── watcher.py      # опрос новых событий
│   ├── merge.py        # объединение дубликатов
│   └── service.py      # подготовка клипа + broadcast
├── media/video.py      # ffmpeg/ffprobe
├── commands/handlers.py
└── monitor/health.py   # health-check + autorestart
```

`bot.py` — legacy-обёртка для совместимости; точка входа: `python -m bot`.

## Требования

- Frigate 0.17+ с записью событий (detections/alerts)
- Docker и docker compose на хосте с Frigate
- Токен бота от [@BotFather](https://t.me/BotFather)
- Chat ID владельца(ев)

## Установка

### 1. Frigate: длина клипа

В `config.yml` Frigate задай отступы до/после движения (секунды):

```yaml
record:
  alerts:
    pre_capture: 1
    post_capture: 1
  detections:
    pre_capture: 1
    post_capture: 1
```

Пример полного конфига — `config.example.yml` (go2rtc, sub-stream для detect, main для record).

### 2. Бот

```bash
git clone https://github.com/mrkvka/frigate-telegram-bot.git
cd frigate-telegram-bot
cp .env.example .env
# заполни BOT_TOKEN и OWNER_CHAT_ID
```

Создай сеть (если ещё нет):

```bash
docker network create --subnet=172.30.55.0/24 frigate_tg_bot_net
```

Проверь пути в `docker-compose.yml` — volumes должны указывать на каталог Frigate на хосте:

```yaml
volumes:
  - /opt/frigate/media/recordings:/media/frigate/recordings:ro
  - /opt/frigate/config:/frigate_config:ro
  - /var/run/docker.sock:/var/run/docker.sock:ro   # для autorestart
```

```bash
docker compose build
docker compose up -d
```

### 3. Chat ID

Напиши боту `/start`, затем:

```
https://api.telegram.org/bot<TOKEN>/getUpdates
```

В ответе: `result[].message.chat.id`.

Несколько получателей: `OWNER_CHAT_ID=111,222,333`

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | — | Токен бота (обязательно) |
| `OWNER_CHAT_ID` | — | Chat ID, через запятую (обязательно) |
| `FRIGATE_URL` | `http://frigate:5000` | URL API Frigate |
| `CAMERA` | `front` | Имя камеры в конфиге Frigate |
| `AUTO_EVENTS` | `1` | Автоотправка новых событий |
| `EVENT_POLL_SECS` | `10` | Интервал опроса Frigate |
| `CLIP_WAIT_SECS` | `10` | Пауза после end_time перед скачиванием клипа |
| `EVENT_MERGE_GAP_SECS` | `30` | Объединять события, если gap между ними меньше (с) |
| `FIX_TELEGRAM_VIDEO` | `1` | Перекодировать клип для Telegram |
| `VIDEO_FIX_WIDTH` | `0` | Ширина (0 = без ресайза) |
| `VIDEO_FIX_CRF` | `23` | Качество H.264 |
| `MAX_VIDEO_MB` | `45` | Лимит размера (Telegram — 50 MB) |
| `SEND_VIDEO_RETRIES` | `5` | Попытки отправки видео |
| `MONITOR_ENABLED` | `1` | Health-мониторинг Frigate |
| `FRIGATE_AUTORESTART` | `1` | Рестарт контейнера Frigate при сбое |
| `FRIGATE_CONTAINER` | `frigate` | Имя контейнера Frigate |
| `TG_API_BASE` | `https://api.telegram.org` | Альтернативный endpoint Telegram |

Полный список — в `.env.example`.

## Как это работает (кратко)

```
Frigate detect → event end_time → watcher ждёт CLIP_WAIT_SECS
    → merge дубликатов → скачать clip MP4 → ffmpeg normalize (1 раз)
    → sendVideo всем OWNER_CHAT_ID параллельно
```

Клип Frigate = движение + `pre_capture` + `post_capture` из конфига записи.

## Сборка образа

Push в `main` или тег `v*` собирает multi-arch образ в GHCR через GitHub Actions.

Локально:

```bash
docker build -t frigate-telegram-bot:1.0.0 .
```

## Логи и диагностика

```bash
docker logs -f frigate-telegram-bot
```

Полезные строки:

- `event_watcher started` — автоотправка включена
- `merged N events` — сработало объединение дубликатов
- `broadcast event id=... sent=2/2` — успешная рассылка

Если видео не доходит — нестабильный канал до `api.telegram.org`. Попробуй `TG_API_BASE` через прокси (см. `README-proxy.md`) или увеличь `SEND_VIDEO_RETRIES`.

## Лицензия

MIT
