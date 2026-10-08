"""Lightweight background job store for long LLM requests."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class JobRecord:
    id: str
    kind: str
    status: str  # queued | running | completed | failed
    created_at: str
    updated_at: str
    result: Any | None = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    tenant_id: str = ""  # owner: only this tenant may read the job

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobStore:
    def __init__(self, max_workers: int = 2):
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def submit(self, kind: str, fn: Callable[[], Any], meta: dict | None = None, tenant_id: str = "") -> str:
        job_id = uuid.uuid4().hex
        now = self._now()
        record = JobRecord(
            id=job_id,
            kind=kind,
            status="queued",
            created_at=now,
            updated_at=now,
            meta=meta or {},
            tenant_id=tenant_id,
        )
        with self._lock:
            self._jobs[job_id] = record

        def _run():
            with self._lock:
                rec = self._jobs[job_id]
                rec.status = "running"
                rec.updated_at = self._now()
            try:
                result = fn()
                with self._lock:
                    rec = self._jobs[job_id]
                    rec.status = "completed"
                    rec.result = result
                    rec.updated_at = self._now()
            except Exception as exc:
                with self._lock:
                    rec = self._jobs[job_id]
                    rec.status = "failed"
                    rec.error = str(exc)
                    rec.updated_at = self._now()

        self._pool.submit(_run)
        return job_id

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_for_tenant(self, job_id: str, tenant_id: str) -> JobRecord | None:
        """The job, only if it belongs to ``tenant_id``. Another tenant's job looks like a missing one."""
        job = self.get(job_id)
        return job if job is not None and job.tenant_id == tenant_id else None


job_store = JobStore()
