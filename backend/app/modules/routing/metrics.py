"""Métricas original/optimizada (matriz OSRM) y actual (datos reportados).

Ref: 3.BE.6, 4.BE.3, diseño 7.5–7.6.

La ruta "original" (orden importado/manual) y la "optimized" recorren los
mismos índices de la matriz OSRM para una comparación justa. `service_seconds`
no depende del orden: suma de `service_minutes * 60`.

`actual` solo usa paradas reportadas (diseño 7.6): no GPS ni teselas. Distancia
vial real no está disponible en v1 (`distance_source=unavailable`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.modules.routing.matrix import ComputedMatrix
from app.modules.routing.models import RouteMetric

_VISITED_STOP_STATUSES = frozenset({"completed", "failed"})


def metrics_for_order(
    durations_seconds: Sequence[Sequence[float]],
    distances_meters: Sequence[Sequence[float]],
    order: Sequence[int],
    *,
    service_minutes: Sequence[int] | None = None,
) -> dict[str, int]:
    """Suma arcos `order[i] → order[i+1]` sobre la matriz. `order` son índices NxN."""
    n = len(durations_seconds)
    if n == 0 or len(distances_meters) != n:
        raise ValueError("Matriz vacía o durations/distances de distinto tamaño")
    travel = 0.0
    distance = 0.0
    for a, b in pairwise(order):
        if a < 0 or b < 0 or a >= n or b >= n:
            raise ValueError(f"Índice de orden fuera de rango: {a} → {b} (n={n})")
        travel += float(durations_seconds[a][b])
        distance += float(distances_meters[a][b])
    service_seconds = 0
    if service_minutes:
        service_seconds = sum(int(minutes) * 60 for minutes in service_minutes)
    return {
        "travel_seconds": round(travel),
        "distance_m": round(distance),
        "service_seconds": service_seconds,
    }


def build_metrics(
    revision_id: uuid.UUID,
    matrix: ComputedMatrix,
    original_order: Sequence[int],
    optimized_order: Sequence[int],
    *,
    organization_id: uuid.UUID,
    service_minutes: Sequence[int] | None = None,
    estimated_cost_original: float = 0.0,
    estimated_cost_optimized: float = 0.0,
) -> list[dict[str, Any]]:
    """Dos dicts listos para `RouteMetric`: variantes `original` y `optimized`.

    Comparten `calculation_json.matrix_hash` (misma matriz base).
    """
    original = metrics_for_order(
        matrix.durations_seconds,
        matrix.distances_meters,
        original_order,
        service_minutes=service_minutes,
    )
    optimized = metrics_for_order(
        matrix.durations_seconds,
        matrix.distances_meters,
        optimized_order,
        service_minutes=service_minutes,
    )
    return [
        _metric_row(
            revision_id,
            organization_id,
            variant="original",
            totals=original,
            order=list(original_order),
            matrix=matrix,
            estimated_cost=estimated_cost_original,
        ),
        _metric_row(
            revision_id,
            organization_id,
            variant="optimized",
            totals=optimized,
            order=list(optimized_order),
            matrix=matrix,
            estimated_cost=estimated_cost_optimized,
        ),
    ]


def persist_metrics(session: Session, rows: Sequence[dict[str, Any]]) -> list[RouteMetric]:
    models = [RouteMetric(**row) for row in rows]
    session.add_all(models)
    session.flush()
    return models


def metrics_from_reports(
    stops: Sequence[Any],
    *,
    planned_travel_seconds: int = 0,
    planned_cost: float = 0.0,
) -> dict[str, Any]:
    """Totales `actual` a partir de status/hora/service_minutes reportados.

    Viaje = (última − primera `completed_at` de visited) − servicio completado,
    nunca negativo. Visited = completed|failed (skipped no viaja). Sin GPS.
    """
    completed = [stop for stop in stops if stop.status == "completed"]
    failed = [stop for stop in stops if stop.status == "failed"]
    skipped = [stop for stop in stops if stop.status == "skipped"]
    pending = [stop for stop in stops if stop.status == "pending"]
    visited = [
        stop
        for stop in stops
        if stop.status in _VISITED_STOP_STATUSES and stop.completed_at is not None
    ]
    service_seconds = sum(int(stop.service_minutes or 0) * 60 for stop in completed)
    timed = sorted(visited, key=lambda stop: (_as_utc(stop.completed_at), stop.sequence))
    if len(timed) >= 2:
        first = _as_utc(timed[0].completed_at)
        last = _as_utc(timed[-1].completed_at)
        elapsed = max(0.0, (last - first).total_seconds())
        travel_seconds = max(0, round(elapsed - service_seconds))
    else:
        travel_seconds = 0
    if planned_travel_seconds > 0:
        estimated_cost = round(planned_cost * travel_seconds / planned_travel_seconds, 4)
    else:
        estimated_cost = 0.0
    return {
        "distance_m": 0,
        "travel_seconds": travel_seconds,
        "service_seconds": service_seconds,
        "estimated_cost": estimated_cost,
        "calculation_json": {
            "source": "reported",
            "distance_source": "unavailable",
            "completed": len(completed),
            "failed": len(failed),
            "skipped": len(skipped),
            "pending": len(pending),
            "visited_order": [str(stop.id) for stop in timed],
        },
    }


def upsert_actual_metric(
    session: Session,
    *,
    revision_id: uuid.UUID,
    organization_id: uuid.UUID,
    stops: Sequence[Any],
    planned: RouteMetric | None,
) -> RouteMetric:
    totals = metrics_from_reports(
        stops,
        planned_travel_seconds=planned.travel_seconds if planned is not None else 0,
        planned_cost=planned.estimated_cost if planned is not None else 0.0,
    )
    existing = (
        session.query(RouteMetric)
        .filter(
            RouteMetric.revision_id == revision_id,
            RouteMetric.organization_id == organization_id,
            RouteMetric.variant == "actual",
        )
        .with_for_update()
        .one_or_none()
    )
    if existing is None:
        existing = RouteMetric(
            revision_id=revision_id,
            organization_id=organization_id,
            variant="actual",
            distance_m=totals["distance_m"],
            travel_seconds=totals["travel_seconds"],
            service_seconds=totals["service_seconds"],
            estimated_cost=totals["estimated_cost"],
            calculation_json=totals["calculation_json"],
        )
        session.add(existing)
        session.flush()
        return existing
    existing.distance_m = totals["distance_m"]
    existing.travel_seconds = totals["travel_seconds"]
    existing.service_seconds = totals["service_seconds"]
    existing.estimated_cost = totals["estimated_cost"]
    existing.calculation_json = totals["calculation_json"]
    flag_modified(existing, "calculation_json")
    session.flush()
    return existing


def _as_utc(value: datetime | None) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _metric_row(
    revision_id: uuid.UUID,
    organization_id: uuid.UUID,
    *,
    variant: str,
    totals: dict[str, int],
    order: list[int],
    matrix: ComputedMatrix,
    estimated_cost: float,
) -> dict[str, Any]:
    return {
        "revision_id": revision_id,
        "variant": variant,
        "organization_id": organization_id,
        "distance_m": totals["distance_m"],
        "travel_seconds": totals["travel_seconds"],
        "service_seconds": totals["service_seconds"],
        "estimated_cost": estimated_cost,
        "calculation_json": {
            "matrix_hash": matrix.matrix_hash,
            "order": order,
            "profile": matrix.profile,
            "dataset_version": matrix.dataset_version,
        },
    }
