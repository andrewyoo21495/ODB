"""In-memory task registry for background work (cache builds, analyses).

Skeleton-grade: task state lives in process memory and is lost on restart (the
produced cache/report files persist in the workspace).  Swap for Celery/RQ +
Redis when concurrency demands it — the routers only touch this small API.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    id: str
    kind: str                       # "cache" | "checklist" | ...
    job_id: str | None = None
    status: str = "queued"          # queued | running | done | error
    progress: float = 0.0
    message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class TaskRegistry:
    """Thread-safe map of task id -> :class:`Task`."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    def create(self, kind: str, job_id: str | None = None) -> Task:
        task = Task(id=uuid.uuid4().hex[:16], kind=kind, job_id=job_id)
        with self._lock:
            self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **fields: Any) -> Task | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                for key, value in fields.items():
                    setattr(task, key, value)
            return task

    def latest_for_job(self, job_id: str, kind: str) -> Task | None:
        """Most recently created task of *kind* for *job_id* (or None)."""
        with self._lock:
            matches = [t for t in self._tasks.values()
                       if t.job_id == job_id and t.kind == kind]
        return matches[-1] if matches else None


# Process-wide singleton.
registry = TaskRegistry()
