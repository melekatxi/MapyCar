"""Consulta de jobs. Ref: diseño sección 8.5, 3.FE.1 / 3.BE.13."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.adapters.object_store.interface import ObjectStore
from app.core.errors import DomainError
from app.db.session import get_db
from app.modules.identity.deps import require_organization_member
from app.modules.identity.models import User
from app.modules.imports.deps import get_object_store
from app.modules.jobs.models import Job
from app.modules.jobs.schemas import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: uuid.UUID,
    organization_id: uuid.UUID,
    _: User = Depends(require_organization_member),
    db: Session = Depends(get_db),
) -> JobOut:
    job = db.get(Job, job_id)
    if job is None or job.organization_id != organization_id:
        raise DomainError(404, "JOB_NOT_FOUND", "Trabajo no encontrado")
    return JobOut.model_validate(job, from_attributes=True)


@router.get("/{job_id}/artifact")
def get_job_artifact(
    job_id: uuid.UUID,
    organization_id: uuid.UUID,
    _: User = Depends(require_organization_member),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
) -> Response:
    job = db.get(Job, job_id)
    if job is None or job.organization_id != organization_id:
        raise DomainError(404, "JOB_NOT_FOUND", "Trabajo no encontrado")
    result = job.result_json or {}
    object_key = result.get("object_key")
    if not object_key:
        raise DomainError(404, "EXPORT_ARTIFACT_MISSING", "El trabajo no tiene fichero")
    try:
        content = store.get(key=str(object_key))
    except KeyError as exc:
        raise DomainError(404, "EXPORT_ARTIFACT_MISSING", "El fichero de exportación no existe") from exc
    media = str(result.get("content_type") or "application/octet-stream")
    filename = str(object_key).rsplit("/", 1)[-1]
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
