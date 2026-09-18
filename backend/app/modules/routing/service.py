"""Servicio de rutas diarias: optimización, paradas, comparativa, publish y ejecución.

Ref: RF-16, RF-18–21, RF-25, 3.BE.7–12, 4.BE.2.

If-Match de planificación usa `daily_routes.version` (route_revisions no tiene columna version).
PATCH de ejecución usa `route_stops.version`. No muta snapshot ni orden publicados.
Tras reordenar o sustituir paradas, route_metrics.calculation_json.stale = true.
GET /comparison lee original vs optimized de current_revision y 409 si faltan o están stale.
Si hay `variant=actual` (4.BE.3) incluye desviación vs el plan optimizado (sin GPS).
POST /optimize es idempotente (ledger `route.optimize`); el hash incluye el conjunto de paradas
(diseño 11.1: un cambio de parada exige nueva Idempotency-Key).
POST /publish es 200 en una transacción (ledger `route.publish`); congela la revisión.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import Any

from cryptography.exceptions import InvalidTag
from geoalchemy2 import Geometry
from sqlalchemy import cast, func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.optimizer.interface import (
    INCOMPATIBLE_WINDOWS,
    INSUFFICIENT_SHIFT,
    ISOLATED_STOP,
    InfeasibilityDiagnostic,
    OptimizationResult,
    Optimizer,
)
from app.adapters.optimizer.ortools_tsp import OrToolsTspOptimizer, estimated_arc_cost
from app.adapters.router.interface import Coordinate, Router
from app.core.config import get_settings
from app.core.crypto import FieldCipher
from app.core.errors import DomainError
from app.jobs.queue import JobQueue
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization
from app.modules.imports.models import Address, Patient
from app.modules.jobs.ledger import begin_idempotent_job, hash_request_payload
from app.modules.jobs.models import Job
from app.modules.planning.calendar import DEFAULT_SERVICE_MINUTES
from app.modules.planning.models import DailyRoute, MonthlyPlan
from app.modules.routing.matrix import (
    COORD_DECIMALS,
    ComputedMatrix,
    OsrmTableCache,
    assemble_table_coordinates,
    compute_matrix,
)
from app.modules.routing.metrics import build_metrics, persist_metrics, upsert_actual_metric
from app.modules.routing.models import RouteMetric, RouteRevision, RouteStop
from app.modules.routing.schemas import (
    OptimizeRouteRequest,
    OptimizeRouteResponse,
    PublishRouteRequest,
    PublishRouteResponse,
    ReorderStopsResponse,
    ReplaceStopsResponse,
    ReportStopExecutionRequest,
    RouteComparisonResponse,
    RouteDetailResponse,
    RouteDiagnosticOut,
    RouteExecutionCountsOut,
    RouteMetricsSavingsOut,
    RouteMetricsVariantOut,
    RouteStopExecutionOut,
    RouteStopOrderOut,
    RouteStopOut,
    RouteStopRefOut,
)

OPTIMIZE_JOB_TYPE = "route.optimize"
OPTIMIZE_RESOURCE_TYPE = "route"
OPTIMIZE_QUEUE = "optimization"
PUBLISH_JOB_TYPE = "route.publish"
_PUBLISHABLE_ROUTE_STATUSES = frozenset({"draft", "optimizing", "ready"})
_UNPUBLISHABLE_ROUTE_STATUSES = frozenset({"in_progress", "completed", "cancelled"})
_EXECUTABLE_ROUTE_STATUSES = frozenset({"published", "in_progress"})
_MAX_ROUTE_STOPS = 25
_INACTIVE_ROUTE_STATUSES = frozenset({"cancelled", "completed"})
CONFIRMED_GEOCODE_STATUSES = frozenset({"matched", "manual"})
_FEASIBLE_SOLVER_STATUSES = frozenset(
    {
        "ROUTING_SUCCESS",
        "ROUTING_OPTIMAL",
        "ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED",
    }
)
_SUGGESTED_ACTIONS = {
    INCOMPATIBLE_WINDOWS: (
        "widen window",
        "split route",
        "drop stop",
        "edit order",
    ),
    INSUFFICIENT_SHIFT: (
        "split route",
        "drop stop",
        "widen window",
    ),
    ISOLATED_STOP: (
        "widen window",
        "drop stop",
        "split route",
    ),
}

# OFFSET evita chocar con uq_route_stops_revision_sequence en el primer flush.
_SEQUENCE_REORDER_OFFSET = 1_000_000


class OptimizeJobError(Exception):
    """Error de dominio en el worker: se persiste en el job y no se reintenta."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _StopInput:
    patient_id: uuid.UUID
    latitude: float
    longitude: float
    service_minutes: int
    municipality: str
    postal_code: str


def enqueue_optimize(
    db: Session,
    route: DailyRoute,
    payload: OptimizeRouteRequest,
    *,
    idempotency_key: str,
    created_by: uuid.UUID,
    queue: JobQueue,
) -> OptimizeRouteResponse:
    """Crea o reutiliza el job durable y encola el worker `optimization`."""
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    try:
        stops = _load_stop_inputs(db, route)
    except OptimizeJobError as exc:
        raise DomainError(409, exc.code, str(exc)) from exc
    ledger_payload = {
        "route_id": str(route.id),
        **payload.model_dump(mode="json"),
        "stops_fingerprint": _stops_fingerprint(stops),
        "osrm_dataset_version": get_settings().osrm_dataset_version,
    }
    job = begin_idempotent_job(
        db,
        organization_id=route.organization_id,
        job_type=OPTIMIZE_JOB_TYPE,
        idempotency_key=idempotency_key,
        payload=ledger_payload,
        resource_type=OPTIMIZE_RESOURCE_TYPE,
        resource_id=route.id,
    )
    if job.result_json:
        return OptimizeRouteResponse.model_validate(job.result_json)

    queue.enqueue(
        queue=OPTIMIZE_QUEUE,
        payload={
            "job_id": str(job.id),
            "route_id": str(route.id),
            "organization_id": str(route.organization_id),
            "created_by": str(created_by),
            "request": payload.model_dump(mode="json"),
        },
    )
    response = OptimizeRouteResponse(job_id=job.id, status="queued")
    job.result_json = response.model_dump(mode="json")
    db.commit()
    db.refresh(job)
    return response


def optimize_route_job(
    db: Session,
    *,
    route_id: uuid.UUID,
    organization_id: uuid.UUID,
    created_by: uuid.UUID,
    request: OptimizeRouteRequest | dict[str, Any],
    router: Router,
    cache: OsrmTableCache,
    job_id: uuid.UUID | None = None,
    optimizer: Optimizer | None = None,
    cipher: FieldCipher | None = None,
) -> RouteRevision | None:
    """Worker de la cola `optimization`: matriz, solver, revisión draft y métricas."""
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    payload = (
        request
        if isinstance(request, OptimizeRouteRequest)
        else OptimizeRouteRequest.model_validate(request)
    )
    job = _lock_job(db, job_id, organization_id=organization_id)
    if job is not None:
        job.status = "running"
        job.progress = max(job.progress, 10)
        job.attempt = job.attempt + 1

    try:
        revision = _run_optimize(
            db,
            route_id=route_id,
            organization_id=organization_id,
            created_by=created_by,
            payload=payload,
            router=router,
            cache=cache,
            optimizer=optimizer or OrToolsTspOptimizer(),
            cipher=cipher,
        )
    except OptimizeJobError as exc:
        if job is not None:
            job.status = "failed"
            job.error_code = exc.code
        db.commit()
        return None
    except Exception:
        if job is not None:
            job.status = "failed"
            job.error_code = "OPTIMIZE_FAILED"
            db.commit()
        raise

    if job is not None:
        job.status = "succeeded"
        job.progress = 100
        job.error_code = None
    db.commit()
    db.refresh(revision)
    return revision


def get_route_detail(db: Session, route: DailyRoute) -> RouteDetailResponse:
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    revision, stops = _current_revision_with_stops(db, route)
    diagnostics = _diagnostics_from_constraints(revision.constraints_json if revision else {})
    coords = _stop_coordinates(db, stops)
    refs = _stop_external_refs(db, route.organization_id, revision, stops)
    return RouteDetailResponse(
        id=route.id,
        plan_id=route.plan_id,
        organization_id=route.organization_id,
        zone_id=route.zone_id,
        service_date=route.service_date,
        assignee_id=route.assignee_id,
        status=route.status,
        version=route.version,
        current_revision=route.current_revision,
        revision=revision.revision if revision is not None else None,
        objective=revision.objective if revision is not None else None,
        solver_status=revision.solver_status if revision is not None else None,
        diagnostics=diagnostics,
        stops=[
            RouteStopOut(
                id=stop.id,
                patient_id=stop.patient_id,
                sequence=stop.sequence,
                status=stop.status,
                version=stop.version,
                completed_at=stop.completed_at,
                failure_reason=stop.failure_reason,
                window_start=stop.window_start.isoformat(timespec="minutes")
                if stop.window_start is not None
                else None,
                window_end=stop.window_end.isoformat(timespec="minutes")
                if stop.window_end is not None
                else None,
                lat=coords.get(stop.id, (None, None))[0],
                lon=coords.get(stop.id, (None, None))[1],
                external_ref=refs.get(stop.patient_id),
            )
            for stop in stops
        ],
    )


def reorder_stops(
    db: Session,
    route: DailyRoute,
    *,
    revision_id: uuid.UUID,
    ordered_stop_ids: list[uuid.UUID],
    expected_version: int,
) -> ReorderStopsResponse:
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    locked = (
        db.query(DailyRoute)
        .filter(DailyRoute.id == route.id, DailyRoute.organization_id == route.organization_id)
        .with_for_update()
        .one_or_none()
    )
    if locked is None:
        raise DomainError(404, "ROUTE_NOT_FOUND", "Ruta no encontrada")
    if locked.version != expected_version:
        raise DomainError(409, "ROUTE_VERSION_CONFLICT", "La ruta ha sido modificada")

    revision = (
        db.query(RouteRevision)
        .filter(
            RouteRevision.id == revision_id,
            RouteRevision.route_id == locked.id,
            RouteRevision.organization_id == locked.organization_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if revision is None:
        raise DomainError(404, "REVISION_NOT_FOUND", "Revisión no encontrada")
    if revision.status != "draft":
        raise DomainError(409, "REVISION_PUBLISHED", "Solo se reordenan revisiones en borrador")

    stops = (
        db.query(RouteStop)
        .filter(
            RouteStop.revision_id == revision.id,
            RouteStop.organization_id == locked.organization_id,
        )
        .with_for_update()
        .all()
    )
    _require_permutation(ordered_stop_ids, {stop.id for stop in stops})
    by_id = {stop.id: stop for stop in stops}
    ordered = [by_id[stop_id] for stop_id in ordered_stop_ids]

    for index, stop in enumerate(ordered, start=1):
        stop.sequence = _SEQUENCE_REORDER_OFFSET + index
    db.flush()
    for index, stop in enumerate(ordered, start=1):
        stop.sequence = index
        stop.version = stop.version + 1

    metrics = (
        db.query(RouteMetric)
        .filter(
            RouteMetric.revision_id == revision.id,
            RouteMetric.organization_id == locked.organization_id,
        )
        .with_for_update()
        .all()
    )
    for metric in metrics:
        payload = dict(metric.calculation_json or {})
        payload["stale"] = True
        metric.calculation_json = payload

    locked.version = expected_version + 1
    db.commit()
    db.refresh(locked)
    for stop in ordered:
        db.refresh(stop)

    return ReorderStopsResponse(
        route_id=locked.id,
        revision_id=revision.id,
        version=locked.version,
        stops=[
            RouteStopOrderOut(
                id=stop.id,
                patient_id=stop.patient_id,
                sequence=stop.sequence,
                version=stop.version,
            )
            for stop in ordered
        ],
        metrics_pending=True,
    )


def replace_stops(
    db: Session,
    route: DailyRoute,
    *,
    patient_ids: list[uuid.UUID],
    expected_version: int,
    created_by: uuid.UUID,
) -> ReplaceStopsResponse:
    """Sustituye paradas de la revisión draft (añadir/quitar/refrescar direcciones).

    Una revisión published no se muta: se abre una draft nueva (3.BE.11).
    """
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    if len(patient_ids) > _MAX_ROUTE_STOPS:
        raise DomainError(422, "ROUTE_TOO_MANY_STOPS", "La ruta admite como máximo 25 paradas")
    if len(patient_ids) != len(set(patient_ids)):
        raise DomainError(422, "DUPLICATE_STOP_PATIENT", "patient_ids no puede repetir pacientes")

    locked = (
        db.query(DailyRoute)
        .filter(DailyRoute.id == route.id, DailyRoute.organization_id == route.organization_id)
        .with_for_update()
        .one_or_none()
    )
    if locked is None:
        raise DomainError(404, "ROUTE_NOT_FOUND", "Ruta no encontrada")
    if locked.version != expected_version:
        raise DomainError(409, "ROUTE_VERSION_CONFLICT", "La ruta ha sido modificada")
    if locked.status in _UNPUBLISHABLE_ROUTE_STATUSES:
        raise DomainError(409, "ROUTE_NOT_EDITABLE", "La ruta no admite cambio de paradas")

    _assert_patients_in_organization(db, locked.organization_id, patient_ids)
    _assert_patients_not_on_other_routes(db, locked, patient_ids)
    resolved = _confirmed_stop_locations(db, locked.organization_id, patient_ids)

    current = None
    if locked.current_revision is not None:
        current = (
            db.query(RouteRevision)
            .filter(
                RouteRevision.id == locked.current_revision,
                RouteRevision.organization_id == locked.organization_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if current is None:
            raise DomainError(404, "REVISION_NOT_FOUND", "Revisión no encontrada")

    previous_minutes = _service_minutes_by_patient(db, current) if current is not None else {}
    if current is None or current.status == "published":
        revision = _open_draft_revision(db, locked, previous=current, created_by=created_by)
        locked.current_revision = revision.id
        if locked.status == "published":
            locked.status = "draft"
    else:
        if current.status != "draft":
            raise DomainError(409, "REVISION_NOT_DRAFT", "Solo se editan revisiones en borrador")
        revision = current
        _clear_revision_stops(db, revision)
    stops: list[RouteStop] = []
    for index, patient_id in enumerate(patient_ids, start=1):
        _, lat, lon = resolved[patient_id]
        stops.append(
            RouteStop(
                revision_id=revision.id,
                organization_id=locked.organization_id,
                patient_id=patient_id,
                location=_point_ewkt(lon, lat),
                sequence=index,
                service_minutes=previous_minutes.get(patient_id, DEFAULT_SERVICE_MINUTES),
            )
        )
    db.add_all(stops)
    _mark_metrics_stale(db, revision)
    revision.solver_status = "pending"
    locked.version = expected_version + 1
    db.commit()
    db.refresh(locked)
    for stop in stops:
        db.refresh(stop)

    return ReplaceStopsResponse(
        route_id=locked.id,
        revision_id=revision.id,
        version=locked.version,
        stops=[
            RouteStopOrderOut(
                id=stop.id,
                patient_id=stop.patient_id,
                sequence=stop.sequence,
                version=stop.version,
            )
            for stop in stops
        ],
        metrics_pending=True,
    )


def get_comparison(db: Session, route: DailyRoute) -> RouteComparisonResponse:
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    if route.current_revision is None:
        raise DomainError(
            409,
            "METRICS_UNAVAILABLE",
            "La revisión actual no tiene métricas original y optimizada",
        )

    metrics = (
        db.query(RouteMetric)
        .filter(
            RouteMetric.revision_id == route.current_revision,
            RouteMetric.organization_id == route.organization_id,
            RouteMetric.variant.in_(("original", "optimized", "actual")),
        )
        .all()
    )
    by_variant = {metric.variant: metric for metric in metrics}
    original = by_variant.get("original")
    optimized = by_variant.get("optimized")
    actual = by_variant.get("actual")
    if original is None or optimized is None:
        raise DomainError(
            409,
            "METRICS_UNAVAILABLE",
            "La revisión actual no tiene métricas original y optimizada",
        )
    if _metric_is_stale(original) or _metric_is_stale(optimized):
        raise DomainError(
            409,
            "METRICS_STALE",
            "Las métricas están pendientes de recálculo",
        )

    saved_distance = original.distance_m - optimized.distance_m
    saved_travel = original.travel_seconds - optimized.travel_seconds
    saved_cost = round(original.estimated_cost - optimized.estimated_cost, 4)
    if original.travel_seconds == 0:
        travel_pct = 0.0
    else:
        travel_pct = round(saved_travel / original.travel_seconds * 100, 2)
    revision = db.get(RouteRevision, route.current_revision)
    _, stops = _current_revision_with_stops(db, route)
    original_stops, optimized_stops = _comparison_stop_orders(original, optimized, stops)
    return RouteComparisonResponse(
        original=_variant_out(original),
        optimized=_variant_out(optimized),
        savings=RouteMetricsSavingsOut(
            distance_m=saved_distance,
            travel_seconds=saved_travel,
            estimated_cost=saved_cost,
            travel_seconds_pct=travel_pct,
        ),
        solver_status=revision.solver_status if revision is not None else None,
        diagnostics=_diagnostics_from_constraints(
            revision.constraints_json if revision is not None else {}
        ),
        revision_id=revision.id if revision is not None else None,
        original_stops=original_stops,
        optimized_stops=optimized_stops,
        actual=_variant_out(actual) if actual is not None else None,
        deviation=_execution_deviation(optimized, actual) if actual is not None else None,
        execution_counts=_execution_counts(actual) if actual is not None else None,
    )


def publish_route(
    db: Session,
    route: DailyRoute,
    payload: PublishRouteRequest,
    *,
    expected_version: int,
    idempotency_key: str,
    router: Router,
    cipher: FieldCipher,
) -> PublishRouteResponse:
    """Congela la revisión actual: snapshot cifrado, geometría OSRM y status published.

    HTTP 200 en una transacción (mismo criterio que publicar plan). Ledger `route.publish`.
    """
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    ledger_payload = {
        "route_id": str(route.id),
        **payload.model_dump(mode="json"),
    }
    job = begin_idempotent_job(
        db,
        organization_id=route.organization_id,
        job_type=PUBLISH_JOB_TYPE,
        idempotency_key=idempotency_key,
        payload=ledger_payload,
        resource_type=OPTIMIZE_RESOURCE_TYPE,
        resource_id=route.id,
    )
    if job.result_json:
        return PublishRouteResponse.model_validate(job.result_json)

    published = _run_publish(
        db,
        route_id=route.id,
        organization_id=route.organization_id,
        expected_version=expected_version,
        revision_id=payload.revision_id,
        router=router,
        cipher=cipher,
    )
    job.status = "succeeded"
    job.progress = 100
    job.error_code = None
    job.result_json = published.model_dump(mode="json")
    db.commit()
    return published


def _run_publish(
    db: Session,
    *,
    route_id: uuid.UUID,
    organization_id: uuid.UUID,
    expected_version: int,
    revision_id: uuid.UUID | None,
    router: Router,
    cipher: FieldCipher,
) -> PublishRouteResponse:
    locked = (
        db.query(DailyRoute)
        .filter(DailyRoute.id == route_id, DailyRoute.organization_id == organization_id)
        .with_for_update()
        .one_or_none()
    )
    if locked is None:
        raise DomainError(404, "ROUTE_NOT_FOUND", "Ruta no encontrada")
    if locked.version != expected_version:
        raise DomainError(409, "ROUTE_VERSION_CONFLICT", "La ruta ha sido modificada")
    if locked.status in _UNPUBLISHABLE_ROUTE_STATUSES:
        raise DomainError(409, "ROUTE_NOT_PUBLISHABLE", "La ruta no se puede publicar en este estado")
    if locked.status == "published":
        raise DomainError(409, "ROUTE_PUBLISHED", "La ruta ya está publicada")
    if locked.status not in _PUBLISHABLE_ROUTE_STATUSES:
        raise DomainError(409, "ROUTE_NOT_PUBLISHABLE", "La ruta no se puede publicar en este estado")

    target_id = revision_id or locked.current_revision
    if target_id is None:
        raise DomainError(409, "REVISION_NOT_FOUND", "La ruta no tiene revisión para publicar")
    if locked.current_revision is not None and target_id != locked.current_revision:
        raise DomainError(409, "REVISION_NOT_CURRENT", "Solo se publica la revisión actual")

    revision = (
        db.query(RouteRevision)
        .filter(
            RouteRevision.id == target_id,
            RouteRevision.route_id == locked.id,
            RouteRevision.organization_id == locked.organization_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if revision is None:
        raise DomainError(404, "REVISION_NOT_FOUND", "Revisión no encontrada")
    if revision.status == "published":
        raise DomainError(409, "REVISION_PUBLISHED", "La revisión ya está publicada")
    if revision.status != "draft":
        raise DomainError(409, "REVISION_NOT_DRAFT", "Solo se publica una revisión en borrador")
    if revision.solver_status != "feasible":
        raise DomainError(409, "ROUTE_NOT_FEASIBLE", "Solo se publica una revisión factible")
    if not isinstance(revision.origin, dict) or not isinstance(revision.destination, dict):
        raise DomainError(422, "ROUTE_ORIGIN_MISSING", "La revisión no tiene origen/destino")

    metrics = (
        db.query(RouteMetric)
        .filter(
            RouteMetric.revision_id == revision.id,
            RouteMetric.organization_id == locked.organization_id,
            RouteMetric.variant.in_(("original", "optimized")),
        )
        .with_for_update()
        .all()
    )
    by_variant = {metric.variant: metric for metric in metrics}
    original = by_variant.get("original")
    optimized = by_variant.get("optimized")
    if original is None or optimized is None:
        raise DomainError(
            409,
            "METRICS_UNAVAILABLE",
            "La revisión actual no tiene métricas original y optimizada",
        )
    if _metric_is_stale(original) or _metric_is_stale(optimized):
        raise DomainError(409, "METRICS_STALE", "Las métricas están pendientes de recálculo")

    (
        db.query(RouteStop)
        .filter(
            RouteStop.revision_id == revision.id,
            RouteStop.organization_id == locked.organization_id,
        )
        .with_for_update()
        .all()
    )

    stop_lat = func.ST_Y(cast(RouteStop.location, Geometry))
    stop_lon = func.ST_X(cast(RouteStop.location, Geometry))
    rows = (
        db.query(RouteStop, Address, Patient, stop_lat, stop_lon)
        .outerjoin(
            Address,
            (Address.patient_id == RouteStop.patient_id)
            & (Address.organization_id == RouteStop.organization_id)
            & Address.is_active.is_(True),
        )
        .outerjoin(Patient, Patient.id == RouteStop.patient_id)
        .filter(
            RouteStop.revision_id == revision.id,
            RouteStop.organization_id == locked.organization_id,
        )
        .order_by(RouteStop.sequence)
        .all()
    )
    if not rows:
        raise DomainError(409, "NO_STOPS_TO_PUBLISH", "La revisión no tiene paradas")

    stop_coords: list[Coordinate] = []
    for stop, _address, _patient, lat, lon in rows:
        if lat is None or lon is None:
            raise DomainError(422, "STOP_LOCATION_MISSING", "Una parada no tiene coordenadas")
        stop_coords.append(Coordinate(latitude=float(lat), longitude=float(lon)))

    origin = _coordinate_from_payload(revision.origin)
    destination = _coordinate_from_payload(revision.destination)
    coordinates = assemble_table_coordinates(origin, stop_coords, destination)
    geometry = _geometry_from_router(router, coordinates)
    dataset_version = revision.osrm_dataset_version or get_settings().osrm_dataset_version
    published_at = datetime.now(UTC)

    for stop, address, _patient, lat, lon in rows:
        stop.address_snapshot_ciphertext = _publish_address_snapshot(
            cipher,
            stop,
            address,
            latitude=float(lat),
            longitude=float(lon),
        )

    snapshot = {
        "geometry": geometry,
        "osrm_dataset_version": dataset_version,
        "osm_dataset_version": dataset_version,
        "origin": revision.origin,
        "destination": revision.destination,
        "objective": revision.objective,
        "order": [
            {
                "stop_id": str(stop.id),
                "patient_id": str(stop.patient_id),
                "external_ref": patient.external_ref if patient is not None else "",
                "sequence": stop.sequence,
                "lat": float(lat),
                "lon": float(lon),
            }
            for stop, _address, patient, lat, lon in rows
        ],
        "metrics": {
            "original": _metric_snapshot(original),
            "optimized": _metric_snapshot(optimized),
        },
    }
    constraints = dict(revision.constraints_json or {})
    constraints["snapshot"] = snapshot
    revision.constraints_json = constraints
    flag_modified(revision, "constraints_json")
    revision.osrm_dataset_version = dataset_version
    revision.status = "published"
    revision.published_at = published_at
    locked.status = "published"
    locked.version = expected_version + 1
    db.flush()

    return PublishRouteResponse(
        route_id=locked.id,
        revision_id=revision.id,
        revision=revision.revision,
        status=locked.status,
        revision_status=revision.status,
        version=locked.version,
        published_at=published_at,
        osrm_dataset_version=dataset_version,
    )


def report_stop_execution(
    db: Session,
    route: DailyRoute,
    *,
    stop_id: uuid.UUID,
    payload: ReportStopExecutionRequest,
    expected_version: int,
) -> RouteStopExecutionOut:
    """Reporta ejecución de una parada. If-Match = route_stops.version (4.BE.2).

    No muta snapshot, geometría ni orden de la revisión publicada.
    """
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    locked = (
        db.query(DailyRoute)
        .filter(DailyRoute.id == route.id, DailyRoute.organization_id == route.organization_id)
        .with_for_update()
        .one_or_none()
    )
    if locked is None:
        raise DomainError(404, "ROUTE_NOT_FOUND", "Ruta no encontrada")
    if locked.status not in _EXECUTABLE_ROUTE_STATUSES:
        raise DomainError(
            409, "ROUTE_NOT_EXECUTABLE", "Solo se reporta ejecución en una ruta publicada"
        )

    stop = (
        db.query(RouteStop)
        .filter(
            RouteStop.id == stop_id,
            RouteStop.organization_id == locked.organization_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if stop is None:
        raise DomainError(404, "STOP_NOT_FOUND", "Parada no encontrada")

    revision = (
        db.query(RouteRevision)
        .filter(
            RouteRevision.id == stop.revision_id,
            RouteRevision.organization_id == locked.organization_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if revision is None or revision.route_id != locked.id:
        raise DomainError(404, "STOP_NOT_FOUND", "Parada no encontrada")
    if revision.status != "published":
        raise DomainError(
            409,
            "REVISION_NOT_PUBLISHED",
            "Solo se reporta ejecución sobre una revisión publicada",
        )

    if stop.version != expected_version:
        raise DomainError(
            409,
            "STOP_VERSION_CONFLICT",
            "La parada ha sido modificada",
            errors=[_stop_latest_state(stop, locked.status)],
        )

    completed_at = _as_utc(payload.completed_at)
    if _same_execution(stop, payload.status, completed_at, payload.failure_reason):
        return _execution_out(stop, locked)

    if completed_at is None:
        completed_at = datetime.now(UTC)
    stop.status = payload.status
    stop.completed_at = completed_at
    stop.failure_reason = payload.failure_reason
    stop.version = expected_version + 1
    db.flush()

    pending = (
        db.query(RouteStop.id)
        .filter(
            RouteStop.revision_id == revision.id,
            RouteStop.organization_id == locked.organization_id,
            RouteStop.status == "pending",
        )
        .count()
    )
    if pending == 0:
        locked.status = "completed"
    elif locked.status == "published":
        locked.status = "in_progress"

    reported_stops = (
        db.query(RouteStop)
        .filter(
            RouteStop.revision_id == revision.id,
            RouteStop.organization_id == locked.organization_id,
        )
        .order_by(RouteStop.sequence)
        .all()
    )
    planned = (
        db.query(RouteMetric)
        .filter(
            RouteMetric.revision_id == revision.id,
            RouteMetric.organization_id == locked.organization_id,
            RouteMetric.variant == "optimized",
        )
        .one_or_none()
    )
    upsert_actual_metric(
        db,
        revision_id=revision.id,
        organization_id=locked.organization_id,
        stops=reported_stops,
        planned=planned,
    )

    db.commit()
    db.refresh(locked)
    db.refresh(stop)
    return _execution_out(stop, locked)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _same_execution(
    stop: RouteStop,
    status: str,
    completed_at: datetime | None,
    failure_reason: str | None,
) -> bool:
    if stop.status != status:
        return False
    if (stop.failure_reason or None) != (failure_reason or None):
        return False
    if completed_at is None:
        return True
    existing = _as_utc(stop.completed_at)
    if existing is None:
        return False
    return existing == completed_at


def _iso_utc(value: datetime | None) -> str | None:
    aware = _as_utc(value)
    if aware is None:
        return None
    return aware.isoformat().replace("+00:00", "Z")


def _stop_latest_state(stop: RouteStop, route_status: str) -> dict[str, Any]:
    return {
        "field": "stop",
        "code": "LATEST_STATE",
        "message": "Estado más reciente de la parada",
        "id": str(stop.id),
        "status": stop.status,
        "version": stop.version,
        "completed_at": _iso_utc(stop.completed_at),
        "failure_reason": stop.failure_reason,
        "route_status": route_status,
    }


def _execution_out(stop: RouteStop, route: DailyRoute) -> RouteStopExecutionOut:
    return RouteStopExecutionOut(
        id=stop.id,
        route_id=route.id,
        revision_id=stop.revision_id,
        patient_id=stop.patient_id,
        sequence=stop.sequence,
        status=stop.status,
        completed_at=stop.completed_at,
        failure_reason=stop.failure_reason,
        version=stop.version,
        route_status=route.status,
    )


def _variant_out(metric: RouteMetric) -> RouteMetricsVariantOut:
    return RouteMetricsVariantOut(
        distance_m=metric.distance_m,
        travel_seconds=metric.travel_seconds,
        service_seconds=metric.service_seconds,
        estimated_cost=metric.estimated_cost,
    )


def _execution_deviation(planned: RouteMetric, actual: RouteMetric) -> RouteMetricsSavingsOut:
    comparable = (actual.calculation_json or {}).get("distance_source") != "unavailable"
    distance_delta = actual.distance_m - planned.distance_m if comparable else 0
    travel_delta = actual.travel_seconds - planned.travel_seconds
    cost_delta = round(actual.estimated_cost - planned.estimated_cost, 4)
    if planned.travel_seconds == 0:
        pct = 0.0
    else:
        pct = round(travel_delta / planned.travel_seconds * 100, 2)
    return RouteMetricsSavingsOut(
        distance_m=distance_delta,
        travel_seconds=travel_delta,
        estimated_cost=cost_delta,
        travel_seconds_pct=pct,
    )


def _execution_counts(actual: RouteMetric) -> RouteExecutionCountsOut:
    payload = actual.calculation_json or {}
    completed = int(payload.get("completed") or 0)
    failed = int(payload.get("failed") or 0)
    skipped = int(payload.get("skipped") or 0)
    pending = int(payload.get("pending") or 0)
    return RouteExecutionCountsOut(
        planned=completed + failed + skipped + pending,
        completed=completed,
        failed=failed,
        skipped=skipped,
        pending=pending,
    )


def _tour_nodes(order: list[Any]) -> list[int]:
    nodes = [int(item) for item in order]
    if len(nodes) <= 2:
        return []
    return nodes[1:-1]


def _comparison_stop_orders(
    original: RouteMetric,
    optimized: RouteMetric,
    stops: list[RouteStop],
) -> tuple[list[RouteStopRefOut], list[RouteStopRefOut]]:
    """Reconstruye orden original vs optimizado (índices de matriz 1..N, sin depósito)."""
    optimized_ids = [stop.patient_id for stop in stops]
    optimized_refs = [
        RouteStopRefOut(patient_id=stop.patient_id, sequence=stop.sequence) for stop in stops
    ]
    opt_nodes = _tour_nodes(list((optimized.calculation_json or {}).get("order") or []))
    orig_nodes = _tour_nodes(list((original.calculation_json or {}).get("order") or []))
    if len(opt_nodes) != len(optimized_ids) or not orig_nodes:
        return [], optimized_refs
    node_to_patient = dict(zip(opt_nodes, optimized_ids, strict=True))
    original_ids = [node_to_patient[node] for node in orig_nodes if node in node_to_patient]
    if len(original_ids) != len(optimized_ids):
        return [], optimized_refs
    original_refs = [
        RouteStopRefOut(patient_id=patient_id, sequence=index)
        for index, patient_id in enumerate(original_ids, start=1)
    ]
    return original_refs, optimized_refs


def _metric_is_stale(metric: RouteMetric) -> bool:
    return (metric.calculation_json or {}).get("stale") is True


def _require_permutation(ordered_ids: list[uuid.UUID], existing_ids: set[uuid.UUID]) -> None:
    if len(ordered_ids) != len(existing_ids) or len(set(ordered_ids)) != len(ordered_ids):
        raise DomainError(
            422,
            "STOP_ORDER_NOT_PERMUTATION",
            "ordered_stop_ids debe ser una permutación de las paradas de la revisión",
        )
    if set(ordered_ids) != existing_ids:
        raise DomainError(
            422,
            "STOP_ORDER_NOT_PERMUTATION",
            "ordered_stop_ids debe ser una permutación de las paradas de la revisión",
        )


def _run_optimize(
    db: Session,
    *,
    route_id: uuid.UUID,
    organization_id: uuid.UUID,
    created_by: uuid.UUID,
    payload: OptimizeRouteRequest,
    router: Router,
    cache: OsrmTableCache,
    optimizer: Optimizer,
    cipher: FieldCipher | None,
) -> RouteRevision:
    locked = (
        db.query(DailyRoute)
        .filter(DailyRoute.id == route_id, DailyRoute.organization_id == organization_id)
        .with_for_update()
        .one_or_none()
    )
    if locked is None:
        raise OptimizeJobError("ROUTE_NOT_FOUND", "Ruta no encontrada")

    stops = _load_stop_inputs(db, locked)
    origin = Coordinate(latitude=payload.origin.lat, longitude=payload.origin.lon)
    dest_in = payload.destination or payload.origin
    destination = Coordinate(latitude=dest_in.lat, longitude=dest_in.lon)
    stop_coords = [Coordinate(latitude=item.latitude, longitude=item.longitude) for item in stops]
    coordinates = assemble_table_coordinates(origin, stop_coords, destination)
    matrix = asyncio.run(compute_matrix(router, cache, coordinates))

    n_stops = len(stops)
    solver_size = n_stops + 1
    dest_index = n_stops + 1
    durations = [row[:solver_size] for row in matrix.durations_seconds[:solver_size]]
    distances = [row[:solver_size] for row in matrix.distances_meters[:solver_size]]
    org = db.get(Organization, organization_id)
    cost_per_km = payload.cost_per_km or (org.cost_per_km if org is not None else 0.0)
    cost_per_hour = payload.cost_per_hour or (org.cost_per_hour if org is not None else 0.0)
    result = optimizer.solve(
        durations_seconds=durations,
        distances_meters=distances,
        time_windows=_solver_windows(payload, stops),
        service_times_seconds=_solver_service_times(payload, stops),
        vehicle_count=payload.vehicle_count,
        vehicle_time_capacity_seconds=payload.vehicle_time_capacity_seconds,
        objective=payload.objective,
        cost_per_km=cost_per_km,
        cost_per_hour=cost_per_hour,
    )
    solver_status = _revision_solver_status(result)
    feasible = solver_status == "feasible" and bool(result.order)
    ordered_stops = _stops_in_solver_order(stops, result) if feasible else list(stops)
    diagnostics = [_diagnostic_out(item) for item in result.diagnostics]
    next_number = _next_revision_number(db, locked)
    revision = RouteRevision(
        organization_id=organization_id,
        route_id=locked.id,
        revision=next_number,
        status="draft",
        objective=payload.objective,
        origin={"lat": payload.origin.lat, "lon": payload.origin.lon},
        destination={"lat": dest_in.lat, "lon": dest_in.lon},
        solver_status=solver_status,
        constraints_json=_constraints_payload(payload, result, diagnostics),
        osrm_dataset_version=matrix.dataset_version,
        created_by=created_by,
    )
    db.add(revision)
    db.flush()
    db.add_all(
        [
            RouteStop(
                revision_id=revision.id,
                organization_id=organization_id,
                patient_id=item.patient_id,
                address_snapshot_ciphertext=_address_snapshot(cipher, item),
                location=_point_ewkt(item.longitude, item.latitude),
                sequence=index,
                service_minutes=item.service_minutes,
            )
            for index, item in enumerate(ordered_stops, start=1)
        ]
    )
    if feasible:
        original_order = list(range(solver_size)) + [dest_index]
        optimized_order = list(result.order) + [dest_index]
        rows = build_metrics(
            revision.id,
            matrix,
            original_order,
            optimized_order,
            organization_id=organization_id,
            service_minutes=[item.service_minutes for item in stops],
            estimated_cost_original=_cost_for_order(
                matrix, original_order, cost_per_km, cost_per_hour
            ),
            estimated_cost_optimized=_cost_for_order(
                matrix, optimized_order, cost_per_km, cost_per_hour
            ),
        )
        for row in rows:
            calc = dict(row["calculation_json"])
            calc["stale"] = False
            row["calculation_json"] = calc
        persist_metrics(db, rows)

    locked.current_revision = revision.id
    locked.version = locked.version + 1
    if locked.status == "published":
        locked.status = "ready" if feasible else "draft"
    db.flush()
    return revision


def _load_stop_inputs(db: Session, route: DailyRoute) -> list[_StopInput]:
    if route.current_revision is not None:
        from_revision = _stops_from_revision(db, route)
        if from_revision:
            return from_revision
    from_plan = _stops_from_plan_assignments(db, route)
    if from_plan:
        return from_plan
    raise OptimizeJobError("NO_STOPS_TO_OPTIMIZE", "La ruta no tiene paradas para optimizar")


def _stops_from_revision(db: Session, route: DailyRoute) -> list[_StopInput]:
    stop_lat = func.ST_Y(cast(RouteStop.location, Geometry))
    stop_lon = func.ST_X(cast(RouteStop.location, Geometry))
    addr_lat = func.ST_Y(cast(Address.location, Geometry))
    addr_lon = func.ST_X(cast(Address.location, Geometry))
    rows = (
        db.query(RouteStop, Address, stop_lat, stop_lon, addr_lat, addr_lon)
        .outerjoin(
            Address,
            (Address.patient_id == RouteStop.patient_id)
            & (Address.organization_id == RouteStop.organization_id)
            & Address.is_active.is_(True),
        )
        .filter(
            RouteStop.revision_id == route.current_revision,
            RouteStop.organization_id == route.organization_id,
        )
        .order_by(RouteStop.sequence)
        .all()
    )
    stops: list[_StopInput] = []
    for stop, address, lat, lon, fallback_lat, fallback_lon in rows:
        resolved_lat = lat if lat is not None else fallback_lat
        resolved_lon = lon if lon is not None else fallback_lon
        if resolved_lat is None or resolved_lon is None:
            raise OptimizeJobError("STOP_LOCATION_MISSING", "Una parada no tiene coordenadas")
        municipality = address.municipality if address is not None else ""
        postal_code = address.postal_code if address is not None else ""
        stops.append(
            _StopInput(
                patient_id=stop.patient_id,
                latitude=float(resolved_lat),
                longitude=float(resolved_lon),
                service_minutes=stop.service_minutes or DEFAULT_SERVICE_MINUTES,
                municipality=municipality,
                postal_code=postal_code,
            )
        )
    return stops


def _stops_from_plan_assignments(db: Session, route: DailyRoute) -> list[_StopInput]:
    plan = db.get(MonthlyPlan, route.plan_id)
    if plan is None or plan.organization_id != route.organization_id:
        raise OptimizeJobError("PLAN_NOT_FOUND", "Plan de la ruta no encontrado")
    patient_ids = _assignment_patient_ids(plan, route.service_date, route.zone_id)
    if not patient_ids:
        return []
    addr_lat = func.ST_Y(cast(Address.location, Geometry))
    addr_lon = func.ST_X(cast(Address.location, Geometry))
    rows = (
        db.query(Patient.id, Address.municipality, Address.postal_code, addr_lat, addr_lon)
        .join(
            Address,
            (Address.patient_id == Patient.id)
            & (Address.organization_id == Patient.organization_id)
            & Address.is_active.is_(True),
        )
        .filter(
            Patient.organization_id == route.organization_id,
            Patient.id.in_(patient_ids),
            Address.geocode_status.in_(CONFIRMED_GEOCODE_STATUSES),
            Address.location.isnot(None),
        )
        .all()
    )
    by_id = {
        patient_id: _StopInput(
            patient_id=patient_id,
            latitude=float(lat),
            longitude=float(lon),
            service_minutes=DEFAULT_SERVICE_MINUTES,
            municipality=municipality or "",
            postal_code=postal_code or "",
        )
        for patient_id, municipality, postal_code, lat, lon in rows
        if lat is not None and lon is not None
    }
    ordered = [by_id[patient_id] for patient_id in patient_ids if patient_id in by_id]
    if len(ordered) != len(patient_ids):
        raise OptimizeJobError(
            "STOP_LOCATION_MISSING",
            "Faltan coordenadas confirmadas para una parada de la ruta",
        )
    return ordered


def _assignment_patient_ids(
    plan: MonthlyPlan, service_date: date, zone_id: uuid.UUID
) -> list[uuid.UUID]:
    stored = (plan.result_json or {}).get("assignments") or []
    matched: list[uuid.UUID] = []
    for item in stored:
        if date.fromisoformat(str(item["date"])) != service_date:
            continue
        if uuid.UUID(str(item["zone_id"])) != zone_id:
            continue
        matched.append(uuid.UUID(str(item["patient_id"])))
    return matched


def _solver_windows(
    payload: OptimizeRouteRequest, stops: list[_StopInput]
) -> list[tuple[float, float] | None] | None:
    if not payload.windows:
        return None
    by_patient = {item.patient_id: item for item in payload.windows}
    windows: list[tuple[float, float] | None] = [None]
    for stop in stops:
        window = by_patient.get(stop.patient_id)
        if window is None:
            windows.append(None)
        else:
            windows.append((window.start_seconds, window.end_seconds))
    return windows


def _solver_service_times(payload: OptimizeRouteRequest, stops: list[_StopInput]) -> list[float]:
    services = [0.0]
    for stop in stops:
        if payload.service_minutes is not None:
            minutes = payload.service_minutes
        elif stop.service_minutes > 0:
            minutes = stop.service_minutes
        else:
            minutes = DEFAULT_SERVICE_MINUTES
        services.append(float(minutes) * 60.0)
    return services


def _stops_in_solver_order(stops: list[_StopInput], result: OptimizationResult) -> list[_StopInput]:
    ordered: list[_StopInput] = []
    seen: set[int] = set()
    for index in result.order:
        if index == 0 or index in seen or index > len(stops):
            continue
        seen.add(index)
        ordered.append(stops[index - 1])
    for offset, stop in enumerate(stops, start=1):
        if offset not in seen:
            ordered.append(stop)
    return ordered


def _revision_solver_status(result: OptimizationResult) -> str:
    raw = result.solver_status
    if not result.order:
        if "TIMEOUT" in raw:
            return "timeout"
        if (
            raw in {"ROUTING_FAIL", "ROUTING_INVALID", "ROUTING_NOT_SOLVED"}
            and not result.diagnostics
        ):
            return "failed"
        return "infeasible"
    if raw in _FEASIBLE_SOLVER_STATUSES or "SUCCESS" in raw or "OPTIMAL" in raw:
        return "feasible"
    if "TIMEOUT" in raw:
        return "timeout"
    if raw == "ROUTING_INFEASIBLE":
        return "infeasible"
    return "failed"


def _constraints_payload(
    payload: OptimizeRouteRequest,
    result: OptimizationResult,
    diagnostics: list[RouteDiagnosticOut],
) -> dict[str, Any]:
    return {
        "vehicle_count": payload.vehicle_count,
        "vehicle_time_capacity_seconds": payload.vehicle_time_capacity_seconds,
        "windows": [item.model_dump(mode="json") for item in payload.windows or []],
        "solver_status_raw": result.solver_status,
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
    }


def _diagnostic_out(item: InfeasibilityDiagnostic) -> RouteDiagnosticOut:
    fallback = _SUGGESTED_ACTIONS[INCOMPATIBLE_WINDOWS]
    return RouteDiagnosticOut(
        code=item.code,
        node_indices=list(item.node_indices),
        detail=item.detail,
        suggested_actions=list(_SUGGESTED_ACTIONS.get(item.code, fallback)),
    )


def _diagnostics_from_constraints(constraints: dict | None) -> list[RouteDiagnosticOut]:
    raw = (constraints or {}).get("diagnostics") or []
    return [RouteDiagnosticOut.model_validate(item) for item in raw]


def _stops_fingerprint(stops: list[_StopInput]) -> str:
    rows = sorted(
        (
            {
                "patient_id": str(stop.patient_id),
                "lat": round(stop.latitude, COORD_DECIMALS),
                "lon": round(stop.longitude, COORD_DECIMALS),
                "service_minutes": stop.service_minutes,
            }
            for stop in stops
        ),
        key=lambda item: item["patient_id"],
    )
    return hash_request_payload(rows)


def _assert_patients_in_organization(
    db: Session, organization_id: uuid.UUID, patient_ids: list[uuid.UUID]
) -> None:
    found = {
        row[0]
        for row in db.query(Patient.id)
        .filter(Patient.organization_id == organization_id, Patient.id.in_(patient_ids))
        .all()
    }
    if found != set(patient_ids):
        raise DomainError(404, "PATIENT_NOT_FOUND", "Paciente no encontrado")


def _assert_patients_not_on_other_routes(
    db: Session, route: DailyRoute, patient_ids: list[uuid.UUID]
) -> None:
    assigned = (
        db.query(RouteStop.patient_id)
        .join(DailyRoute, DailyRoute.current_revision == RouteStop.revision_id)
        .filter(
            DailyRoute.organization_id == route.organization_id,
            DailyRoute.service_date == route.service_date,
            DailyRoute.id != route.id,
            DailyRoute.status.notin_(tuple(_INACTIVE_ROUTE_STATUSES)),
            RouteStop.patient_id.in_(patient_ids),
        )
        .all()
    )
    if assigned:
        raise DomainError(
            409,
            "STOP_ALREADY_ASSIGNED",
            "Una parada ya pertenece a otra ruta activa en esa fecha",
        )


def _confirmed_stop_locations(
    db: Session, organization_id: uuid.UUID, patient_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[Address, float, float]]:
    addr_lat = func.ST_Y(cast(Address.location, Geometry))
    addr_lon = func.ST_X(cast(Address.location, Geometry))
    rows = (
        db.query(Address, addr_lat, addr_lon)
        .filter(
            Address.organization_id == organization_id,
            Address.patient_id.in_(patient_ids),
            Address.is_active.is_(True),
            Address.geocode_status.in_(CONFIRMED_GEOCODE_STATUSES),
            Address.location.isnot(None),
        )
        .all()
    )
    by_patient: dict[uuid.UUID, tuple[Address, float, float]] = {}
    for address, lat, lon in rows:
        if lat is None or lon is None:
            continue
        by_patient[address.patient_id] = (address, float(lat), float(lon))
    if set(by_patient) != set(patient_ids):
        raise DomainError(
            422,
            "STOP_LOCATION_MISSING",
            "Faltan coordenadas confirmadas para una parada de la ruta",
        )
    return by_patient


def _service_minutes_by_patient(
    db: Session, revision: RouteRevision
) -> dict[uuid.UUID, int]:
    rows = (
        db.query(RouteStop.patient_id, RouteStop.service_minutes)
        .filter(
            RouteStop.revision_id == revision.id,
            RouteStop.organization_id == revision.organization_id,
        )
        .all()
    )
    return {patient_id: minutes or DEFAULT_SERVICE_MINUTES for patient_id, minutes in rows}


def _open_draft_revision(
    db: Session,
    route: DailyRoute,
    *,
    previous: RouteRevision | None,
    created_by: uuid.UUID,
) -> RouteRevision:
    revision = RouteRevision(
        organization_id=route.organization_id,
        route_id=route.id,
        revision=_next_revision_number(db, route),
        status="draft",
        objective=previous.objective if previous is not None else "time",
        origin=previous.origin if previous is not None else None,
        destination=previous.destination if previous is not None else None,
        solver_status="pending",
        constraints_json={},
        osrm_dataset_version=previous.osrm_dataset_version if previous is not None else None,
        created_by=created_by,
    )
    db.add(revision)
    db.flush()
    return revision


def _clear_revision_stops(db: Session, revision: RouteRevision) -> None:
    stops = (
        db.query(RouteStop)
        .filter(
            RouteStop.revision_id == revision.id,
            RouteStop.organization_id == revision.organization_id,
        )
        .all()
    )
    for stop in stops:
        db.delete(stop)
    db.flush()


def _mark_metrics_stale(db: Session, revision: RouteRevision) -> None:
    metrics = (
        db.query(RouteMetric)
        .filter(
            RouteMetric.revision_id == revision.id,
            RouteMetric.organization_id == revision.organization_id,
        )
        .all()
    )
    for metric in metrics:
        payload = dict(metric.calculation_json or {})
        payload["stale"] = True
        metric.calculation_json = payload


def _address_snapshot(cipher: FieldCipher | None, stop: _StopInput) -> str:
    if cipher is None:
        return ""
    payload = json.dumps(
        {"municipality": stop.municipality, "postal_code": stop.postal_code},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return cipher.encrypt(payload)


def _publish_address_snapshot(
    cipher: FieldCipher,
    stop: RouteStop,
    address: Address | None,
    *,
    latitude: float,
    longitude: float,
) -> str:
    payload: dict[str, Any] = {
        "patient_id": str(stop.patient_id),
        "sequence": stop.sequence,
        "lat": latitude,
        "lon": longitude,
        "postal_code": address.postal_code if address is not None else "",
        "municipality": address.municipality if address is not None else "",
        "province": address.province if address is not None else "",
    }
    if address is not None and address.address_ciphertext:
        decrypted = _try_decrypt_address(cipher, address.address_ciphertext)
        if decrypted:
            payload["address"] = decrypted
    return cipher.encrypt(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def _metric_snapshot(metric: RouteMetric) -> dict[str, Any]:
    return {
        "distance_m": metric.distance_m,
        "travel_seconds": metric.travel_seconds,
        "service_seconds": metric.service_seconds,
        "estimated_cost": metric.estimated_cost,
        "matrix_hash": (metric.calculation_json or {}).get("matrix_hash"),
        "dataset_version": (metric.calculation_json or {}).get("dataset_version"),
    }


def _try_decrypt_address(cipher: FieldCipher, token: str) -> str | None:
    try:
        return cipher.decrypt(token)
    except (ValueError, KeyError, UnicodeDecodeError, InvalidTag):
        return None


def _coordinate_from_payload(payload: dict[str, Any]) -> Coordinate:
    try:
        return Coordinate(latitude=float(payload["lat"]), longitude=float(payload["lon"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError(422, "ROUTE_ORIGIN_MISSING", "Origen o destino no válido") from exc


def _geometry_from_router(router: Router, coordinates: list[Coordinate]) -> dict[str, Any]:
    try:
        payload = _run_coro(router.route(coordinates))
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            503,
            "ROUTER_UNAVAILABLE",
            "OSRM no disponible para la geometría de publicación",
        ) from exc
    geometry = _normalize_route_geometry(payload)
    if geometry is None:
        raise DomainError(
            409,
            "ROUTE_GEOMETRY_UNAVAILABLE",
            "No hay geometría OSRM para publicar",
        )
    return geometry


def _normalize_route_geometry(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    routes = payload.get("routes")
    if isinstance(routes, list) and routes:
        geom = (routes[0] or {}).get("geometry")
        if isinstance(geom, dict) and geom.get("coordinates"):
            return geom
    geom = payload.get("geometry")
    if isinstance(geom, dict) and geom.get("coordinates"):
        return geom
    raw_coords = payload.get("coordinates")
    if not isinstance(raw_coords, list) or not raw_coords:
        return None
    converted: list[list[float]] = []
    for item in raw_coords:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        lat, lon = float(item[0]), float(item[1])
        converted.append([lon, lat])
    if not converted:
        return None
    return {"type": "LineString", "coordinates": converted}


def _run_coro(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _point_ewkt(lon: float, lat: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


def _cost_for_order(
    matrix: ComputedMatrix,
    order: list[int],
    cost_per_km: float,
    cost_per_hour: float,
) -> float:
    total = 0.0
    for origin, dest in pairwise(order):
        total += estimated_arc_cost(
            matrix.distances_meters[origin][dest],
            matrix.durations_seconds[origin][dest],
            cost_per_km=cost_per_km,
            cost_per_hour=cost_per_hour,
        )
    return total


def _next_revision_number(db: Session, route: DailyRoute) -> int:
    current = (
        db.query(func.max(RouteRevision.revision))
        .filter(
            RouteRevision.route_id == route.id,
            RouteRevision.organization_id == route.organization_id,
        )
        .scalar()
    )
    return int(current or 0) + 1


def _lock_job(db: Session, job_id: uuid.UUID | None, *, organization_id: uuid.UUID) -> Job | None:
    if job_id is None:
        return None
    job = (
        db.query(Job)
        .filter(Job.id == job_id, Job.organization_id == organization_id)
        .with_for_update()
        .one_or_none()
    )
    return job


def _stop_coordinates(
    db: Session, stops: list[RouteStop]
) -> dict[uuid.UUID, tuple[float | None, float | None]]:
    if not stops:
        return {}
    stop_lat = func.ST_Y(cast(RouteStop.location, Geometry))
    stop_lon = func.ST_X(cast(RouteStop.location, Geometry))
    rows = (
        db.query(RouteStop.id, stop_lat, stop_lon)
        .filter(RouteStop.id.in_([stop.id for stop in stops]))
        .all()
    )
    coords: dict[uuid.UUID, tuple[float | None, float | None]] = {}
    for stop_id, lat, lon in rows:
        coords[stop_id] = (
            float(lat) if lat is not None else None,
            float(lon) if lon is not None else None,
        )
    return coords


def _stop_external_refs(
    db: Session,
    organization_id: uuid.UUID,
    revision: RouteRevision | None,
    stops: list[RouteStop],
) -> dict[uuid.UUID, str]:
    refs: dict[uuid.UUID, str] = {}
    snapshot = ((revision.constraints_json or {}).get("snapshot") if revision else None) or {}
    for item in snapshot.get("order") or []:
        raw_id = item.get("patient_id")
        if not raw_id:
            continue
        try:
            refs[uuid.UUID(str(raw_id))] = str(item.get("external_ref") or "")
        except ValueError:
            continue
    missing = [stop.patient_id for stop in stops if stop.patient_id not in refs]
    if missing:
        for patient_id, external_ref in (
            db.query(Patient.id, Patient.external_ref)
            .filter(Patient.organization_id == organization_id, Patient.id.in_(missing))
            .all()
        ):
            refs[patient_id] = external_ref
    return refs


def _current_revision_with_stops(
    db: Session, route: DailyRoute
) -> tuple[RouteRevision | None, list[RouteStop]]:
    if route.current_revision is None:
        return None, []
    revision = (
        db.query(RouteRevision)
        .filter(
            RouteRevision.id == route.current_revision,
            RouteRevision.organization_id == route.organization_id,
        )
        .one_or_none()
    )
    if revision is None:
        return None, []
    stops = (
        db.query(RouteStop)
        .filter(
            RouteStop.revision_id == revision.id,
            RouteStop.organization_id == route.organization_id,
        )
        .order_by(RouteStop.sequence)
        .all()
    )
    return revision, stops
