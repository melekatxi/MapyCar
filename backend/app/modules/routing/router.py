"""Endpoints de rutas diarias. Ref: diseño sección 8.5, RF-16, RF-18–20, 3.BE.7–8, 3.BE.10, 3.BE.12."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.planning.models import DailyRoute
from app.modules.routing import service
from app.modules.routing.deps import get_route_for_editor, require_if_match
from app.modules.routing.schemas import (
    OptimizeRouteRequest,
    OptimizeRouteResponse,
    ReorderStopsRequest,
    ReorderStopsResponse,
    RouteComparisonResponse,
    RouteDetailResponse,
)

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
    route: DailyRoute = Depends(get_route_for_editor),
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
