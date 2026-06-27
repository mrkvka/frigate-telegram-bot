"""Нормализация видео для Telegram (ffmpeg/ffprobe)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass

from bot.config import Settings

log = logging.getLogger("frigate-bot")


@dataclass(frozen=True)
class VideoMeta:
    width: int | None
    height: int | None
    frame_count: int


def upload_timeout(size_bytes: int) -> int:
    """Таймаут загрузки ~40 KB/s, от 300 до 600 сек."""
    return min(600, max(300, size_bytes // (40 * 1024)))


def probe_video_file(path: str) -> VideoMeta:
    """Один вызов ffprobe: размеры + число пакетов."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "v:0",
                "-count_packets",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return VideoMeta(None, None, 0)
        streams = json.loads(result.stdout).get("streams", [])
        if not streams:
            return VideoMeta(None, None, 0)
        stream = streams[0]
        packets = stream.get("nb_read_packets") or stream.get("nb_packets") or 0
        try:
            frame_count = int(packets) if packets not in (None, "N/A", "") else 0
        except (TypeError, ValueError):
            frame_count = 0
        return VideoMeta(stream.get("width"), stream.get("height"), frame_count)
    except Exception as e:
        log.warning("probe_video_file error: %s", e)
        return VideoMeta(None, None, 0)


def _audio_filter(settings: Settings) -> str:
    base = "aresample=async=1000"
    if os.path.exists(settings.rnnoise_model):
        return f"{base},arnndn=model={settings.rnnoise_model},loudnorm=I=-16:TP=-1.5:LRA=11"
    return f"{base},loudnorm=I=-16:TP=-1.5:LRA=11"


def normalize_for_telegram(video_bytes: bytes, duration: int, settings: Settings) -> tuple[bytes, VideoMeta]:
    """Перекодирует клип Frigate в MP4, совместимый с Telegram."""
    if not settings.fix_telegram_video:
        meta = _probe_bytes(video_bytes)
        return video_bytes, meta

    seconds = max(1, int(duration or 10) + 1)
    input_path = output_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="frigate-clip-", suffix=".mp4", delete=False) as src:
            src.write(video_bytes)
            input_path = src.name
        with tempfile.NamedTemporaryFile(prefix="telegram-clip-", suffix=".mp4", delete=False) as dst:
            output_path = dst.name

        meta = probe_video_file(input_path)
        source_fps = meta.frame_count / seconds if meta.frame_count else settings.video_fix_fps
        source_fps = min(max(source_fps or 25.0, 1.0), 30.0)

        filters = [f"setpts=N/({source_fps:.6f}*TB)"]
        if settings.video_fix_width > 0:
            filters.append(f"scale={settings.video_fix_width}:-2:flags=lanczos")
        if settings.video_fix_fps > 0:
            filters.append(f"fps={settings.video_fix_fps}")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-loglevel",
            "error",
            "-fflags",
            "+genpts+igndts",
            "-i",
            input_path,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            ",".join(filters),
            "-af",
            _audio_filter(settings),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(settings.video_fix_crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.video_fix_timeout)
        if result.returncode != 0:
            log.error("ffmpeg failed: %s", result.stderr.strip()[:500])
            return video_bytes, meta

        with open(output_path, "rb") as fixed:
            fixed_bytes = fixed.read()
        out_meta = probe_video_file(output_path)
        log.info(
            "normalized video: %d -> %d bytes, %ss, fps=%.2f, %sx%s, crf=%s",
            len(video_bytes),
            len(fixed_bytes),
            seconds,
            source_fps,
            out_meta.width or "?",
            out_meta.height or "?",
            settings.video_fix_crf,
        )
        return fixed_bytes, out_meta
    except Exception as e:
        log.error("video normalization error: %s", e)
        return video_bytes, VideoMeta(None, None, 0)
    finally:
        for path in (input_path, output_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def _probe_bytes(video_bytes: bytes) -> VideoMeta:
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(video_bytes)
        path = f.name
    try:
        return probe_video_file(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
