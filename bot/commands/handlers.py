"""Обработчики команд Telegram."""

from __future__ import annotations

import logging
import time

from bot.config import Settings
from bot.events.service import EventService
from bot.frigate_client import FrigateClient
from bot.telegram_client import TelegramClient

log = logging.getLogger("frigate-bot")


class CommandHandlers:
    def __init__(
        self,
        settings: Settings,
        tg: TelegramClient,
        frigate: FrigateClient,
        events: EventService,
    ) -> None:
        self._s = settings
        self._tg = tg
        self._frigate = frigate
        self._events = events

    def start(self, chat_id: int) -> None:
        self._tg.send_message(
            chat_id,
            "<b>🎥 Frigate Bot</b>\n"
            "Я присылаю события с камеры и выполняю команды.\n\n"
            "<b>Доступные команды:</b>\n"
            "/status — статус камеры и детектора\n"
            "/snapshot — текущий снимок с камеры\n"
            "/last — последнее событие (видео)\n"
            "/help — эта справка",
        )

    def help(self, chat_id: int) -> None:
        self.start(chat_id)

    def status(self, chat_id: int) -> None:
        data = self._frigate.stats()
        if not data:
            self._tg.send_message(chat_id, "❌ Frigate недоступен")
            return
        try:
            uptime = int(data.get("service", {}).get("uptime", 0))
            ver = data.get("service", {}).get("version", "?")
            cam = data.get("cameras", {}).get(self._s.camera, {})
            det = data.get("detectors") or {}
            det_name = next(iter(det), None)
            det_info = det.get(det_name, {}) if det_name else {}
            hours = uptime // 3600
            minutes = (uptime % 3600) // 60
            text = (
                f"<b>📊 Статус Frigate</b>\n"
                f"Версия: <code>{ver}</code>\n"
                f"Uptime: {hours}ч {minutes}м\n\n"
                f"<b>📹 Камера {self._s.camera}:</b>\n"
                f"  camera_fps: {cam.get('camera_fps', '?')}\n"
                f"  detection_fps: {cam.get('detection_fps', '?')}\n"
                f"  process_fps: {cam.get('process_fps', '?')}\n"
                f"  skipped_fps: {cam.get('skipped_fps', '?')}\n\n"
                f"<b>🧠 Детектор {det_name or '?'}:</b>\n"
                f"  inference: {det_info.get('inference_speed', '?')} мс"
            )
            summary = self._frigate.events_summary()
            if summary:
                today = time.strftime("%Y-%m-%d")
                today_count = sum(s.get("count", 0) for s in summary if s.get("day") == today)
                text += f"\n\n<b>📈 Событий сегодня:</b> {today_count}"
            self._tg.send_message(chat_id, text)
        except Exception as e:
            log.exception("cmd_status error")
            self._tg.send_message(chat_id, f"❌ Ошибка парсинга: {e}")

    def snapshot(self, chat_id: int) -> None:
        self._tg.call("sendChatAction", chat_id=chat_id, action="upload_photo")
        img = self._frigate.latest_jpg()
        if not img:
            self._tg.send_message(chat_id, "❌ Не удалось получить снимок")
            return
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self._tg.send_photo(chat_id, img, caption=f"<b>📷 Снимок {self._s.camera}</b>\n{ts}")

    def last(self, chat_id: int) -> None:
        self._tg.call("sendChatAction", chat_id=chat_id, action="upload_video")
        ev = self._frigate.latest_event_with_clip()
        if not ev:
            self._tg.send_message(chat_id, "ℹ️ Нет событий с клипами")
            return
        try:
            self._events.send_one(chat_id, ev, title="🎬 Последнее событие")
        except Exception as e:
            log.exception("cmd_last error")
            self._tg.send_message(chat_id, f"❌ Ошибка: {e}")

    def dispatch(self, chat_id: int, text: str) -> None:
        cmd = text.split()[0].split("@")[0].lower()
        handlers = {
            "/start": self.start,
            "/help": self.help,
            "/status": self.status,
            "/snapshot": self.snapshot,
            "/last": self.last,
        }
        handler = handlers.get(cmd)
        if handler:
            log.info("cmd=%s chat=%s", cmd, chat_id)
            try:
                handler(chat_id)
            except Exception as e:
                log.exception("handler error for %s", cmd)
                self._tg.send_message(chat_id, f"❌ Ошибка: {e}")
        else:
            self._tg.send_message(chat_id, f"Неизвестная команда: {cmd}\nНажми /help")
