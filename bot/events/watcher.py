"""Фоновый опрос Frigate на новые события."""

from __future__ import annotations

import logging
import threading
import time

from bot.config import Settings
from bot.events.merge import merge_incident_events
from bot.events.service import EventService
from bot.frigate_client import FrigateClient

log = logging.getLogger("frigate-bot")


class EventWatcher:
    def __init__(
        self,
        settings: Settings,
        frigate: FrigateClient,
        events: EventService,
    ) -> None:
        self._s = settings
        self._frigate = frigate
        self._events = events
        self._last_sent_end_ts = time.time()

    def run(self) -> None:
        log.info(
            "event_watcher started baseline=%.0f poll=%ds merge_gap=%ds",
            self._last_sent_end_ts,
            self._s.event_poll_secs,
            self._s.event_merge_gap_secs,
        )
        while True:
            try:
                batch = self._frigate.events_with_clips(after_ts=int(self._last_sent_end_ts))
                batch = [e for e in batch if (e.get("end_time") or 0) > self._last_sent_end_ts]
                batch = merge_incident_events(batch, self._s.event_merge_gap_secs)

                for ev in batch:
                    end_time = ev.get("end_time") or 0
                    time.sleep(self._s.clip_wait_secs)
                    log.info(
                        "auto-sending event id=%s label=%s end=%.0f dur=%.0fs to %d user(s)",
                        ev.get("id"),
                        ev.get("label"),
                        end_time,
                        (ev.get("end_time") or 0) - (ev.get("start_time") or 0),
                        len(self._s.owner_chat_ids),
                    )
                    try:
                        self._events.broadcast(ev, title="🚨 Новое событие")
                    except Exception:
                        log.exception("broadcast failed id=%s", ev.get("id"))
                    self._last_sent_end_ts = end_time
            except Exception:
                log.exception("event_watcher iteration error")
            time.sleep(self._s.event_poll_secs)

    def start_daemon(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, name="event-watcher", daemon=True)
        thread.start()
        return thread
