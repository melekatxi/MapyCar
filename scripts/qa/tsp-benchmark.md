# Benchmark de TSP OR-Tools (RNF-02 / 3.QA.1)

| Campo | Valor |
|---|---|
| Fecha | 2026-08-30 |
| Script | [benchmark_tsp.py](benchmark_tsp.py) |
| Instancia | `OrToolsTspOptimizer` (OR-Tools Routing, un vehículo, sin ventanas). Matriz euclídea sintética 25×25; **sin** HTTP, **sin** OSRM. |
| Parámetros | N=30 solves, 25 paradas, semilla `20260830`, `time_limit_seconds=10` (límite del solver, inferior al SLA de 15 s) |
| Hardware | `uname -m`: **x86_64**; CPU (`/proc/cpuinfo` primer `model name`): **12th Gen Intel(R) Core(TM) i7-12700H** (20 hilos); RAM (`MemTotal`): **31.0 GiB** |

## Resultado

| Métrica | Valor |
|---|---|
| p50 | 0.0167 s |
| **p95** | **0.0266 s** |
| max | 0.0289 s |
| `solver_status` | `ROUTING_SUCCESS` × 30 |

Criterio RNF-02 / 3.QA.1 ("p95 de optimización con hasta 25 paradas < 15 s"): **cumplido** (p95 ≈ 0.027 s, ~560× por debajo del límite).

`ROUTING_SUCCESS` acredita solución factible, no optimalidad matemática (`ROUTING_OPTIMAL`). Ver docstring de `ortools_tsp.py`.

## Reproducir

Desde la raíz del repositorio:

```bash
PYTHONPATH=backend backend/.venv/bin/python scripts/qa/benchmark_tsp.py -n 30
```

Opcional: `-n 20`, `--seed`, `--stops`, `--time-limit`. El p95 documentado arriba es el criterio de aceptación; CI cubre un smoke N=5 en `backend/tests/test_optimizer_tsp.py` (`test_p95_of_five_twenty_five_stop_solves_under_sla`).

## Qué no mide este benchmark

- Matriz OSRM `/table` (3.BE.2) ni latencia de red.
- Endpoint HTTP `POST /routes/{id}/optimize` (3.BE.7).
- VRPTW, ventanas ni varios vehículos (3.BE.4).
