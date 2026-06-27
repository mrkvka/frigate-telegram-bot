"""Объединение перекрывающихся событий Frigate в один инцидент."""

from __future__ import annotations

import logging

log = logging.getLogger("frigate-bot")


def _duration(ev: dict) -> float:
    start = ev.get("start_time") or 0
    end = ev.get("end_time") or start
    return max(0.0, end - start)


def merge_incident_events(events: list[dict], gap_secs: int) -> list[dict]:
    """
    Frigate иногда создаёт несколько event id на одно движение (потеря трека).
    Группируем по label+camera, если start следующего <= end предыдущего + gap.
    Из группы отправляем одно событие — с наибольшей длительностью клипа.
    """
    if not events:
        return []

    sorted_evs = sorted(events, key=lambda e: (e.get("start_time") or 0))
    groups: list[list[dict]] = []

    for ev in sorted_evs:
        start = ev.get("start_time") or 0
        label = ev.get("label", "")
        camera = ev.get("camera", "")
        placed = False
        for group in groups:
            anchor = group[0]
            if anchor.get("label") != label or anchor.get("camera") != camera:
                continue
            group_end = max(e.get("end_time") or 0 for e in group)
            if start <= group_end + gap_secs:
                group.append(ev)
                placed = True
                break
        if not placed:
            groups.append([ev])

    merged: list[dict] = []
    for group in groups:
        if len(group) > 1:
            ids = [e.get("id") for e in group]
            log.info(
                "merged %d events label=%s into one (ids=%s)",
                len(group),
                group[0].get("label"),
                ids,
            )
        best = max(group, key=lambda e: (_duration(e), e.get("end_time") or 0))
        merged.append(best)

    merged.sort(key=lambda e: (e.get("end_time") or 0))
    return merged
