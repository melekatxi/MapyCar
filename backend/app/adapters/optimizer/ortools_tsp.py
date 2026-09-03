"""TSP/VRP/VRPTW con OR-Tools Routing. Ref: ADR-10, 3.BE.3–3.BE.5.

`order` es el orden de visita de índices de la matriz, depósito al inicio.
Origen y destino coinciden: el índice de retorno no se duplica al final; el arco
de vuelta al depósito sí entra en `objective_value` y `estimated_cost`.

Sin ventanas, un vehículo y sin jornada se modela TSP (PATH_CHEAPEST_ARC).
Con ventanas, jornada o varios visitadores se usa VRP/VRPTW. La atención entra
en la dimensión de tiempo, no en el objetivo: el orden no cambia su suma.

`objective="time"` minimiza segundos de viaje. `objective="cost"` minimiza
`distancia_km * cost_per_km + horas_viaje * cost_per_hour` en arcos.

`solver_status` es el nombre corto del enum de OR-Tools. Si las restricciones
duras son inviables se devuelve `ROUTING_INFEASIBLE` con `diagnostics`, nunca
un tour que viole ventanas. `ROUTING_SUCCESS` es factible, no óptimo
matemático; solo `ROUTING_OPTIMAL` acredita optimalidad.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.adapters.optimizer.interface import (
    INCOMPATIBLE_WINDOWS,
    INSUFFICIENT_SHIFT,
    ISOLATED_STOP,
    InfeasibilityDiagnostic,
    Objective,
    OptimizationResult,
    Optimizer,
)

DEFAULT_TIME_LIMIT_SECONDS = 10.0
_MS_PER_SECOND = 1000
_COST_SCALE = 1_000_000
_METERS_PER_KM = 1000.0
_SECONDS_PER_HOUR = 3600.0
_TIME_DIMENSION = "Time"


def routing_status_name(status: int) -> str:
    """Traduce el entero de OR-Tools al nombre del enum; no relabela factible como óptimo."""
    try:
        name = routing_enums_pb2.RoutingSearchStatus.Value.Name(status)
    except ValueError:
        return "ROUTING_UNKNOWN"
    return name or "ROUTING_UNKNOWN"


def estimated_arc_cost(
    distance_meters: float,
    duration_seconds: float,
    *,
    cost_per_km: float,
    cost_per_hour: float,
) -> float:
    return (distance_meters / _METERS_PER_KM) * cost_per_km + (
        duration_seconds / _SECONDS_PER_HOUR
    ) * cost_per_hour


def estimated_routes_cost(
    distances_meters: Sequence[Sequence[float]],
    durations_seconds: Sequence[Sequence[float]],
    routes: Sequence[Sequence[int]],
    *,
    depot_index: int,
    cost_per_km: float,
    cost_per_hour: float,
) -> float:
    total = 0.0
    for route in routes:
        if not route:
            continue
        nodes = list(route)
        if nodes[-1] != depot_index:
            nodes.append(depot_index)
        for origin, dest in pairwise(nodes):
            total += estimated_arc_cost(
                distances_meters[origin][dest],
                durations_seconds[origin][dest],
                cost_per_km=cost_per_km,
                cost_per_hour=cost_per_hour,
            )
    return total


class OrToolsTspOptimizer(Optimizer):
    def __init__(
        self,
        *,
        time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
        depot_index: int = 0,
    ) -> None:
        if time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive")
        if depot_index < 0:
            raise ValueError("depot_index must be >= 0")
        self._time_limit_seconds = time_limit_seconds
        self._depot_index = depot_index

    @property
    def time_limit_seconds(self) -> float:
        return self._time_limit_seconds

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
        n = _require_square_matrices(durations_seconds, distances_meters)
        if self._depot_index >= n:
            raise ValueError("depot_index must be a matrix index")
        if vehicle_count < 1:
            raise ValueError("vehicle_count must be >= 1")
        if objective not in ("time", "cost"):
            raise ValueError("objective must be 'time' or 'cost'")
        if cost_per_km < 0 or cost_per_hour < 0:
            raise ValueError("cost rates must be >= 0")
        if vehicle_time_capacity_seconds is not None and vehicle_time_capacity_seconds <= 0:
            raise ValueError("vehicle_time_capacity_seconds must be positive")

        services = _normalize_service_times(service_times_seconds, n)
        windows = _normalize_windows(time_windows, n)
        horizon = _horizon_seconds(
            durations_seconds,
            services,
            windows,
            vehicle_time_capacity_seconds,
        )
        resolved_windows = [
            (0.0, horizon) if window is None else window for window in windows
        ]
        need_time = _needs_time_dimension(windows, vehicle_time_capacity_seconds)

        diagnostics = _diagnose_infeasibility(
            durations_seconds=durations_seconds,
            services=services,
            windows=resolved_windows,
            depot_index=self._depot_index,
            capacity=vehicle_time_capacity_seconds,
        )
        if _diagnostics_prove_infeasible(diagnostics, vehicle_count):
            return _infeasible_result(diagnostics)

        manager = pywrapcp.RoutingIndexManager(n, vehicle_count, self._depot_index)
        routing = pywrapcp.RoutingModel(manager)

        def cost_callback(from_index: int, to_index: int) -> int:
            origin = manager.IndexToNode(from_index)
            dest = manager.IndexToNode(to_index)
            if objective == "cost":
                return round(
                    estimated_arc_cost(
                        distances_meters[origin][dest],
                        durations_seconds[origin][dest],
                        cost_per_km=cost_per_km,
                        cost_per_hour=cost_per_hour,
                    )
                    * _COST_SCALE
                )
            return round(durations_seconds[origin][dest] * _MS_PER_SECOND)

        routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(cost_callback))

        if need_time:
            capacity_ms = round(
                (vehicle_time_capacity_seconds or horizon) * _MS_PER_SECOND
            )
            slack_ms = capacity_ms

            def time_callback(from_index: int, to_index: int) -> int:
                origin = manager.IndexToNode(from_index)
                dest = manager.IndexToNode(to_index)
                return round(
                    (durations_seconds[origin][dest] + services[origin]) * _MS_PER_SECOND
                )

            time_cb = routing.RegisterTransitCallback(time_callback)
            routing.AddDimension(time_cb, slack_ms, capacity_ms, True, _TIME_DIMENSION)
            time_dim = routing.GetDimensionOrDie(_TIME_DIMENSION)
            _apply_time_windows(
                routing,
                manager,
                time_dim,
                resolved_windows,
                vehicle_count=vehicle_count,
                depot_index=self._depot_index,
                capacity_seconds=vehicle_time_capacity_seconds or horizon,
            )

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        if need_time or vehicle_count > 1:
            search_parameters.first_solution_strategy = (
                routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
            )
        else:
            search_parameters.first_solution_strategy = (
                routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            )
        millis = max(1, round(self._time_limit_seconds * _MS_PER_SECOND))
        search_parameters.time_limit.seconds = millis // _MS_PER_SECOND
        search_parameters.time_limit.nanos = (millis % _MS_PER_SECOND) * 1_000_000

        solution = routing.SolveWithParameters(search_parameters)
        status = routing_status_name(routing.status())
        if solution is None:
            if not diagnostics:
                diagnostics = _diagnose_infeasibility(
                    durations_seconds=durations_seconds,
                    services=services,
                    windows=resolved_windows,
                    depot_index=self._depot_index,
                    capacity=vehicle_time_capacity_seconds,
                )
            return _infeasible_result(diagnostics, status=status)

        routes = _collect_routes(manager, routing, solution, vehicle_count)
        if not _routes_are_complete(routes, n, self._depot_index):
            return _infeasible_result(diagnostics, status=status)
        if not _routes_respect_windows(
            routes,
            durations_seconds=durations_seconds,
            services=services,
            windows=resolved_windows,
            depot_index=self._depot_index,
            capacity=vehicle_time_capacity_seconds,
        ):
            return _infeasible_result(diagnostics, status="ROUTING_INFEASIBLE")

        scale = _COST_SCALE if objective == "cost" else _MS_PER_SECOND
        order = _flatten_order(routes, self._depot_index)
        service_duration = _service_duration(services, self._depot_index)
        return OptimizationResult(
            order=order,
            solver_status=status,
            objective_value=solution.ObjectiveValue() / scale,
            estimated_cost=estimated_routes_cost(
                distances_meters,
                durations_seconds,
                routes,
                depot_index=self._depot_index,
                cost_per_km=cost_per_km,
                cost_per_hour=cost_per_hour,
            ),
            service_duration_seconds=service_duration,
            routes=routes,
        )


def _require_square_matrices(
    durations_seconds: list[list[float]], distances_meters: list[list[float]]
) -> int:
    n = len(durations_seconds)
    if n == 0:
        raise ValueError("duration matrix must not be empty")
    if any(len(row) != n for row in durations_seconds):
        raise ValueError("duration matrix must be square")
    if len(distances_meters) != n or any(len(row) != n for row in distances_meters):
        raise ValueError("distance matrix must be square and match durations")
    return n


def _normalize_service_times(service_times_seconds: list[float] | None, n: int) -> list[float]:
    if service_times_seconds is None:
        return [0.0] * n
    if len(service_times_seconds) != n:
        raise ValueError("service_times_seconds must match matrix size")
    if any(t < 0 for t in service_times_seconds):
        raise ValueError("service times must be >= 0")
    return [float(t) for t in service_times_seconds]


def _normalize_windows(
    time_windows: list[tuple[float, float] | None] | None, n: int
) -> list[tuple[float, float] | None]:
    if time_windows is None:
        return [None] * n
    if len(time_windows) != n:
        raise ValueError("time_windows must match matrix size")
    normalized: list[tuple[float, float] | None] = []
    for window in time_windows:
        if window is None:
            normalized.append(None)
            continue
        start, end = window
        if start < 0 or end < 0 or start > end:
            raise ValueError("time windows must satisfy 0 <= start <= end")
        normalized.append((float(start), float(end)))
    return normalized


def _horizon_seconds(
    durations_seconds: list[list[float]],
    services: list[float],
    windows: list[tuple[float, float] | None],
    capacity: float | None,
) -> float:
    if capacity is not None:
        return capacity
    span = sum(max(row) for row in durations_seconds) + sum(services)
    closed_ends = [window[1] for window in windows if window is not None]
    max_end = max(closed_ends) if closed_ends else 0.0
    return max(span, max_end, 1.0)


def _needs_time_dimension(
    windows: list[tuple[float, float] | None],
    capacity: float | None,
) -> bool:
    if capacity is not None:
        return True
    return any(window is not None for window in windows)


def _apply_time_windows(
    routing: pywrapcp.RoutingModel,
    manager: pywrapcp.RoutingIndexManager,
    time_dim: pywrapcp.RoutingDimension,
    windows: list[tuple[float, float]],
    *,
    vehicle_count: int,
    depot_index: int,
    capacity_seconds: float,
) -> None:
    depot_window = windows[depot_index]
    depot_lo = round(depot_window[0] * _MS_PER_SECOND)
    depot_hi = round(min(depot_window[1], capacity_seconds) * _MS_PER_SECOND)
    for vehicle in range(vehicle_count):
        time_dim.CumulVar(routing.Start(vehicle)).SetRange(depot_lo, depot_hi)
        time_dim.CumulVar(routing.End(vehicle)).SetRange(depot_lo, depot_hi)
    for node, (start, end) in enumerate(windows):
        if node == depot_index:
            continue
        index = manager.NodeToIndex(node)
        lo = round(start * _MS_PER_SECOND)
        hi = round(min(end, capacity_seconds) * _MS_PER_SECOND)
        time_dim.CumulVar(index).SetRange(lo, hi)


def _collect_routes(
    manager: pywrapcp.RoutingIndexManager,
    routing: pywrapcp.RoutingModel,
    solution: pywrapcp.Assignment,
    vehicle_count: int,
) -> list[list[int]]:
    routes: list[list[int]] = []
    for vehicle in range(vehicle_count):
        index = routing.Start(vehicle)
        route: list[int] = []
        while not routing.IsEnd(index):
            route.append(manager.IndexToNode(index))
            index = solution.Value(routing.NextVar(index))
        if len(route) > 1:
            routes.append(route)
    if not routes:
        routes.append([manager.IndexToNode(routing.Start(0))])
    return routes


def _flatten_order(routes: list[list[int]], depot_index: int) -> list[int]:
    if len(routes) == 1:
        return list(routes[0])
    order = [depot_index]
    seen = {depot_index}
    for route in routes:
        for node in route:
            if node not in seen:
                order.append(node)
                seen.add(node)
    return order


def _routes_are_complete(routes: list[list[int]], n: int, depot_index: int) -> bool:
    routed = {node for route in routes for node in route}
    return routed == set(range(n)) or routed | {depot_index} == set(range(n))


def _routes_respect_windows(
    routes: list[list[int]],
    *,
    durations_seconds: list[list[float]],
    services: list[float],
    windows: list[tuple[float, float]],
    depot_index: int,
    capacity: float | None,
) -> bool:
    for route in routes:
        customers = [node for node in route if node != depot_index]
        if not _can_serve_chain(
            customers,
            durations_seconds=durations_seconds,
            services=services,
            windows=windows,
            depot_index=depot_index,
            capacity=capacity,
        ):
            return False
    return True


def _can_serve_chain(
    nodes: Sequence[int],
    *,
    durations_seconds: list[list[float]],
    services: list[float],
    windows: list[tuple[float, float]],
    depot_index: int,
    capacity: float | None,
) -> bool:
    time = 0.0
    prev = depot_index
    for node in nodes:
        time += durations_seconds[prev][node]
        start, end = windows[node]
        time = max(time, start)
        if time > end:
            return False
        time += services[node]
        if capacity is not None and time > capacity:
            return False
        prev = node
    time += durations_seconds[prev][depot_index]
    return capacity is None or time <= capacity


def _classify_single_stop(
    node: int,
    *,
    durations_seconds: list[list[float]],
    services: list[float],
    windows: list[tuple[float, float]],
    depot_index: int,
    capacity: float | None,
) -> str | None:
    arrival = durations_seconds[depot_index][node]
    start, end = windows[node]
    if arrival > end:
        return ISOLATED_STOP
    service_start = max(arrival, start)
    if service_start > end:
        return ISOLATED_STOP
    if _can_serve_chain(
        [node],
        durations_seconds=durations_seconds,
        services=services,
        windows=windows,
        depot_index=depot_index,
        capacity=None,
    ):
        if capacity is not None and not _can_serve_chain(
            [node],
            durations_seconds=durations_seconds,
            services=services,
            windows=windows,
            depot_index=depot_index,
            capacity=capacity,
        ):
            return INSUFFICIENT_SHIFT
        return None
    if capacity is not None:
        return INSUFFICIENT_SHIFT
    return ISOLATED_STOP


def _diagnose_infeasibility(
    *,
    durations_seconds: list[list[float]],
    services: list[float],
    windows: list[tuple[float, float]],
    depot_index: int,
    capacity: float | None,
) -> list[InfeasibilityDiagnostic]:
    diagnostics: list[InfeasibilityDiagnostic] = []
    n = len(durations_seconds)
    customers = [node for node in range(n) if node != depot_index]
    individually_feasible: list[int] = []
    for node in customers:
        code = _classify_single_stop(
            node,
            durations_seconds=durations_seconds,
            services=services,
            windows=windows,
            depot_index=depot_index,
            capacity=capacity,
        )
        if code is None:
            individually_feasible.append(node)
            continue
        diagnostics.append(
            InfeasibilityDiagnostic(
                code=code,
                node_indices=(node,),
                detail=_single_stop_detail(code, node),
            )
        )

    for i, origin in enumerate(individually_feasible):
        for dest in individually_feasible[i + 1 :]:
            either_order = _can_serve_chain(
                [origin, dest],
                durations_seconds=durations_seconds,
                services=services,
                windows=windows,
                depot_index=depot_index,
                capacity=capacity,
            ) or _can_serve_chain(
                [dest, origin],
                durations_seconds=durations_seconds,
                services=services,
                windows=windows,
                depot_index=depot_index,
                capacity=capacity,
            )
            if either_order:
                continue
            windows_only = _can_serve_chain(
                [origin, dest],
                durations_seconds=durations_seconds,
                services=services,
                windows=windows,
                depot_index=depot_index,
                capacity=None,
            ) or _can_serve_chain(
                [dest, origin],
                durations_seconds=durations_seconds,
                services=services,
                windows=windows,
                depot_index=depot_index,
                capacity=None,
            )
            code = INSUFFICIENT_SHIFT if windows_only else INCOMPATIBLE_WINDOWS
            diagnostics.append(
                InfeasibilityDiagnostic(
                    code=code,
                    node_indices=(origin, dest),
                    detail=_pair_detail(code, origin, dest),
                )
            )
    return diagnostics


def _diagnostics_prove_infeasible(
    diagnostics: list[InfeasibilityDiagnostic], vehicle_count: int
) -> bool:
    isolated_or_shift = any(
        item.code in {ISOLATED_STOP, INSUFFICIENT_SHIFT} and len(item.node_indices) == 1
        for item in diagnostics
    )
    single_vehicle_conflict = vehicle_count == 1 and any(
        item.code in {INCOMPATIBLE_WINDOWS, INSUFFICIENT_SHIFT} for item in diagnostics
    )
    return isolated_or_shift or single_vehicle_conflict


def _single_stop_detail(code: str, node: int) -> str:
    if code == ISOLATED_STOP:
        return f"Stop {node} cannot be reached from the depot within its time window."
    return f"Stop {node} exceeds the vehicle time capacity even as a single visit."


def _pair_detail(code: str, origin: int, dest: int) -> str:
    if code == INCOMPATIBLE_WINDOWS:
        return (
            f"Stops {origin} and {dest} cannot both be served: travel exceeds the second window."
        )
    return f"Stops {origin} and {dest} fit their windows but exceed the vehicle time capacity together."


def _infeasible_result(
    diagnostics: list[InfeasibilityDiagnostic],
    *,
    status: str | None = None,
) -> OptimizationResult:
    solver_status = "ROUTING_INFEASIBLE"
    if status in {"ROUTING_INFEASIBLE", "ROUTING_FAIL", "ROUTING_FAIL_TIMEOUT", "ROUTING_INVALID"}:
        solver_status = "ROUTING_INFEASIBLE" if diagnostics else status
    elif status is not None and not diagnostics:
        solver_status = status
    return OptimizationResult(
        order=[],
        solver_status=solver_status,
        objective_value=0.0,
        diagnostics=list(diagnostics),
        estimated_cost=0.0,
        service_duration_seconds=0.0,
        routes=[],
    )


def _service_duration(services: list[float], depot_index: int) -> float:
    return sum(duration for node, duration in enumerate(services) if node != depot_index)
