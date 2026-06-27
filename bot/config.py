"""Конфигурация из переменных окружения."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip() == "1"


def _parse_owner_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return ids


@dataclass(frozen=True)
class Settings:
    bot_token: str
    owner_chat_ids: frozenset[int]
    frigate_url: str
    tg_api_base: str
    camera: str
    poll_timeout: int
    max_video_mb: int
    fix_telegram_video: bool
    video_fix_width: int
    video_fix_fps: int
    video_fix_crf: int
    video_fix_timeout: int
    rnnoise_model: str
    auto_events: bool
    event_poll_secs: int
    clip_wait_secs: int
    clip_ready_timeout: int
    clip_ready_poll: int
    event_merge_gap_secs: int
    send_video_retries: int
    send_video_retry_delay: float
    send_snapshot_on_missing_clip: bool
    monitor_enabled: bool
    monitor_interval: int
    monitor_fail_threshold: int
    camera_fps_min: float
    process_fps_min: float
    recordings_dir: str
    recording_max_age_secs: int
    frigate_autorestart: bool
    frigate_container: str
    frigate_autorestart_cooldown: int
    heartbeat_file: str = "/tmp/bot_alive"

    @property
    def tg_api_url(self) -> str:
        return f"{self.tg_api_base}/bot{self.bot_token}"

    @property
    def primary_owner_id(self) -> int:
        return next(iter(self.owner_chat_ids))

    @classmethod
    def from_env(cls) -> Settings:
        token = os.environ.get("BOT_TOKEN", "").strip()
        owners_raw = os.environ.get("OWNER_CHAT_ID", "").strip()
        if not token:
            print("FATAL: BOT_TOKEN env var is required", file=sys.stderr)
            sys.exit(1)
        if not owners_raw:
            print("FATAL: OWNER_CHAT_ID env var is required", file=sys.stderr)
            sys.exit(1)
        owner_ids = _parse_owner_ids(owners_raw)
        if not owner_ids:
            print("FATAL: OWNER_CHAT_ID has no valid IDs", file=sys.stderr)
            sys.exit(1)

        return cls(
            bot_token=token,
            owner_chat_ids=frozenset(owner_ids),
            frigate_url=os.environ.get("FRIGATE_URL", "http://frigate:5000").strip().rstrip("/"),
            tg_api_base=os.environ.get("TG_API_BASE", "https://api.telegram.org").strip().rstrip("/"),
            camera=os.environ.get("CAMERA", "front").strip(),
            poll_timeout=int(os.environ.get("POLL_TIMEOUT", "30")),
            max_video_mb=int(os.environ.get("MAX_VIDEO_MB", "45")),
            fix_telegram_video=_env_bool("FIX_TELEGRAM_VIDEO", "1"),
            video_fix_width=int(os.environ.get("VIDEO_FIX_WIDTH", "0")),
            video_fix_fps=int(os.environ.get("VIDEO_FIX_FPS", "0")),
            video_fix_crf=int(os.environ.get("VIDEO_FIX_CRF", "23")),
            video_fix_timeout=int(os.environ.get("VIDEO_FIX_TIMEOUT", "240")),
            rnnoise_model=os.environ.get("RNNOISE_MODEL", "/frigate_config/rnnoise.rnnn").strip(),
            auto_events=_env_bool("AUTO_EVENTS", "1"),
            event_poll_secs=int(os.environ.get("EVENT_POLL_SECS", "10")),
            clip_wait_secs=int(os.environ.get("CLIP_WAIT_SECS", "5")),
            clip_ready_timeout=int(os.environ.get("CLIP_READY_TIMEOUT", "90")),
            clip_ready_poll=int(os.environ.get("CLIP_READY_POLL", "5")),
            event_merge_gap_secs=int(os.environ.get("EVENT_MERGE_GAP_SECS", "30")),
            send_video_retries=int(os.environ.get("SEND_VIDEO_RETRIES", "5")),
            send_video_retry_delay=float(os.environ.get("SEND_VIDEO_RETRY_DELAY", "8")),
            send_snapshot_on_missing_clip=_env_bool("SEND_SNAPSHOT_ON_MISSING_CLIP", "1"),
            monitor_enabled=_env_bool("MONITOR_ENABLED", "1"),
            monitor_interval=int(os.environ.get("MONITOR_INTERVAL", "60")),
            monitor_fail_threshold=int(os.environ.get("MONITOR_FAIL_THRESHOLD", "2")),
            camera_fps_min=float(os.environ.get("CAMERA_FPS_MIN", "1")),
            process_fps_min=float(os.environ.get("PROCESS_FPS_MIN", "1")),
            recordings_dir=os.environ.get("RECORDINGS_DIR", "/media/frigate/recordings").strip(),
            recording_max_age_secs=int(os.environ.get("RECORDING_MAX_AGE_SECS", "180")),
            frigate_autorestart=_env_bool("FRIGATE_AUTORESTART", "1"),
            frigate_container=os.environ.get("FRIGATE_CONTAINER", "frigate").strip(),
            frigate_autorestart_cooldown=int(os.environ.get("FRIGATE_AUTORESTART_COOLDOWN", "600")),
        )
