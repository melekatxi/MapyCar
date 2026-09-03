"""Servicio de rutas diarias: optimización, reordenación y comparativa.

Ref: RF-16, RF-18, RF-19, RF-20, 3.BE.7, 3.BE.8, 3.BE.10, 3.BE.12.

If-Match usa `daily_routes.version` (route_revisions no tiene columna version).
Tras reordenar, route_metrics.calculation_json.stale = true (pendiente de recálculo).
GET /comparison lee original vs optimized de current_revision y 409 si faltan o están stale.
POST /optimize es idempotente (ledger `route.optimize`); el worker crea la revisión draft.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import cast, func
from sqlalchemy.orm import Session

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
from app.core.crypto import FieldCipher
from app.core.errors import DomainError
from app.jobs.queue import JobQueue
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization
from app.modules.imports.models import Address, Patient
from app.modules.jobs.ledger import begin_idempotent_job
from app.modules.jobs.models import Job
from app.modules.planning.calendar import DEFAULT_SERVICE_MINUTES
from app.modules.planning.models import DailyRoute, MonthlyPlan
from app.modules.routing.matrix import (
    ComputedMatrix,
    OsrmTableCache,
    assemble_table_coordinates,
    compute_matrix,
)
from app.modules.routing.metrics import build_metrics, persist_metrics
from app.modules.routing.models import RouteMetric, RouteRevision, RouteStop
from app.modules.routing.schemas import (
    OptimizeRouteRequest,
    OptimizeRouteResponse,
    ReorderStopsResponse,
    RouteComparisonResponse,
    RouteDetailResponse,
    RouteDiagnosticOut,
    RouteMetricsSavingsOut,
    RouteMetricsVariantOut,
    RouteStopOrderOut,
    RouteStopOut,
)

OPTIMIZE_JOB_TYPE = "route.optimize"
OPTIMIZE_RESOURCE_TYPE = "route"
OPTIMIZE_QUEUE = "optimization"
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
    ledger_payload = {
        "route_id": str(route.id),
        **payload.model_dump(mode="json"),
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
            RouteStopOut(id=stop.id, patient_id=stop.patient_id, sequence=stop.sequence)
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
            RouteMetric.variant.in_(("original", "optimized")),
        )
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
    )


def _variant_out(metric: RouteMetric) -> RouteMetricsVariantOut:
    return RouteMetricsVariantOut(
        distance_m=metric.distance_m,
        travel_seconds=metric.travel_seconds,
        service_seconds=metric.service_seconds,
        estimated_cost=metric.estimated_cost,
    )


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
