from __future__ import annotations

from app.adapters.optimizer.interface import OptimizationResult, Optimizer


class FakeOptimizer(Optimizer):
    def solve(
        self, *, durations_seconds: list[list[float]], distances_meters: list[list[float]]
    ) -> OptimizationResult:
        n = len(durations_seconds)
        return OptimizationResult(order=list(range(n)), solver_status="FAKE_IDENTITY", objective_value=0.0)
