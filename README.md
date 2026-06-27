# Frigate Telegram Bot

Telegram-бот для [Frigate NVR](https://frigate.video): присылает **review-клипы** (один ролик на инцидент) и отвечает на команды. Работает в Docker рядом с Frigate.

Образ: `ghcr.io/mrkvka/frigate-telegram-bot:latest`

## Что делает

**Review вместо events.** Frigate группирует все перекрывающиеся треки на одной камере в один review. Бот опрашивает `/api/review`, ждёт `end_time`, скачивает клип через Recording API и шлёт в Telegram. Два event id на одно движение больше не дают два сообщения.

**Нормализация видео.** ffmpeg: H.264 + AAC, loudnorm, опционально RNNoise. Передаются `width`/`height`/`supports_streaming` для корректного inline-воспроизведения.

**Надёжная доставка.** Retry `sendVideo`, fallback `sendDocument`, параллельная рассылка всем владельцам с одной кодировкой клипа.

**Мониторинг Frigate.** Health-check API, fps, свежесть записей, опциональный autorestart контейнера.

**Команды** (только `OWNER_CHAT_ID`):

| Команда | Действие |
|---|---|
| `/start`, `/help` | Справка |
| `/status` | Frigate, fps, review за 24ч |
| `/snapshot` | Текущий кадр |
| `/last` | Последний review-клип |

## Frigate: обязательный конфиг

```yaml
review:
  alerts:
    labels:
      - person
      - car

record:
  alerts:
    pre_capture: 1    # секунд до движения
    post_capture: 1   # секунд после
  detections:
    pre_capture: 1
    post_capture: 1
```

`pre_capture`/`post_capture` управляют тем, какие сегменты записи сохраняются. Клип в Telegram строится по `start_time`/`end_time` review через:

```
GET /api/{camera}/start/{start}/end/{end}/clip.mp4
```

Полный пример — `config.example.yml`.

## Установка

```bash
git clone https://github.com/mrkvka/frigate-telegram-bot.git
cd frigate-telegram-bot
cp .env.example .env
# BOT_TOKEN, OWNER_CHAT_ID
docker network create --subnet=172.30.55.0/24 frigate_tg_bot_net  # если нет
docker compose build && docker compose up -d
```

Volumes в `docker-compose.yml` должны указывать на Frigate на хосте:

```yaml
volumes:
  - /opt/frigate/media/recordings:/media/frigate/recordings:ro
  - /opt/frigate/config:/frigate_config:ro
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | — | Токен от @BotFather |
| `OWNER_CHAT_ID` | — | Chat ID через запятую |
| `FRIGATE_URL` | `http://frigate:5000` | URL Frigate |
| `CAMERA` | `front` | Камера в конфиге |
| `AUTO_REVIEWS` | `1` | Автоотправка review |
| `REVIEW_SEVERITY` | `alert` | `alert` или `detection` |
| `REVIEW_POLL_SECS` | `10` | Интервал опроса |
| `CLIP_WAIT_SECS` | `10` | Пауза после end_time |
| `FIX_TELEGRAM_VIDEO` | `1` | Перекодировать для TG |
| `VIDEO_FIX_WIDTH` | `0` | 0 = без ресайза |
| `MAX_VIDEO_MB` | `45` | Лимит размера |

Полный список — `.env.example`. `AUTO_EVENTS` и `EVENT_POLL_SECS` поддерживаются как alias.

## Как работает

```
Frigate: треки → один review (start/end)
    → бот ждёт end_time + CLIP_WAIT_SECS
    → GET /api/{cam}/start/{start}/end/{end}/clip.mp4
    → ffmpeg normalize → sendVideo всем владельцам
```

## Chat ID

Напиши боту `/start`, затем `https://api.telegram.org/bot<TOKEN>/getUpdates` → `message.chat.id`.

## Лицензия

MIT
