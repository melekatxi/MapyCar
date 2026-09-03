"""Benchmark p95 de TSP OR-Tools (25 paradas euclídeas). Ref: RNF-02, 3.QA.1.

Mide el adaptador `OrToolsTspOptimizer` sobre matrices euclídeas sintéticas.
No llama HTTP ni OSRM: el criterio de aceptación es el informe documentado
(`scripts/qa/tsp-benchmark.md`) con N=30 en hardware de referencia.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from collections import Counter
from collections.abc import Sequence
from math import hypot
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.adapters.optimizer.ortools_tsp import (
    DEFAULT_TIME_LIMIT_SECONDS,
    OrToolsTspOptimizer,
)

SLA_SECONDS = 15.0
STOPS = 25
DEFAULT_N = 30
DEFAULT_SEED = 20260830
_FAILED_STATUSES = frozenset({"ROUTING_NOT_SOLVED", "ROUTING_FAIL"})


def euclidean_matrix(points: Sequence[tuple[float, float]]) -> list[list[float]]:
    n = len(points)
    matrix = [[0.0] * n for _ in range(n)]
    for i, (xi, yi) in enumerate(points):
        for j, (xj, yj) in enumerate(points):
            matrix[i][j] = hypot(xi - xj, yi - yj)
    return matrix


def random_points(n: int, rng: random.Random) -> list[tuple[float, float]]:
    return [(rng.random() * 100.0, rng.random() * 100.0) for _ in range(n)]


def linear_percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if not 0.0 <= pct <= 100.0:
        raise ValueError("pct must be in [0, 100]")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def read_hardware() -> dict[str, str]:
    machine = os.uname().machine
    cpu = _cpu_model() or "unknown"
    ram = _ram_gib() or "unknown"
    return {"machine": machine, "cpu": cpu, "ram": ram}


def _cpu_model() -> str | None:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def _ram_gib() -> str | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                kib = int(line.split()[1])
                return f"{kib / 1024 / 1024:.1f} GiB"
    except (OSError, ValueError, IndexError):
        return None
    return None


def run_solves(
    *,
    n: int,
    stops: int = STOPS,
    seed: int = DEFAULT_SEED,
    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
) -> tuple[list[float], list[str]]:
    optimizer = OrToolsTspOptimizer(time_limit_seconds=time_limit_seconds)
    elapsed_s: list[float] = []
    statuses: list[str] = []
    for i in range(n):
        points = random_points(stops, random.Random(seed + i))
        durations = euclidean_matrix(points)
        started = time.perf_counter()
        result = optimizer.solve(durations_seconds=durations, distances_meters=durations)
        elapsed_s.append(time.perf_counter() - started)
        statuses.append(result.solver_status)
        if result.solver_status in _FAILED_STATUSES:
            raise RuntimeError(f"solve {i} failed with solver_status={result.solver_status}")
        if len(result.order) != stops:
            raise RuntimeError(f"solve {i} returned {len(result.order)} stops, expected {stops}")
    return elapsed_s, statuses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-n", type=int, default=DEFAULT_N, help="número de solves (default 30)")
    parser.add_argument("--stops", type=int, default=STOPS, help="paradas por instancia (default 25)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="semilla de puntos euclídeos")
    parser.add_argument(
        "--time-limit",
        type=float,
        default=DEFAULT_TIME_LIMIT_SECONDS,
        help="límite del solver en segundos (default 10)",
    )
    args = parser.parse_args(argv)
    if args.n < 1:
        parser.error("-n must be >= 1")
    if args.stops < 2:
        parser.error("--stops must be >= 2")

    hardware = read_hardware()
    elapsed_s, statuses = run_solves(
        n=args.n,
        stops=args.stops,
        seed=args.seed,
        time_limit_seconds=args.time_limit,
    )
    p50 = linear_percentile(elapsed_s, 50)
    p95 = linear_percentile(elapsed_s, 95)
    max_s = max(elapsed_s)
    status_counts = ", ".join(f"{name}={count}" for name, count in sorted(Counter(statuses).items()))
    passed = p95 < SLA_SECONDS

    print(f"N={args.n}  stops={args.stops}  seed={args.seed}  time_limit={args.time_limit}s")
    print(f"hardware: {hardware['machine']} | {hardware['cpu']} | RAM {hardware['ram']}")
    print(f"p50={p50:.4f}s  p95={p95:.4f}s  max={max_s:.4f}s")
    print(f"solver_status: {status_counts}")
    print(f"samples_s: {', '.join(f'{t:.4f}' for t in elapsed_s)}")
    print(f"RNF-02 p95 < {SLA_SECONDS:.0f}s: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
