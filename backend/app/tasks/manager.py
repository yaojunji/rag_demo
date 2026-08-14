"""后台任务管理：文档索引任务注册表（asyncio）。

- 同一知识库的索引任务串行执行（per-kb 锁），避免 SQLite 写锁竞争
- 任务在进程内运行；重启后遗留的 pending/processing 文档会在启动时标记为失败
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TaskManager:
    """文档索引任务管理。

    - 同一知识库的任务串行执行（per-kb 锁），避免 SQLite 写竞争
    - 全局并发上限（_MAX_CONCURRENT），避免 embedding/LLM 网关被瞬时打满
    - 重启后遗留的 pending/processing 文档会在启动时标记为失败
    """

    _MAX_CONCURRENT = 3

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}
        self._kb_locks: dict[int, asyncio.Lock] = {}
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(self._MAX_CONCURRENT)

    async def submit(self, doc_id: int, kb_id: int, coro) -> None:
        async with self._lock:
            old = self._tasks.get(doc_id)
            if old and not old.done():
                old.cancel()
            task = asyncio.create_task(self._run(kb_id, doc_id, coro))
            self._tasks[doc_id] = task

    async def _run(self, kb_id: int, doc_id: int, coro):
        async with self._sem:
            lock = self._kb_locks.setdefault(kb_id, asyncio.Lock())
            try:
                async with lock:
                    await coro
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.exception("index task crashed doc=%s kb=%s: %s", doc_id, kb_id, e)

    def is_running(self, doc_id: int) -> bool:
        t = self._tasks.get(doc_id)
        return bool(t and not t.done())

    async def wait(self, doc_id: int, timeout: float = 300.0) -> Optional[asyncio.Task]:
        t = self._tasks.get(doc_id)
        if t:
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout)
            except asyncio.TimeoutError:
                pass
        return t

    def running_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())


task_manager = TaskManager()
