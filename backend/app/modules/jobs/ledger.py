"""Ledger de Idempotency-Key sobre `jobs`. Ref: diseño 8.1, 3.BE.14.

Misma org+tipo+clave y mismo hash → replay (devuelve el job existente).
Misma clave y payload distinto → 409 IDEMPOTENCY_KEY_REUSE.
Falta de clave: responsabilidad del caller (p. ej. POST /imports ya responde 400).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.modules.jobs.models import Job


def hash_request_payload(payload: Any) -> str:
    """SHA-256 hex del JSON canónico (claves ordenadas, sin espacios)."""
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _get_job(
    db: Session,
    *,
    organization_id: uuid.UUID,
    job_type: str,
    idempotency_key: str,
) -> Job | None:
    return (
        db.query(Job)
        .filter(
            Job.organization_id == organization_id,
            Job.type == job_type,
            Job.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )


def _reuse_error() -> DomainError:
    return DomainError(
        409,
        "IDEMPOTENCY_KEY_REUSE",
        "La Idempotency-Key ya se usó con un payload distinto",
    )


def begin_idempotent_job(
    db: Session,
    *,
    organization_id: uuid.UUID,
    job_type: str,
    idempotency_key: str,
    payload: Any,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
) -> Job:
    """Crea o reutiliza un job durable para la tripleta (org, tipo, clave)."""
    request_hash = hash_request_payload(payload)
    existing = _get_job(
        db,
        organization_id=organization_id,
        job_type=job_type,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise _reuse_error()
        return existing

    job = Job(
        organization_id=organization_id,
        type=job_type,
        resource_type=resource_type,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
        return job
    except IntegrityError:
        existing = _get_job(
            db,
            organization_id=organization_id,
            job_type=job_type,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            raise
        if existing.request_hash != request_hash:
            raise _reuse_error() from None
        return existing
