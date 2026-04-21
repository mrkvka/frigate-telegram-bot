#!/usr/bin/env python3
"""
Frigate Telegram Bot
Обрабатывает команды /start /status /snapshot /last /help
Подключается к Frigate API и отвечает владельцу.
"""
import os
import sys
import time
import json
import logging
import requests

# ==== Конфиг (env) ====
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
OWNER_CHAT_ID_RAW = os.environ.get("OWNER_CHAT_ID", "").strip()
FRIGATE_URL = os.environ.get("FRIGATE_URL", "http://frigate:5000").strip().rstrip("/")
POLL_TIMEOUT = int(os.environ.get("POLL_TIMEOUT", "30"))
CAMERA = os.environ.get("CAMERA", "front").strip()
MAX_VIDEO_MB = int(os.environ.get("MAX_VIDEO_MB", "45"))

if not BOT_TOKEN:
    print("FATAL: BOT_TOKEN env var is required", file=sys.stderr)
    sys.exit(1)
if not OWNER_CHAT_ID_RAW:
    print("FATAL: OWNER_CHAT_ID env var is required", file=sys.stderr)
    sys.exit(1)
OWNER_CHAT_ID = int(OWNER_CHAT_ID_RAW)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("frigate-bot")


# ==== Telegram API helpers ====
def tg(method, **params):
    try:
        r = requests.post(f"{API}/{method}", json=params, timeout=30)
        if not r.ok:
            log.error("TG %s %s -> %s %s", method, params, r.status_code, r.text[:200])
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else None
    except Exception as e:
        log.error("TG %s error: %s", method, e)
        return None


def tg_send_photo(chat_id, photo_bytes, caption=""):
    try:
        r = requests.post(
            f"{API}/sendPhoto",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("snap.jpg", photo_bytes, "image/jpeg")},
            timeout=60,
        )
        return r.json()
    except Exception as e:
        log.error("sendPhoto error: %s", e)
        return None


def tg_send_video(chat_id, video_bytes, caption=""):
    try:
        r = requests.post(
            f"{API}/sendVideo",
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            files={"video": ("clip.mp4", video_bytes, "video/mp4")},
            timeout=120,
        )
        return r.json()
    except Exception as e:
        log.error("sendVideo error: %s", e)
        return None


def tg_text(chat_id, text):
    return tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)


# ==== Frigate helpers ====
def frigate_get(path, stream=False, timeout=15):
    try:
        r = requests.get(f"{FRIGATE_URL}{path}", timeout=timeout, stream=stream)
        r.raise_for_status()
        return r
    except Exception as e:
        log.error("Frigate %s error: %s", path, e)
        return None


# ==== Команды ====
def cmd_start(chat_id):
    tg_text(chat_id,
        "<b>🎥 Frigate Bot</b>\n"
        "Я присылаю события с камеры и выполняю команды.\n\n"
        "<b>Доступные команды:</b>\n"
        "/status — статус камеры и детектора\n"
        "/snapshot — текущий снимок с камеры\n"
        "/last — последнее событие (видео)\n"
        "/help — эта справка"
    )


def cmd_help(chat_id):
    cmd_start(chat_id)


def cmd_status(chat_id):
    r = frigate_get("/api/stats")
    if not r:
        tg_text(chat_id, "❌ Frigate недоступен")
        return
    try:
        data = r.json()
        uptime = int(data.get("service", {}).get("uptime", 0))
        ver = data.get("service", {}).get("version", "?")
        cam = data.get("cameras", {}).get(CAMERA, {})
        det = (data.get("detectors") or {})
        # Берём первый детектор
        det_name = next(iter(det), None)
        det_info = det.get(det_name, {}) if det_name else {}

        hours = uptime // 3600
        minutes = (uptime % 3600) // 60

        text = (
            f"<b>📊 Статус Frigate</b>\n"
            f"Версия: <code>{ver}</code>\n"
            f"Uptime: {hours}ч {minutes}м\n\n"
            f"<b>📹 Камера {CAMERA}:</b>\n"
            f"  camera_fps: {cam.get('camera_fps', '?')}\n"
            f"  detection_fps: {cam.get('detection_fps', '?')}\n"
            f"  process_fps: {cam.get('process_fps', '?')}\n"
            f"  skipped_fps: {cam.get('skipped_fps', '?')}\n\n"
            f"<b>🧠 Детектор {det_name or '?'}:</b>\n"
            f"  inference: {det_info.get('inference_speed', '?')} мс"
        )

        # события сегодня
        r2 = frigate_get("/api/events/summary")
        if r2:
            try:
                summary = r2.json()
                today = time.strftime("%Y-%m-%d")
                today_count = sum(s.get("count", 0) for s in summary if s.get("day") == today)
                text += f"\n\n<b>📈 Событий сегодня:</b> {today_count}"
            except Exception:
                pass

        tg_text(chat_id, text)
    except Exception as e:
        log.exception("cmd_status error")
        tg_text(chat_id, f"❌ Ошибка парсинга: {e}")


def cmd_snapshot(chat_id):
    tg("sendChatAction", chat_id=chat_id, action="upload_photo")
    r = frigate_get(f"/api/{CAMERA}/latest.jpg?h=720", timeout=15)
    if not r:
        tg_text(chat_id, "❌ Не удалось получить снимок")
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    tg_send_photo(chat_id, r.content, caption=f"<b>📷 Снимок {CAMERA}</b>\n{ts}")


def cmd_last(chat_id):
    tg("sendChatAction", chat_id=chat_id, action="upload_video")
    r = frigate_get("/api/events?limit=1&has_clip=1")
    if not r:
        tg_text(chat_id, "❌ Frigate недоступен")
        return
    try:
        events = r.json()
        if not events:
            tg_text(chat_id, "ℹ️ Нет событий с клипами")
            return
        ev = events[0]
        eid = ev.get("id")
        label = ev.get("label", "?")
        cam = ev.get("camera", "?")
        score = ev.get("top_score", ev.get("score", 0)) or 0
        start = ev.get("start_time", 0)
        end = ev.get("end_time") or (start + 10)
        duration = int(end - start) if end else 0
        dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start))

        caption = (
            f"<b>🎬 Последнее событие</b>\n"
            f"Метка: <b>{label}</b> ({score*100:.0f}%)\n"
            f"Камера: {cam}\n"
            f"Время: {dt}\n"
            f"Длительность: ~{duration}с"
        )

        r2 = frigate_get(f"/api/events/{eid}/clip.mp4", stream=True, timeout=60)
        if not r2:
            tg_text(chat_id, caption + "\n\n❌ Клип недоступен")
            return
        video_bytes = r2.content
        if len(video_bytes) > MAX_VIDEO_MB * 1024 * 1024:
            tg_text(chat_id, caption + f"\n\n⚠️ Клип слишком большой ({len(video_bytes)//1024//1024}MB)")
            return
        tg_send_video(chat_id, video_bytes, caption=caption)
    except Exception as e:
        log.exception("cmd_last error")
        tg_text(chat_id, f"❌ Ошибка: {e}")


# ==== Диспатчер ====
COMMANDS = {
    "/start": cmd_start,
    "/help": cmd_help,
    "/status": cmd_status,
    "/snapshot": cmd_snapshot,
    "/last": cmd_last,
}


def handle_update(update):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg.get("chat", {}).get("id")
    if chat_id != OWNER_CHAT_ID:
        log.warning("Unauthorized chat_id=%s user=%s", chat_id, msg.get("from"))
        tg_text(chat_id, "⛔ Доступ запрещён")
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return
    cmd = text.split()[0].split("@")[0].lower()
    handler = COMMANDS.get(cmd)
    if handler:
        log.info("cmd=%s chat=%s", cmd, chat_id)
        try:
            handler(chat_id)
        except Exception as e:
            log.exception("handler error for %s", cmd)
            tg_text(chat_id, f"❌ Ошибка: {e}")
    else:
        tg_text(chat_id, f"Неизвестная команда: {cmd}\nНажми /help")


def set_bot_commands():
    """Устанавливает меню команд при старте."""
    commands = [
        {"command": "start", "description": "Запуск бота"},
        {"command": "status", "description": "Статус камеры Frigate"},
        {"command": "snapshot", "description": "Текущий снимок с камеры"},
        {"command": "last", "description": "Последнее событие"},
        {"command": "help", "description": "Справка по командам"},
    ]
    tg("setMyCommands", commands=commands)


def main():
    log.info("Frigate bot starting... Frigate=%s Owner=%s Camera=%s", FRIGATE_URL, OWNER_CHAT_ID, CAMERA)
    tg("deleteWebhook", drop_pending_updates=False)
    set_bot_commands()

    offset = 0
    while True:
        try:
            r = requests.get(
                f"{API}/getUpdates",
                params={"offset": offset, "timeout": POLL_TIMEOUT, "allowed_updates": json.dumps(["message"])},
                timeout=POLL_TIMEOUT + 10,
            )
            data = r.json()
            if not data.get("ok"):
                log.error("getUpdates failed: %s", data)
                time.sleep(5)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                handle_update(upd)
        except requests.exceptions.ReadTimeout:
            continue
        except Exception as e:
            log.error("Main loop error: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
