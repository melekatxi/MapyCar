"""VRPTW e objetivo tiempo/coste. Ref: 3.BE.4, 3.BE.5, RF-17, RF-19."""

from __future__ import annotations

import pytest

from app.adapters.optimizer.interface import (
    INCOMPATIBLE_WINDOWS,
    INSUFFICIENT_SHIFT,
    ISOLATED_STOP,
)
from app.adapters.optimizer.ortools_tsp import OrToolsTspOptimizer, estimated_routes_cost

_COST_PER_KM = 1.0
_COST_PER_HOUR = 0.0


def _incompatible_window_matrices() -> tuple[list[list[float]], list[list[float]]]:
    # A y B son factibles por separado (ida y vuelta 20 s) pero el viaje A↔B (100 s)
    # sale de la ventana [0, 50] del segundo; un vehículo no puede servir ambos.
    durations = [
        [0.0, 10.0, 10.0],
        [10.0, 0.0, 100.0],
        [10.0, 100.0, 0.0],
    ]
    return durations, [row[:] for row in durations]


def _time_vs_cost_matrices() -> tuple[list[list[float]], list[list[float]]]:
    # Ciclo horario: rápido y largo. Antihorario: lento y corto. El resto, peor.
    n = 4
    slow, far = 10_000.0, 1_000_000.0
    durations = [[0.0 if i == j else slow for j in range(n)] for i in range(n)]
    distances = [[0.0 if i == j else far for j in range(n)] for i in range(n)]
    for origin, dest in ((0, 1), (1, 2), (2, 3), (3, 0)):
        durations[origin][dest] = 10.0
        distances[origin][dest] = 100_000.0
    for origin, dest in ((0, 3), (3, 2), (2, 1), (1, 0)):
        durations[origin][dest] = 10_000.0
        distances[origin][dest] = 100.0
    return durations, distances


def _codes(result) -> set[str]:
    return {item.code for item in result.diagnostics}


def test_incompatible_windows_return_infeasible_diagnosis_not_a_tour() -> None:
    durations, distances = _incompatible_window_matrices()
    result = OrToolsTspOptimizer(time_limit_seconds=1.0).solve(
        durations_seconds=durations,
        distances_meters=distances,
        time_windows=[None, (0.0, 50.0), (0.0, 50.0)],
    )

    assert result.order == []
    assert result.routes == []
    assert result.solver_status == "ROUTING_INFEASIBLE"
    assert INCOMPATIBLE_WINDOWS in _codes(result)
    pair = next(item for item in result.diagnostics if item.code == INCOMPATIBLE_WINDOWS)
    assert set(pair.node_indices) == {1, 2}


def test_two_vehicles_split_incompatible_single_vehicle_load() -> None:
    durations, distances = _incompatible_window_matrices()
    windows = [None, (0.0, 50.0), (0.0, 50.0)]
    result = OrToolsTspOptimizer(time_limit_seconds=1.0).solve(
        durations_seconds=durations,
        distances_meters=distances,
        time_windows=windows,
        vehicle_count=2,
    )

    assert result.solver_status not in {"ROUTING_INFEASIBLE", "ROUTING_FAIL", "ROUTING_NOT_SOLVED"}
    assert len(result.routes) == 2
    assert all(route[0] == 0 for route in result.routes)
    stops = sorted(node for route in result.routes for node in route if node != 0)
    assert stops == [1, 2]
    assert {frozenset(route) for route in result.routes} == {frozenset({0, 1}), frozenset({0, 2})}
    assert INCOMPATIBLE_WINDOWS not in _codes(result)


def test_isolated_stop_is_diagnosed_without_a_tour() -> None:
    durations = [
        [0.0, 100.0],
        [100.0, 0.0],
    ]
    result = OrToolsTspOptimizer(time_limit_seconds=1.0).solve(
        durations_seconds=durations,
        distances_meters=durations,
        time_windows=[None, (0.0, 5.0)],
    )

    assert result.order == []
    assert result.solver_status == "ROUTING_INFEASIBLE"
    assert ISOLATED_STOP in _codes(result)
    assert result.diagnostics[0].node_indices == (1,)


def test_insufficient_shift_is_diagnosed_without_a_tour() -> None:
    durations = [
        [0.0, 10.0],
        [10.0, 0.0],
    ]
    result = OrToolsTspOptimizer(time_limit_seconds=1.0).solve(
        durations_seconds=durations,
        distances_meters=durations,
        service_times_seconds=[0.0, 100.0],
        vehicle_time_capacity_seconds=50.0,
    )

    assert result.order == []
    assert result.solver_status == "ROUTING_INFEASIBLE"
    assert INSUFFICIENT_SHIFT in _codes(result)
    assert result.diagnostics[0].node_indices == (1,)


def test_time_and_cost_objectives_diverge_on_the_same_fixture() -> None:
    durations, distances = _time_vs_cost_matrices()
    optimizer = OrToolsTspOptimizer(time_limit_seconds=1.0)
    kwargs = {
        "durations_seconds": durations,
        "distances_meters": distances,
        "cost_per_km": _COST_PER_KM,
        "cost_per_hour": _COST_PER_HOUR,
    }
    by_time = optimizer.solve(**kwargs, objective="time")
    by_cost = optimizer.solve(**kwargs, objective="cost")

    assert by_time.order[0] == 0
    assert by_cost.order[0] == 0
    assert by_time.order == [0, 1, 2, 3]
    assert by_cost.order == [0, 3, 2, 1]
    assert by_time.order != by_cost.order
    assert by_time.objective_value != by_cost.objective_value
    assert by_time.estimated_cost != by_cost.estimated_cost
    assert by_cost.estimated_cost == pytest.approx(
        estimated_routes_cost(
            distances,
            durations,
            by_cost.routes or [by_cost.order],
            depot_index=0,
            cost_per_km=_COST_PER_KM,
            cost_per_hour=_COST_PER_HOUR,
        )
    )
    assert by_cost.objective_value == pytest.approx(by_cost.estimated_cost)


def test_service_duration_does_not_change_with_order() -> None:
    durations, distances = _time_vs_cost_matrices()
    services = [0.0, 5.0, 7.0, 11.0]
    optimizer = OrToolsTspOptimizer(time_limit_seconds=1.0)
    kwargs = {
        "durations_seconds": durations,
        "distances_meters": distances,
        "service_times_seconds": services,
        "cost_per_km": _COST_PER_KM,
        "cost_per_hour": _COST_PER_HOUR,
    }
    by_time = optimizer.solve(**kwargs, objective="time")
    by_cost = optimizer.solve(**kwargs, objective="cost")

    assert by_time.order != by_cost.order
    assert by_time.service_duration_seconds == 23.0
    assert by_cost.service_duration_seconds == 23.0


def test_compatible_windows_return_a_feasible_tour() -> None:
    durations = [
        [0.0, 10.0, 10.0],
        [10.0, 0.0, 10.0],
        [10.0, 10.0, 0.0],
    ]
    result = OrToolsTspOptimizer(time_limit_seconds=1.0).solve(
        durations_seconds=durations,
        distances_meters=durations,
        time_windows=[None, (0.0, 1_000.0), (0.0, 1_000.0)],
        service_times_seconds=[0.0, 5.0, 5.0],
    )

    assert result.order[0] == 0
    assert sorted(result.order) == [0, 1, 2]
    assert result.solver_status not in {"ROUTING_INFEASIBLE", "ROUTING_FAIL"}
    assert result.diagnostics == []
    assert result.service_duration_seconds == 10.0
