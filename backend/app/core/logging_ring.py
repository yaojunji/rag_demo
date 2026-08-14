"""环形缓冲日志 Handler：进程内保留最近 N 条日志，供管理端查看。"""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._buffer: deque[dict] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "time": datetime.utcnow().isoformat() + "Z",
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage()[:2000],
            }
            with self._lock:
                self._buffer.append(entry)
        except Exception:  # noqa: BLE001
            pass

    def snapshot(self, level: str = "INFO", limit: int = 200) -> list[dict]:
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        min_level = levels.get(level.upper(), 20)
        with self._lock:
            rows = [e for e in self._buffer if levels.get(e["level"], 20) >= min_level]
        return list(reversed(rows))[:limit]


ring_handler = RingBufferHandler()
ring_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
