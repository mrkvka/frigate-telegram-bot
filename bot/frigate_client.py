"""Клиент Frigate HTTP API."""

from __future__ import annotations

import logging
import time

import requests

from bot.config import Settings
from bot.http_client import get_session

log = logging.getLogger("frigate-bot")


class FrigateClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._base = settings.frigate_url
        self._session = get_session()

    def get(self, path: str, stream: bool = False, timeout: int = 15) -> requests.Response | None:
        try:
            r = self._session.get(f"{self._base}{path}", timeout=timeout, stream=stream)
            r.raise_for_status()
            return r
        except Exception as e:
            log.error("Frigate %s error: %s", path, e)
            return None

    def wait_for_recording_clip(
        self,
        camera: str,
        start_ts: float,
        end_ts: float,
        timeout: int | None = None,
    ) -> bytes | None:
        timeout = self._s.clip_ready_timeout if timeout is None else timeout
        deadline = time.time() + max(1, timeout)
        path = f"/api/{camera}/start/{start_ts}/end/{end_ts}/clip.mp4"
        last_status = None
        last_body = ""

        while True:
            try:
                r = self._session.get(f"{self._base}{path}", timeout=120)
                last_status = r.status_code
                if r.ok and len(r.content) > 1024:
                    return r.content
                last_body = r.text[:200] if not r.ok else f"small clip: {len(r.content)} bytes"
            except Exception as e:
                last_body = str(e)

            if time.time() >= deadline:
                log.warning(
                    "recording clip not ready camera=%s %.0f-%.0f after %ss: status=%s body=%s",
                    camera,
                    start_ts,
                    end_ts,
                    timeout,
                    last_status,
                    last_body,
                )
                return None
            time.sleep(max(1, self._s.clip_ready_poll))

    def stats(self) -> dict | None:
        r = self.get("/api/stats")
        return r.json() if r else None

    def reviews(self, after_ts: int, limit: int = 20) -> list[dict]:
        params = [f"limit={limit}", f"after={after_ts}"]
        if self._s.review_severity:
            params.append(f"severity={self._s.review_severity}")
        if self._s.camera:
            params.append(f"cameras={self._s.camera}")
        r = self.get(f"/api/review?{'&'.join(params)}")
        if not r:
            return []
        return r.json() or []

    def latest_review(self) -> dict | None:
        params = ["limit=1"]
        if self._s.review_severity:
            params.append(f"severity={self._s.review_severity}")
        if self._s.camera:
            params.append(f"cameras={self._s.camera}")
        r = self.get(f"/api/review?{'&'.join(params)}")
        if not r:
            return None
        reviews = r.json() or []
        return reviews[0] if reviews else None

    def review_preview(self, review_id: str) -> bytes | None:
        r = self.get(f"/api/review/{review_id}/preview", timeout=30)
        return r.content if r else None

    def event_snapshot(self, event_id: str) -> bytes | None:
        r = self.get(f"/api/events/{event_id}/snapshot.jpg", timeout=20)
        return r.content if r else None

    def latest_jpg(self, height: int = 720) -> bytes | None:
        r = self.get(f"/api/{self._s.camera}/latest.jpg?h={height}", timeout=15)
        return r.content if r else None

    def reviews_summary(self) -> dict | None:
        r = self.get("/api/review/summary")
        return r.json() if r else None
