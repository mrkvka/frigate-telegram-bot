"""Клиент Telegram Bot API."""

from __future__ import annotations

import logging
import time
from typing import Any

from bot.config import Settings
from bot.http_client import get_session
from bot.media.video import upload_timeout, _probe_bytes

log = logging.getLogger("frigate-bot")


class TelegramClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._api = settings.tg_api_url
        self._session = get_session()

    def call(self, method: str, **params: Any) -> dict | None:
        try:
            r = self._session.post(f"{self._api}/{method}", json=params, timeout=30)
            if not r.ok:
                log.error("TG %s -> %s %s", method, r.status_code, r.text[:200])
            if r.headers.get("content-type", "").startswith("application/json"):
                return r.json()
        except Exception as e:
            log.error("TG %s error: %s", method, e)
        return None

    def send_message(self, chat_id: int, text: str) -> dict | None:
        return self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    def send_to_all(self, text: str, owner_ids: frozenset[int]) -> None:
        for chat_id in owner_ids:
            self.send_message(chat_id, text)

    def send_photo(self, chat_id: int, photo_bytes: bytes, caption: str = "") -> dict | None:
        try:
            r = self._session.post(
                f"{self._api}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": ("snap.jpg", photo_bytes, "image/jpeg")},
                timeout=60,
            )
            return r.json() if r.ok else None
        except Exception as e:
            log.error("sendPhoto error chat=%s: %s", chat_id, e)
            return None

    def send_video(
        self,
        chat_id: int,
        video_bytes: bytes,
        caption: str = "",
        width: int | None = None,
        height: int | None = None,
    ) -> dict | None:
        if width is None or height is None:
            meta = _probe_bytes(video_bytes)
            width, height = meta.width, meta.height

        data = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            "supports_streaming": "true",
        }
        if width and height:
            data["width"] = width
            data["height"] = height

        timeout = upload_timeout(len(video_bytes))
        last_err: str | None = None

        for attempt in range(1, self._s.send_video_retries + 1):
            try:
                r = self._session.post(
                    f"{self._api}/sendVideo",
                    data=data,
                    files={"video": ("clip.mp4", video_bytes, "video/mp4")},
                    timeout=timeout,
                )
                result = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
                if r.ok and result and result.get("ok"):
                    log.info(
                        "sendVideo ok chat=%s size=%dKB attempt=%d",
                        chat_id,
                        len(video_bytes) // 1024,
                        attempt,
                    )
                    return result
                err = (result or {}).get("description") or r.text[:200]
                log.error(
                    "sendVideo API error chat=%s attempt=%d/%d: %s %s",
                    chat_id,
                    attempt,
                    self._s.send_video_retries,
                    r.status_code,
                    err,
                )
                last_err = err
            except Exception as e:
                log.error(
                    "sendVideo error chat=%s attempt=%d/%d: %s",
                    chat_id,
                    attempt,
                    self._s.send_video_retries,
                    e,
                )
                last_err = str(e)
            if attempt < self._s.send_video_retries:
                time.sleep(self._s.send_video_retry_delay * attempt)

        log.warning(
            "sendVideo failed chat=%s, trying sendDocument (%dKB)",
            chat_id,
            len(video_bytes) // 1024,
        )
        try:
            r = self._session.post(
                f"{self._api}/sendDocument",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"document": ("clip.mp4", video_bytes, "video/mp4")},
                timeout=timeout,
            )
            result = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
            if r.ok and result and result.get("ok"):
                log.info("sendDocument ok chat=%s size=%dKB", chat_id, len(video_bytes) // 1024)
                return result
            last_err = (result or {}).get("description") or r.text[:200]
            log.error("sendDocument API error chat=%s: %s", chat_id, last_err)
        except Exception as e:
            log.error("sendDocument error chat=%s: %s", chat_id, e)
            last_err = str(e)

        log.error("upload failed chat=%s: %s", chat_id, last_err)
        return None

    def set_commands(self) -> None:
        commands = [
            {"command": "start", "description": "Запуск бота"},
            {"command": "status", "description": "Статус камеры Frigate"},
            {"command": "snapshot", "description": "Текущий снимок с камеры"},
            {"command": "last", "description": "Последнее событие"},
            {"command": "help", "description": "Справка по командам"},
        ]
        self.call("setMyCommands", commands=commands)

    def delete_webhook(self) -> None:
        self.call("deleteWebhook", drop_pending_updates=False)

    def get_updates(self, offset: int, timeout: int) -> dict | None:
        import json

        try:
            r = self._session.get(
                f"{self._api}/getUpdates",
                params={
                    "offset": offset,
                    "timeout": timeout,
                    "allowed_updates": json.dumps(["message"]),
                },
                timeout=timeout + 10,
            )
            return r.json()
        except Exception as e:
            log.error("getUpdates error: %s", e)
            return None
