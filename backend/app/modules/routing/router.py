"""Endpoints de rutas diarias. Ref: diseño sección 8.5, RF-16, RF-18–21, RF-25, 3.BE.7–12, 4.BE.2."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Header, Response
from sqlalchemy.orm import Session

from app.adapters.router.interface import Router
from app.core.crypto import FieldCipher
from app.core.errors import DomainError
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.imports.deps import get_field_cipher
from app.modules.planning.models import DailyRoute
from app.modules.routing import export as export_service
from app.modules.routing import service
from app.modules.routing.deps import (
    get_route_for_editor,
    get_route_for_execution,
    get_route_for_viewer,
    require_if_match,
)
from app.modules.routing.schemas import (
    ExportRouteRequest,
    ExportRouteResponse,
    OptimizeRouteRequest,
    OptimizeRouteResponse,
    PublishRouteRequest,
    PublishRouteResponse,
    ReorderStopsRequest,
    ReorderStopsResponse,
    ReplaceStopsRequest,
    ReplaceStopsResponse,
    ReportStopExecutionRequest,
    RouteComparisonResponse,
    RouteDetailResponse,
    RouteStopExecutionOut,
)
from app.modules.zoning.deps import get_router

router = APIRouter(prefix="/routes", tags=["routing"])


def _etag(version: int) -> str:
    return f'"{version}"'


@router.post("/{route_id}/optimize", status_code=202, response_model=OptimizeRouteResponse)
def optimize_route(
    payload: OptimizeRouteRequest,
    route: DailyRoute = Depends(get_route_for_editor),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    queue: JobQueue = Depends(get_job_queue),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> OptimizeRouteResponse:
    if not idempotency_key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Falta la cabecera Idempotency-Key")
    return service.enqueue_optimize(
        db,
        route,
        payload,
        idempotency_key=idempotency_key,
        created_by=current_user.id,
        queue=queue,
    )


@router.get("/{route_id}", response_model=RouteDetailResponse)
def get_route(
    route: DailyRoute = Depends(get_route_for_viewer),
    db: Session = Depends(get_db),
) -> RouteDetailResponse:
    return service.get_route_detail(db, route)


@router.get("/{route_id}/comparison", response_model=RouteComparisonResponse)
def get_route_comparison(
    route: DailyRoute = Depends(get_route_for_editor),
    db: Session = Depends(get_db),
) -> RouteComparisonResponse:
    return service.get_comparison(db, route)


@router.patch("/{route_id}/stops/order", response_model=ReorderStopsResponse)
def reorder_route_stops(
    payload: ReorderStopsRequest,
    response: Response,
    route: DailyRoute = Depends(get_route_for_editor),
    expected_version: int = Depends(require_if_match),
    db: Session = Depends(get_db),
) -> ReorderStopsResponse:
    reordered = service.reorder_stops(
        db,
        route,
        revision_id=payload.revision_id,
        ordered_stop_ids=payload.ordered_stop_ids,
        expected_version=expected_version,
    )
    response.headers["ETag"] = _etag(reordered.version)
    return reordered


@router.put("/{route_id}/stops", response_model=ReplaceStopsResponse)
def replace_route_stops(
    payload: ReplaceStopsRequest,
    response: Response,
    route: DailyRoute = Depends(get_route_for_editor),
    expected_version: int = Depends(require_if_match),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReplaceStopsResponse:
    replaced = service.replace_stops(
        db,
        route,
        patient_ids=payload.patient_ids,
        expected_version=expected_version,
        created_by=current_user.id,
    )
    response.headers["ETag"] = _etag(replaced.version)
    return replaced


@router.post("/{route_id}/publish", status_code=200, response_model=PublishRouteResponse)
def publish_route(
    response: Response,
    payload: PublishRouteRequest = Body(default_factory=PublishRouteRequest),
    route: DailyRoute = Depends(get_route_for_editor),
    expected_version: int = Depends(require_if_match),
    db: Session = Depends(get_db),
    router: Router = Depends(get_router),
    cipher: FieldCipher = Depends(get_field_cipher),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PublishRouteResponse:
    if not idempotency_key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Falta la cabecera Idempotency-Key")
    published = service.publish_route(
        db,
        route,
        payload,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
        router=router,
        cipher=cipher,
    )
    response.headers["ETag"] = _etag(published.version)
    return published


@router.patch("/{route_id}/stops/{stop_id}", response_model=RouteStopExecutionOut)
def report_stop_execution(
    stop_id: uuid.UUID,
    payload: ReportStopExecutionRequest,
    response: Response,
    route: DailyRoute = Depends(get_route_for_execution),
    expected_version: int = Depends(require_if_match),
    db: Session = Depends(get_db),
) -> RouteStopExecutionOut:
    reported = service.report_stop_execution(
        db,
        route,
        stop_id=stop_id,
        payload=payload,
        expected_version=expected_version,
    )
    response.headers["ETag"] = _etag(reported.version)
    return reported


@router.post("/{route_id}/exports", status_code=202, response_model=ExportRouteResponse)
def export_route(
    payload: ExportRouteRequest,
    route: DailyRoute = Depends(get_route_for_editor),
    db: Session = Depends(get_db),
    queue: JobQueue = Depends(get_job_queue),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ExportRouteResponse:
    if not idempotency_key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Falta la cabecera Idempotency-Key")
    return export_service.enqueue_export(
        db,
        route,
        payload,
        idempotency_key=idempotency_key,
        queue=queue,
    )
