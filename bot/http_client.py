"""Общий HTTP-клиент с пулом соединений."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter

_session: requests.Session | None = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _session = session
    return _session
