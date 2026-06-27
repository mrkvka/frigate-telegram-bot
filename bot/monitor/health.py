"""Мониторинг Frigate и авто-рестарт."""

from __future__ import annotations

import http.client
import logging
import os
import socket
import threading
import time
from pathlib import Path

import requests

from bot.config import Settings
from bot.telegram_client import TelegramClient

log = logging.getLogger("frigate-bot")


def latest_recording_age(settings: Settings) -> tuple[float | None, str]:
    root = Path(settings.recordings_dir)
    if not root.exists():
        return None, f"recordings dir missing: {settings.recordings_dir}"

    latest = None
    latest_mtime = 0.0
    try:
        for path in root.rglob("*.mp4"):
            if settings.camera not in path.parts:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest = path
                latest_mtime = mtime
    except Exception as e:
        return None, f"recordings scan failed: {e}"

    if not latest:
        return None, f"no recordings found for camera {settings.camera}"
    return time.time() - latest_mtime, str(latest)


def docker_restart_container(name: str) -> bool:
    docker_socket = "/var/run/docker.sock"
    if not os.path.exists(docker_socket):
        log.warning("docker.sock not found — autorestart unavailable")
        return False
    try:

        class UnixConn(http.client.HTTPConnection):
            def connect(self) -> None:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.settimeout(15)
                self.sock.connect(self.host)

        conn = UnixConn(docker_socket)
        conn.request(
            "POST",
            f"/containers/{name}/restart?t=10",
            headers={"Host": "localhost", "Content-Length": "0"},
        )
        resp = conn.getresponse()
        resp.read()
        log.info("docker_restart %s -> HTTP %s", name, resp.status)
        return resp.status in (200, 204)
    except Exception as e:
        log.error("docker_restart %s error: %s", name, e)
        return False


def monitor_check(settings: Settings) -> tuple[dict[str, str], dict]:
    problems: dict[str, str] = {}
    details: dict = {}

    try:
        stats = requests.get(f"{settings.frigate_url}/api/stats", timeout=15).json()
        cam = (stats.get("cameras") or {}).get(settings.camera)
        if not cam:
            problems["camera_missing"] = f"камера {settings.camera} отсутствует в /api/stats"
        else:
            camera_fps = float(cam.get("camera_fps") or 0)
            process_fps = float(cam.get("process_fps") or 0)
            ffmpeg_pid = cam.get("ffmpeg_pid")
            details.update(
                {"camera_fps": camera_fps, "process_fps": process_fps, "ffmpeg_pid": ffmpeg_pid}
            )
            if camera_fps < settings.camera_fps_min:
                problems["camera_fps"] = f"camera_fps={camera_fps:.1f}, ниже {settings.camera_fps_min:g}"
            if process_fps < settings.process_fps_min:
                problems["process_fps"] = f"process_fps={process_fps:.1f}, ниже {settings.process_fps_min:g}"
            if not ffmpeg_pid:
                problems["ffmpeg_pid"] = "у камеры нет ffmpeg_pid"
    except Exception as e:
        problems["frigate_api"] = f"Frigate API недоступен: {e}"

    age, record_detail = latest_recording_age(settings)
    details["latest_recording"] = record_detail
    if age is None:
        problems["recording_missing"] = record_detail
    else:
        details["recording_age"] = age
        if age > settings.recording_max_age_secs:
            problems["recording_stale"] = (
                f"последний recording старше {int(age)}с "
                f"(порог {settings.recording_max_age_secs}с): {record_detail}"
            )
    return problems, details


class HealthMonitor:
    def __init__(self, settings: Settings, tg: TelegramClient) -> None:
        self._s = settings
        self._tg = tg
        self._active: dict[str, str] = {}
        self._streaks: dict[str, int] = {}
        self._last_restart_ts = 0.0

    def run(self) -> None:
        log.info(
            "health_monitor started interval=%ss threshold=%s autorestart=%s",
            self._s.monitor_interval,
            self._s.monitor_fail_threshold,
            self._s.frigate_autorestart,
        )
        while True:
            try:
                self._tick()
            except Exception:
                log.exception("health_monitor iteration error")
            time.sleep(self._s.monitor_interval)

    def _tick(self) -> None:
        problems, details = monitor_check(self._s)
        now_keys = set(problems)

        for key in now_keys:
            self._streaks[key] = self._streaks.get(key, 0) + 1
            if self._streaks[key] >= self._s.monitor_fail_threshold and key not in self._active:
                self._active[key] = problems[key]
                self._alert(key, problems[key])

        for key in list(self._streaks):
            if key not in now_keys:
                self._streaks[key] = 0

        for key in list(self._active):
            if key not in now_keys:
                old = self._active.pop(key)
                self._tg.send_to_all(
                    f"<b>✅ Frigate recovered</b>\n"
                    f"Камера: <code>{self._s.camera}</code>\n"
                    f"Было: {old}",
                    self._s.owner_chat_ids,
                )
                log.info("monitor recovered %s details=%s", key, details)

    def _alert(self, key: str, message: str) -> None:
        log.warning("monitor alert %s: %s", key, message)
        if key in ("recording_stale", "recording_missing") and self._s.frigate_autorestart:
            now = time.time()
            if now - self._last_restart_ts >= self._s.frigate_autorestart_cooldown:
                log.warning("auto-restarting %s due to %s", self._s.frigate_container, key)
                ok = docker_restart_container(self._s.frigate_container)
                self._last_restart_ts = now
                self._tg.send_to_all(
                    "<b>🔄 Frigate авто-рестарт</b>\n"
                    f"Камера: <code>{self._s.camera}</code>\n"
                    f"Причина: {message}\n"
                    f"Статус: {'✅ выполнен' if ok else '❌ ошибка'}",
                    self._s.owner_chat_ids,
                )
            else:
                wait = int(self._s.frigate_autorestart_cooldown - (now - self._last_restart_ts))
                self._tg.send_to_all(
                    "<b>🚨 Frigate alert</b>\n"
                    f"Камера: <code>{self._s.camera}</code>\n"
                    f"Проблема: {message}\n"
                    f"⏳ Рестарт на cooldown ещё {wait}с",
                    self._s.owner_chat_ids,
                )
        else:
            self._tg.send_to_all(
                f"<b>🚨 Frigate alert</b>\n"
                f"Камера: <code>{self._s.camera}</code>\n"
                f"Проблема: {message}",
                self._s.owner_chat_ids,
            )

    def start_daemon(self) -> threading.Thread:
        thread = threading.Thread(target=self.run, name="health-monitor", daemon=True)
        thread.start()
        return thread
