"""Exportación de ruta publicada: PDF, PNG y enlace de navegación. Ref: 3.BE.13, RF-22."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.object_store.interface import ObjectStore
from app.core.errors import DomainError
from app.jobs.queue import JobQueue
from app.modules.identity import service as identity_service
from app.modules.jobs.ledger import begin_idempotent_job
from app.modules.planning.models import DailyRoute
from app.modules.routing.export_render import navigation_url, render_pdf, render_png, tour_points
from app.modules.routing.models import RouteRevision
from app.modules.routing.schemas import ExportRouteRequest, ExportRouteResponse
from app.modules.routing.service import OptimizeJobError, _lock_job

EXPORT_JOB_TYPE = "route.export"
EXPORT_QUEUE = "exports"
_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "navigation_link": "text/uri-list",
}


def enqueue_export(
    db: Session,
    route: DailyRoute,
    payload: ExportRouteRequest,
    *,
    idempotency_key: str,
    queue: JobQueue,
) -> ExportRouteResponse:
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    revision_id = payload.revision_id or route.current_revision
    if revision_id is None:
        raise DomainError(409, "REVISION_NOT_FOUND", "La ruta no tiene revisión para exportar")
    revision = db.get(RouteRevision, revision_id)
    if revision is None or revision.route_id != route.id:
        raise DomainError(404, "REVISION_NOT_FOUND", "Revisión no encontrada")
    if revision.status != "published":
        raise DomainError(409, "REVISION_NOT_PUBLISHED", "Solo se exporta una revisión publicada")
    ledger_payload = {
        "route_id": str(route.id),
        "format": payload.format,
        "revision_id": str(revision_id),
    }
    job = begin_idempotent_job(
        db,
        organization_id=route.organization_id,
        job_type=EXPORT_JOB_TYPE,
        idempotency_key=idempotency_key,
        payload=ledger_payload,
        resource_type="route",
        resource_id=route.id,
    )
    if job.result_json:
        return ExportRouteResponse.model_validate(job.result_json)

    queue.enqueue(
        queue=EXPORT_QUEUE,
        payload={
            "job_id": str(job.id),
            "route_id": str(route.id),
            "organization_id": str(route.organization_id),
            "revision_id": str(revision_id),
            "format": payload.format,
        },
    )
    response = ExportRouteResponse(job_id=job.id, status="queued", format=payload.format)
    job.result_json = response.model_dump(mode="json")
    db.commit()
    db.refresh(job)
    return response


def export_route_job(
    db: Session,
    store: ObjectStore,
    *,
    route_id: uuid.UUID,
    organization_id: uuid.UUID,
    revision_id: uuid.UUID,
    format: str,
    job_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    job = _lock_job(db, job_id, organization_id=organization_id)
    if job is not None:
        job.status = "running"
        job.progress = max(job.progress, 10)
        job.attempt = job.attempt + 1
    try:
        result = _run_export(
            db,
            store,
            route_id=route_id,
            organization_id=organization_id,
            revision_id=revision_id,
            format=format,
            job_id=job.id if job is not None else uuid.uuid4(),
        )
    except OptimizeJobError as exc:
        if job is not None:
            job.status = "failed"
            job.error_code = exc.code
        db.commit()
        return {}
    if job is not None:
        job.status = "succeeded"
        job.progress = 100
        job.error_code = None
        merged = dict(job.result_json or {})
        merged.update(result)
        merged["status"] = "succeeded"
        job.result_json = merged
        db.commit()
    return result


def _run_export(
    db: Session,
    store: ObjectStore,
    *,
    route_id: uuid.UUID,
    organization_id: uuid.UUID,
    revision_id: uuid.UUID,
    format: str,
    job_id: uuid.UUID,
) -> dict[str, Any]:
    route = db.get(DailyRoute, route_id)
    if route is None or route.organization_id != organization_id:
        raise OptimizeJobError("ROUTE_NOT_FOUND", "Ruta no encontrada")
    revision = (
        db.query(RouteRevision)
        .filter(
            RouteRevision.id == revision_id,
            RouteRevision.route_id == route.id,
            RouteRevision.organization_id == organization_id,
        )
        .one_or_none()
    )
    if revision is None:
        raise OptimizeJobError("REVISION_NOT_FOUND", "Revisión no encontrada")
    if revision.status != "published":
        raise OptimizeJobError("REVISION_NOT_PUBLISHED", "Solo se exporta una revisión publicada")
    snapshot = (revision.constraints_json or {}).get("snapshot") or {}
    points = tour_points(snapshot)
    if len(points) < 2:
        raise OptimizeJobError("SNAPSHOT_UNAVAILABLE", "La revisión no tiene geometría/paradas para exportar")

    content_type = _CONTENT_TYPES[format]
    object_key: str | None = None
    nav: str | None = None
    if format == "navigation_link":
        nav = navigation_url(points)
    elif format == "pdf":
        object_key = f"exports/{organization_id}/{route_id}/{job_id}.pdf"
        store.put(key=object_key, content=render_pdf(points), content_type=content_type)
    elif format == "png":
        object_key = f"exports/{organization_id}/{route_id}/{job_id}.png"
        store.put(key=object_key, content=render_png(points), content_type=content_type)
    else:
        raise OptimizeJobError("EXPORT_FORMAT_INVALID", "Formato de exportación no válido")
    return {
        "format": format,
        "object_key": object_key,
        "content_type": content_type,
        "navigation_url": nav,
    }
