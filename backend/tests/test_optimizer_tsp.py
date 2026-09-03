"""TSP OR-Tools (un vehículo, sin ventanas). Ref: 3.BE.3, 3.BE.5, RF-16, RNF-02."""

from __future__ import annotations

import random
import time
from math import hypot

import pytest
from ortools.constraint_solver import routing_enums_pb2

from app.adapters.optimizer.ortools_tsp import (
    DEFAULT_TIME_LIMIT_SECONDS,
    OrToolsTspOptimizer,
    estimated_routes_cost,
    routing_status_name,
)

_SLA_SECONDS = 15.0
_LINE_ORDERS = ([0, 1, 2, 3], [0, 3, 2, 1])
_P95_CI_N = 5
_P95_SEED = 20260830


def _euclidean_matrix(points: list[tuple[float, float]]) -> list[list[float]]:
    n = len(points)
    matrix = [[0.0] * n for _ in range(n)]
    for i, (xi, yi) in enumerate(points):
        for j, (xj, yj) in enumerate(points):
            matrix[i][j] = hypot(xi - xj, yi - yj)
    return matrix


def test_line_of_four_visits_in_spatial_order() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)]
    durations = _euclidean_matrix(points)
    result = OrToolsTspOptimizer(time_limit_seconds=1.0).solve(
        durations_seconds=durations, distances_meters=durations
    )

    assert result.order[0] == 0
    assert result.order in _LINE_ORDERS
    assert result.solver_status
    assert result.solver_status != "ROUTING_NOT_SOLVED"
    assert result.objective_value > 0


def test_twenty_five_stops_solve_under_sla() -> None:
    points = [(float(x), float(y)) for y in range(5) for x in range(5)]
    durations = _euclidean_matrix(points)
    optimizer = OrToolsTspOptimizer()

    started = time.perf_counter()
    result = optimizer.solve(durations_seconds=durations, distances_meters=durations)
    elapsed = time.perf_counter() - started

    assert elapsed < _SLA_SECONDS
    assert result.order[0] == 0
    assert len(result.order) == 25
    assert sorted(result.order) == list(range(25))
    assert result.solver_status
    assert result.solver_status not in {"ROUTING_NOT_SOLVED", "ROUTING_FAIL"}
    assert result.objective_value > 0


def test_time_limit_is_configured_below_sla() -> None:
    assert DEFAULT_TIME_LIMIT_SECONDS == 10.0
    assert DEFAULT_TIME_LIMIT_SECONDS < _SLA_SECONDS
    assert OrToolsTspOptimizer().time_limit_seconds == DEFAULT_TIME_LIMIT_SECONDS

    points = [(float(i), 0.0) for i in range(8)]
    durations = _euclidean_matrix(points)
    optimizer = OrToolsTspOptimizer(time_limit_seconds=0.5)

    started = time.perf_counter()
    result = optimizer.solve(durations_seconds=durations, distances_meters=durations)
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert result.solver_status


def test_feasible_status_is_not_labeled_optimal() -> None:
    status = routing_enums_pb2.RoutingSearchStatus.ROUTING_SUCCESS
    name = routing_status_name(status)
    assert name == "ROUTING_SUCCESS"
    assert "OPTIMAL" not in name


def test_explicit_time_objective_matches_default_tsp_path() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)]
    durations = _euclidean_matrix(points)
    optimizer = OrToolsTspOptimizer(time_limit_seconds=1.0)
    default = optimizer.solve(durations_seconds=durations, distances_meters=durations)
    timed = optimizer.solve(
        durations_seconds=durations, distances_meters=durations, objective="time"
    )

    assert default.order == timed.order
    assert default.order in _LINE_ORDERS
    assert default.objective_value == timed.objective_value
    assert default.diagnostics == []
    assert timed.routes == [timed.order]


def test_estimated_cost_uses_distance_and_travel_time_on_tsp_tour() -> None:
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0), (30.0, 0.0)]
    durations = _euclidean_matrix(points)
    distances = [[cell * 1000.0 for cell in row] for row in durations]
    cost_per_km = 2.0
    cost_per_hour = 3600.0
    result = OrToolsTspOptimizer(time_limit_seconds=1.0).solve(
        durations_seconds=durations,
        distances_meters=distances,
        objective="time",
        cost_per_km=cost_per_km,
        cost_per_hour=cost_per_hour,
        service_times_seconds=[0.0, 1.0, 2.0, 3.0],
    )

    assert result.order in _LINE_ORDERS
    assert result.service_duration_seconds == 6.0
    expected = estimated_routes_cost(
        distances,
        durations,
        [result.order],
        depot_index=0,
        cost_per_km=cost_per_km,
        cost_per_hour=cost_per_hour,
    )
    assert result.estimated_cost == pytest.approx(expected)
    assert result.estimated_cost > 0


def test_p95_of_five_twenty_five_stop_solves_under_sla() -> None:
    """Smoke de RNF-02. El criterio de aceptación es scripts/qa/tsp-benchmark.md (N=30)."""
    optimizer = OrToolsTspOptimizer()
    times: list[float] = []
    for i in range(_P95_CI_N):
        rng = random.Random(_P95_SEED + i)
        points = [(rng.random() * 100.0, rng.random() * 100.0) for _ in range(25)]
        durations = _euclidean_matrix(points)
        started = time.perf_counter()
        result = optimizer.solve(durations_seconds=durations, distances_meters=durations)
        times.append(time.perf_counter() - started)
        assert result.order[0] == 0
        assert len(result.order) == 25
        assert sorted(result.order) == list(range(25))
        assert result.solver_status not in {"ROUTING_NOT_SOLVED", "ROUTING_FAIL"}

    p95 = _linear_percentile(times, 95)
    assert p95 < _SLA_SECONDS


def _linear_percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac

