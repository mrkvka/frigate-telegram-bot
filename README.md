# Frigate Telegram Bot

Лёгкий Docker-бот (Python + requests, образ ~45MB) для Frigate NVR. Отдаёт снимки и клипы в Telegram по командам.

## Возможности

- `/start` / `/help` — приветствие и список команд
- `/status` — версия Frigate, uptime, fps камеры, inference детектора, число событий сегодня
- `/snapshot` — текущий кадр с камеры (JPEG 720p)
- `/last` — последнее событие с клипом (MP4)
- Меню команд настраивается автоматически при старте (`setMyCommands`)
- Доступ только для `OWNER_CHAT_ID` (остальные игнорируются)

## Быстрый старт

```bash
docker run -d --name frigate-bot --restart unless-stopped \
  -e BOT_TOKEN=123:AAA... \
  -e OWNER_CHAT_ID=123456789 \
  -e FRIGATE_URL=http://frigate:5000 \
  -e CAMERA=front \
  ghcr.io/mrkvka/frigate-telegram-bot:latest
```

## Docker Compose (рекомендуется — рядом с Frigate)

```yaml
services:
  frigate:
    image: ghcr.io/blakeblackshear/frigate:stable
    # ... твой конфиг Frigate ...

  frigate-bot:
    image: ghcr.io/mrkvka/frigate-telegram-bot:latest
    container_name: frigate-bot
    restart: unless-stopped
    environment:
      BOT_TOKEN: ${BOT_TOKEN}
      OWNER_CHAT_ID: ${OWNER_CHAT_ID}
      FRIGATE_URL: http://frigate:5000
      CAMERA: front
    depends_on:
      - frigate
```

Скопируй `.env.example` в `.env`, подставь токен и chat_id:
```bash
cp .env.example .env
docker compose up -d frigate-bot
```

## Переменные окружения

| Переменная | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `BOT_TOKEN` | да | — | Токен от @BotFather |
| `OWNER_CHAT_ID` | да | — | Chat ID владельца (любой другой будет отбит «Доступ запрещён») |
| `FRIGATE_URL` | нет | `http://frigate:5000` | URL Frigate API |
| `CAMERA` | нет | `front` | Имя камеры в конфиге Frigate |
| `POLL_TIMEOUT` | нет | `30` | Секунды long-polling Telegram |
| `MAX_VIDEO_MB` | нет | `45` | Максимальный размер клипа для отправки (лимит TG — 50MB) |

## Как получить chat_id

Напиши боту `/start`, потом:
```
https://api.telegram.org/bot<TOKEN>/getUpdates
```
В ответе `result[].message.chat.id` — твой chat_id.

## GitHub Actions

При push в `main` или теге `v*` автоматически собирается multi-arch (amd64/arm64) образ в GHCR:
- `ghcr.io/mrkvka/frigate-telegram-bot:latest`
- `ghcr.io/mrkvka/frigate-telegram-bot:v1.0.0`

## Лицензия

MIT
