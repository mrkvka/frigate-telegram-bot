"""Точка входа: long-polling + фоновые потоки."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from bot import __version__
from bot.commands.handlers import CommandHandlers
from bot.config import Settings
from bot.events.service import EventService
from bot.events.watcher import EventWatcher
from bot.frigate_client import FrigateClient
from bot.logging_setup import setup_logging
from bot.monitor.health import HealthMonitor
from bot.telegram_client import TelegramClient

log = logging.getLogger("frigate-bot")


class BotApp:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._tg = TelegramClient(settings)
        self._frigate = FrigateClient(settings)
        self._events = EventService(settings, self._tg, self._frigate)
        self._commands = CommandHandlers(settings, self._tg, self._frigate, self._events)

    def run(self) -> None:
        log.info(
            "Frigate bot v%s starting... Frigate=%s Owners=%s Camera=%s TG=%s auto_events=%s",
            __version__,
            self._s.frigate_url,
            sorted(self._s.owner_chat_ids),
            self._s.camera,
            self._s.tg_api_base,
            self._s.auto_events,
        )
        self._tg.delete_webhook()
        self._tg.set_commands()

        if self._s.auto_events:
            EventWatcher(self._s, self._frigate, self._events).start_daemon()
        if self._s.monitor_enabled:
            HealthMonitor(self._s, self._tg).start_daemon()

        self._touch_heartbeat()
        offset = 0
        while True:
            try:
                data = self._tg.get_updates(offset, self._s.poll_timeout)
                if not data or not data.get("ok"):
                    log.error("getUpdates failed: %s", data)
                    time.sleep(5)
                    continue
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    self._handle_update(upd)
                self._touch_heartbeat()
            except requests.exceptions.ReadTimeout:
                self._touch_heartbeat()
            except Exception as e:
                log.error("Main loop error: %s", e)
                time.sleep(5)

    def _handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat_id = msg.get("chat", {}).get("id")
        if chat_id not in self._s.owner_chat_ids:
            log.warning("Unauthorized chat_id=%s user=%s", chat_id, msg.get("from"))
            self._tg.send_message(chat_id, "⛔ Доступ запрещён")
            return
        text = (msg.get("text") or "").strip()
        if text:
            self._commands.dispatch(chat_id, text)

    def _touch_heartbeat(self) -> None:
        try:
            Path(self._s.heartbeat_file).touch()
        except OSError:
            pass


def main() -> None:
    setup_logging()
    BotApp(Settings.from_env()).run()


if __name__ == "__main__":
    main()
