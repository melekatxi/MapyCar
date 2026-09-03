"""Esquemas Pydantic de rutas: optimización, reordenación y comparativa.

Ref: diseño sección 8.5, RF-16, RF-18, RF-19, RF-20, 3.BE.7, 3.BE.8, 3.BE.12.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class OptimizeWindowIn(BaseModel):
    """Ventana en segundos desde la salida del depósito, por paciente."""

    patient_id: uuid.UUID
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered_window(self) -> Self:
        if self.start_seconds > self.end_seconds:
            raise ValueError("end_seconds debe ser >= start_seconds")
        return self


class OptimizeRouteRequest(BaseModel):
    objective: Literal["time", "cost"] = "time"
    origin: LatLon
    destination: LatLon | None = None
    cost_per_km: float = Field(default=0.0, ge=0)
    cost_per_hour: float = Field(default=0.0, ge=0)
    vehicle_count: int = Field(default=1, ge=1)
    vehicle_time_capacity_seconds: float | None = Field(default=None, gt=0)
    windows: list[OptimizeWindowIn] | None = None
    service_minutes: int | None = Field(default=None, ge=0)


class OptimizeRouteResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    revision_id: uuid.UUID | None = None


class ReorderStopsRequest(BaseModel):
    revision_id: uuid.UUID
    ordered_stop_ids: list[uuid.UUID] = Field(min_length=1)


class RouteStopOrderOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    sequence: int
    version: int


class ReorderStopsResponse(BaseModel):
    route_id: uuid.UUID
    revision_id: uuid.UUID
    version: int
    stops: list[RouteStopOrderOut]
    metrics_pending: bool


class RouteMetricsVariantOut(BaseModel):
    distance_m: int
    travel_seconds: int
    service_seconds: int
    estimated_cost: float


class RouteMetricsSavingsOut(BaseModel):
    distance_m: int
    travel_seconds: int
    estimated_cost: float
    travel_seconds_pct: float


class RouteDiagnosticOut(BaseModel):
    code: str
    node_indices: list[int] = Field(default_factory=list)
    detail: str = ""
    suggested_actions: list[str] = Field(default_factory=list)


class RouteComparisonResponse(BaseModel):
    original: RouteMetricsVariantOut
    optimized: RouteMetricsVariantOut
    savings: RouteMetricsSavingsOut
    solver_status: str | None = None
    diagnostics: list[RouteDiagnosticOut] = Field(default_factory=list)
    revision_id: uuid.UUID | None = None


class RouteStopOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    sequence: int


class RouteDetailResponse(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    organization_id: uuid.UUID
    zone_id: uuid.UUID
    service_date: date
    assignee_id: uuid.UUID
    status: str
    version: int
    current_revision: uuid.UUID | None = None
    revision: int | None = None
    objective: str | None = None
    solver_status: str | None = None
    diagnostics: list[RouteDiagnosticOut] = Field(default_factory=list)
    stops: list[RouteStopOut] = Field(default_factory=list)
