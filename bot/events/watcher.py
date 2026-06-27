"""Фоновый опрос Frigate review API."""

from __future__ import annotations

import logging
import threading
import time

from bot.config import Settings
from bot.events.service import ReviewService
from bot.frigate_client import FrigateClient

log = logging.getLogger("frigate-bot")


def _completed_reviews(reviews: list[dict], after_end_ts: float, camera: str) -> list[dict]:
    result: list[dict] = []
    for review in reviews:
        end_time = review.get("end_time")
        if not end_time or end_time <= after_end_ts:
            continue
        if review.get("camera") != camera:
            continue
        result.append(review)
    result.sort(key=lambda r: r.get("end_time") or 0)
    return result


class ReviewWatcher:
    def __init__(
        self,
        settings: Settings,
        frigate: FrigateClient,
        reviews: ReviewService,
    ) -> None:
        self._s = settings
        self._frigate = frigate
        self._reviews = reviews
        self._last_sent_end_ts = time.time()

    def run(self) -> None:
        log.info(
            "review_watcher started baseline=%.0f poll=%ds severity=%s camera=%s",
            self._last_sent_end_ts,
            self._s.review_poll_secs,
            self._s.review_severity,
            self._s.camera,
        )
        while True:
            try:
                batch = self._frigate.reviews(after_ts=int(self._last_sent_end_ts))
                batch = _completed_reviews(batch, self._last_sent_end_ts, self._s.camera)

                for review in batch:
                    end_time = review.get("end_time") or 0
                    data = review.get("data") or {}
                    time.sleep(self._s.clip_wait_secs)
                    log.info(
                        "auto-sending review id=%s objects=%s end=%.0f dur=%.0fs detections=%d to %d user(s)",
                        review.get("id"),
                        data.get("objects"),
                        end_time,
                        end_time - (review.get("start_time") or 0),
                        len(data.get("detections") or []),
                        len(self._s.owner_chat_ids),
                    )
                    try:
                        self._reviews.broadcast(review, title="🚨 Новое событие")
                    except Exception:
                        log.exception("broadcast failed review id=%s", review.get("id"))
                    self._last_sent_end_ts = end_time
            except Exception:
                log.exception("review_watcher iteration error")
            time.sleep(self._s.review_poll_secs)

    def start_daemon(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, name="review-watcher", daemon=True)
        thread.start()
        return thread
