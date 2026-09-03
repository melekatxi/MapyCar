"""Cola Redis con colas separadas por dominio y reintentos con backoff exponencial.

No debe hacer: implementar lógica de dominio (eso vive en cada módulo). Ref: ADR-05, diseño 3.1.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

import redis

from app.core.config import get_settings

QUEUE_NAMES = (
    "imports",
    "geocoding",
    "zoning",
    "planning",
    "routing",
    "optimization",
    "exports",
    "notifications",
)


@dataclass
class Job:
    id: str
    queue: str
    payload: dict
    status: str = "queued"  # queued -> running -> succeeded|failed|cancelled
    attempt: int = 0
    error_code: str | None = None


class JobQueue:
    """Cola simple sobre Redis Streams, con reintentos y backoff exponencial."""

    def __init__(
        self, redis_client: redis.Redis, *, max_attempts: int = 3, base_backoff_seconds: float = 0.1
    ) -> None:
        self._redis = redis_client
        self._max_attempts = max_attempts
        self._base_backoff_seconds = base_backoff_seconds

    def _key(self, queue: str) -> str:
        if queue not in QUEUE_NAMES:
            raise ValueError(f"Cola desconocida: {queue}")
        return f"sofia:queue:{queue}"

    def _status_key(self, job_id: str) -> str:
        return f"sofia:job-status:{job_id}"

    def enqueue(self, *, queue: str, payload: dict) -> Job:
        job = Job(id=str(uuid.uuid4()), queue=queue, payload=payload)
        self._redis.rpush(
            self._key(queue), json.dumps({"id": job.id, "payload": payload, "attempt": 0})
        )
        self._redis.set(self._status_key(job.id), "queued")
        return job

    def get_status(self, job_id: str) -> str | None:
        value = self._redis.get(self._status_key(job_id))
        return value.decode() if value else None

    def run_once(self, *, queue: str, handler) -> Job | None:
        """Procesa un elemento de la cola de forma síncrona (usado por el worker/tests)."""
        raw = self._redis.lpop(self._key(queue))
        if raw is None:
            return None
        data = json.loads(raw)
        job = Job(
            id=data["id"],
            queue=queue,
            payload=data["payload"],
            status="running",
            attempt=data["attempt"] + 1,
        )
        self._redis.set(self._status_key(job.id), "running")
        try:
            handler(job.payload)
        except Exception as exc:  # noqa: BLE001 - reintento controlado
            job.error_code = type(exc).__name__
            if job.attempt < self._max_attempts:
                time.sleep(self._base_backoff_seconds * (2 ** (job.attempt - 1)))
                data["attempt"] = job.attempt
                self._redis.rpush(self._key(queue), json.dumps(data))
                job.status = "queued"
            else:
                job.status = "failed"
            self._redis.set(self._status_key(job.id), job.status)
            return job
        job.status = "succeeded"
        self._redis.set(self._status_key(job.id), "succeeded")
        return job


@lru_cache
def get_job_queue() -> JobQueue:
    """Instancia compartida de `JobQueue` sobre el Redis de configuración (`SOFIA_REDIS_URL`)."""
    client = redis.Redis.from_url(get_settings().redis_url)
    return JobQueue(client)
