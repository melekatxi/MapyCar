"""Puerto Optimizer. Ref: ADR-06, ADR-10, 3.BE.3–3.BE.5."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

Objective = Literal["time", "cost"]

INCOMPATIBLE_WINDOWS = "INCOMPATIBLE_WINDOWS"
INSUFFICIENT_SHIFT = "INSUFFICIENT_SHIFT"
ISOLATED_STOP = "ISOLATED_STOP"


@dataclass(frozen=True)
class InfeasibilityDiagnostic:
    code: str
    node_indices: tuple[int, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class OptimizationResult:
    order: list[int]
    solver_status: str
    objective_value: float
    diagnostics: list[InfeasibilityDiagnostic] = field(default_factory=list)
    estimated_cost: float = 0.0
    service_duration_seconds: float = 0.0
    routes: list[list[int]] = field(default_factory=list)


class Optimizer(ABC):
    @abstractmethod
    def solve(
        self,
        *,
        durations_seconds: list[list[float]],
        distances_meters: list[list[float]],
        time_windows: list[tuple[float, float] | None] | None = None,
        service_times_seconds: list[float] | None = None,
        vehicle_count: int = 1,
        vehicle_time_capacity_seconds: float | None = None,
        objective: Objective = "time",
        cost_per_km: float = 0.0,
        cost_per_hour: float = 0.0,
    ) -> OptimizationResult:
        """Resuelve TSP/VRP/VRPTW sobre una matriz ya calculada.

        Ventanas en segundos desde la salida del depósito. `objective="time"`
        minimiza segundos de viaje; `objective="cost"` minimiza
        `distancia_km * cost_per_km + horas_viaje * cost_per_hour` en arcos.
        La duración de atención se informa y no depende del orden.
        """
