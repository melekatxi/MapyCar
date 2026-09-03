"""Métricas original vs optimizada sobre la misma matriz. Ref: 3.BE.6, diseño 7.5.

La ruta "original" (orden importado/manual) y la "optimized" recorren los
mismos índices de la matriz OSRM para una comparación justa. `service_seconds`
no depende del orden: suma de `service_minutes * 60`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from itertools import pairwise
from typing import Any

from sqlalchemy.orm import Session

from app.modules.routing.matrix import ComputedMatrix
from app.modules.routing.models import RouteMetric


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
