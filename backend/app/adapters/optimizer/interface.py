"""Puerto Optimizer. Ref: ADR-06, ADR-10. La implementación OR-Tools llega en Fase 3."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class OptimizationResult:
    order: list[int]
    solver_status: str
    objective_value: float


class Optimizer(ABC):
    @abstractmethod
    def solve(
        self, *, durations_seconds: list[list[float]], distances_meters: list[list[float]]
    ) -> OptimizationResult:
        """Resuelve TSP/VRP sobre una matriz ya calculada."""
