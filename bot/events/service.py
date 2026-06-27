"""Подготовка и рассылка review-клипов Frigate."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from bot.config import Settings
from bot.frigate_client import FrigateClient
from bot.media.video import VideoMeta, normalize_for_telegram
from bot.telegram_client import TelegramClient

log = logging.getLogger("frigate-bot")


@dataclass(frozen=True)
class PreparedReview:
    caption: str
    video_bytes: bytes | None
    meta: VideoMeta | None
    error_suffix: str | None = None


def build_caption(review: dict, title: str = "🎬 Review") -> tuple[str, int]:
    data = review.get("data") or {}
    objects = data.get("objects") or ["?"]
    labels = ", ".join(objects)
    severity = review.get("severity", "?")
    cam = review.get("camera", "?")
    start = review.get("start_time", 0)
    end = review.get("end_time") or start
    duration = max(0, int(end - start))
    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start))
    severity_label = "🚨 Alert" if severity == "alert" else "ℹ️ Detection"
    caption = (
        f"<b>{title}</b>\n"
        f"Объекты: <b>{labels}</b>\n"
        f"Тип: {severity_label}\n"
        f"Камера: {cam}\n"
        f"Время: {dt}\n"
        f"Длительность: ~{duration}с"
    )
    return caption, duration


class ReviewService:
    def __init__(
        self,
        settings: Settings,
        tg: TelegramClient,
        frigate: FrigateClient,
    ) -> None:
        self._s = settings
        self._tg = tg
        self._frigate = frigate

    def prepare(self, review: dict, title: str = "🎬 Review") -> PreparedReview:
        caption, duration = build_caption(review, title=title)
        camera = review.get("camera") or self._s.camera
        start = review.get("start_time", 0)
        end = review.get("end_time") or start
        raw = self._frigate.wait_for_recording_clip(camera, start, end)
        if not raw:
            return PreparedReview(caption, None, None, error_suffix="\n\n⚠️ Записи для клипа нет")

        video_bytes, meta = normalize_for_telegram(raw, duration, self._s)
        max_bytes = self._s.max_video_mb * 1024 * 1024
        if len(video_bytes) > max_bytes:
            suffix = f"\n\n⚠️ Клип слишком большой ({len(video_bytes) // 1024 // 1024}MB)"
            return PreparedReview(caption, None, meta, error_suffix=suffix)
        return PreparedReview(caption, video_bytes, meta)

    def _notify_missing(self, prepared: PreparedReview, chat_ids: frozenset[int], review: dict) -> None:
        suffix = prepared.error_suffix or ""
        if self._s.send_snapshot_on_missing_clip and "нет" in suffix:
            preview = self._frigate.review_preview(review.get("id", ""))
            if preview:
                suffix = "\n\n⚠️ Записи для клипа нет, отправляю preview."
                for uid in chat_ids:
                    self._tg.send_photo(uid, preview, caption=prepared.caption + suffix)
                return
            detections = (review.get("data") or {}).get("detections") or []
            if detections:
                snap = self._frigate.event_snapshot(detections[0])
                if snap:
                    suffix = "\n\n⚠️ Записи для клипа нет, отправляю snapshot."
                    for uid in chat_ids:
                        self._tg.send_photo(uid, snap, caption=prepared.caption + suffix)
                    return
        for uid in chat_ids:
            self._tg.send_message(uid, prepared.caption + suffix)

    def broadcast(self, review: dict, title: str = "🚨 Новое событие") -> tuple[int, int]:
        rid = review.get("id")
        prepared = self.prepare(review, title=title)
        owners = self._s.owner_chat_ids
        total = len(owners)

        if not prepared.video_bytes:
            self._notify_missing(prepared, owners, review)
            return 0, total

        width = prepared.meta.width if prepared.meta else None
        height = prepared.meta.height if prepared.meta else None

        def send_one(uid: int) -> tuple[int, bool]:
            ok = bool(self._tg.send_video(uid, prepared.video_bytes, prepared.caption, width, height))
            return uid, ok

        results: dict[int, bool] = {}
        with ThreadPoolExecutor(max_workers=max(1, total)) as pool:
            futures = [pool.submit(send_one, uid) for uid in owners]
            for fut in as_completed(futures):
                uid, ok = fut.result()
                results[uid] = ok

        failed = [uid for uid, ok in results.items() if not ok]
        if failed:
            log.warning("broadcast retry for %d user(s): %s", len(failed), failed)
            time.sleep(self._s.send_video_retry_delay)
            for uid in failed:
                if self._tg.send_video(uid, prepared.video_bytes, prepared.caption, width, height):
                    results[uid] = True

        still_failed = [uid for uid, ok in results.items() if not ok]
        for uid in still_failed:
            self._tg.send_message(uid, prepared.caption + "\n\n⚠️ Не удалось доставить видео, попробуй /last")

        sent = sum(1 for ok in results.values() if ok)
        log.info(
            "broadcast review id=%s sent=%d/%d size=%dKB",
            rid,
            sent,
            total,
            len(prepared.video_bytes) // 1024,
        )
        return sent, total

    def send_one(self, chat_id: int, review: dict, title: str = "🎬 Review") -> bool:
        prepared = self.prepare(review, title=title)
        if not prepared.video_bytes:
            self._notify_missing(prepared, frozenset({chat_id}), review)
            return False
        width = prepared.meta.width if prepared.meta else None
        height = prepared.meta.height if prepared.meta else None
        return bool(self._tg.send_video(chat_id, prepared.video_bytes, prepared.caption, width, height))
