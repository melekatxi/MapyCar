"""Matriz OSRM `/table` NxN con caché Redis. Ref: 3.BE.2, diseño 7.5 / 11.5.

Convención de índices (depot primero y último):

    coordinates = [origin, stop1, stop2, ..., stopN, destination]

    0       origin (inicio de depósito)
    1..N    paradas en el orden de entrada
    N+1     destination (retorno; puede coincidir con origin)

Para 25 paradas la matriz es 27×27. El redondeo a 5 decimales aplica **solo**
a la clave de caché; `Router.table` recibe las coordenadas sin redondear.
Una celda nula o no finita aborta: inalcanzables bloquean publicar (7.5).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

import redis

from app.adapters.router.interface import Coordinate, DistanceMatrix, Router
from app.core.config import get_settings

COORD_DECIMALS = 5
CACHE_KEY_PREFIX = "sofia:osrm:table:"
CACHE_TTL_SECONDS = 60 * 60 * 24


class IncompleteDistanceMatrixError(Exception):
    """Matriz incompleta (None, no NxN o celda no finita). Bloquea publicación."""

    def __init__(
        self,
        message: str,
        *,
        row: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.row = row
        self.column = column


@dataclass(frozen=True)
class ComputedMatrix:
    durations_seconds: list[list[float]]
    distances_meters: list[list[float]]
    matrix_hash: str
    profile: str
    dataset_version: str
    from_cache: bool
    coordinates: tuple[Coordinate, ...]


def assemble_table_coordinates(
    origin: Coordinate,
    stops: Sequence[Coordinate],
    destination: Coordinate | None = None,
) -> list[Coordinate]:
    """[origin, stop1..stopN, destination]. Destination por defecto = origin."""
    return [origin, *list(stops), destination if destination is not None else origin]


def hash_table_query(
    coordinates: Sequence[Coordinate],
    *,
    profile: str,
    dataset_version: str,
) -> str:
    """SHA-256 de perfil + versión de extracto + coordenadas redondeadas a 5 decimales."""
    rounded = ";".join(
        f"{round(c.latitude, COORD_DECIMALS):.{COORD_DECIMALS}f},"
        f"{round(c.longitude, COORD_DECIMALS):.{COORD_DECIMALS}f}"
        for c in coordinates
    )
    payload = f"{profile}|{dataset_version}|{rounded}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def redis_cache_key(matrix_hash: str) -> str:
    return f"{CACHE_KEY_PREFIX}{matrix_hash}"


class OsrmTableCache:
    """Caché Redis de matrices OSRM. Valor JSON `{durations, distances}`, TTL 24 h."""

    def __init__(self, redis_client: redis.Redis, *, ttl_seconds: int = CACHE_TTL_SECONDS) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    def get(self, matrix_hash: str) -> DistanceMatrix | None:
        raw = self._redis.get(redis_cache_key(matrix_hash))
        if not raw:
            return None
        payload = json.loads(raw)
        return DistanceMatrix(
            durations_seconds=payload["durations"],
            distances_meters=payload["distances"],
        )

    def set(self, matrix_hash: str, matrix: DistanceMatrix) -> None:
        payload = {
            "durations": matrix.durations_seconds,
            "distances": matrix.distances_meters,
        }
        self._redis.set(redis_cache_key(matrix_hash), json.dumps(payload), ex=self._ttl_seconds)


def get_osrm_table_cache() -> OsrmTableCache:
    return OsrmTableCache(redis.Redis.from_url(get_settings().redis_url))


def _cell(value: object, row: int, column: int, *, kind: str) -> float:
    if value is None:
        raise IncompleteDistanceMatrixError(
            f"Celda {kind}[{row}][{column}] nula: parada inalcanzable",
            row=row,
            column=column,
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise IncompleteDistanceMatrixError(
            f"Celda {kind}[{row}][{column}] no numérica",
            row=row,
            column=column,
        ) from exc
    if not isfinite(number) or number < 0:
        raise IncompleteDistanceMatrixError(
            f"Celda {kind}[{row}][{column}] no finita o negativa",
            row=row,
            column=column,
        )
    return number


def require_complete_matrix(matrix: DistanceMatrix, size: int) -> DistanceMatrix:
    """Exige NxN sin celdas nulas. Distances y durations deben coincidir en tamaño."""
    durations = matrix.durations_seconds
    distances = matrix.distances_meters
    if len(durations) != size or len(distances) != size:
        raise IncompleteDistanceMatrixError(
            f"Matriz {len(durations)}x? / {len(distances)}x? distinta de {size}x{size}"
        )
    clean_durations: list[list[float]] = []
    clean_distances: list[list[float]] = []
    for i in range(size):
        dur_row = durations[i]
        dist_row = distances[i]
        if len(dur_row) != size or len(dist_row) != size:
            raise IncompleteDistanceMatrixError(
                f"Fila {i} incompleta: durations={len(dur_row)} distances={len(dist_row)}"
            )
        clean_durations.append([_cell(v, i, j, kind="durations") for j, v in enumerate(dur_row)])
        clean_distances.append([_cell(v, i, j, kind="distances") for j, v in enumerate(dist_row)])
    return DistanceMatrix(durations_seconds=clean_durations, distances_meters=clean_distances)


async def compute_matrix(
    router: Router,
    cache: OsrmTableCache,
    coordinates: Sequence[Coordinate],
    *,
    profile: str | None = None,
    dataset_version: str | None = None,
) -> ComputedMatrix:
    """NxN vía `Router.table`, cacheada por hash de coords redondeadas + perfil + extracto."""
    coords = list(coordinates)
    if len(coords) < 2:
        raise ValueError("La matriz requiere al menos origin y destination")
    settings = get_settings()
    resolved_profile = profile if profile is not None else settings.osrm_profile
    resolved_version = (
        dataset_version if dataset_version is not None else settings.osrm_dataset_version
    )
    matrix_hash = hash_table_query(
        coords, profile=resolved_profile, dataset_version=resolved_version
    )
    cached = cache.get(matrix_hash)
    if cached is not None:
        complete = require_complete_matrix(cached, len(coords))
        return ComputedMatrix(
            durations_seconds=complete.durations_seconds,
            distances_meters=complete.distances_meters,
            matrix_hash=matrix_hash,
            profile=resolved_profile,
            dataset_version=resolved_version,
            from_cache=True,
            coordinates=tuple(coords),
        )
    raw = await router.table(coords)
    complete = require_complete_matrix(raw, len(coords))
    cache.set(matrix_hash, complete)
    return ComputedMatrix(
        durations_seconds=complete.durations_seconds,
        distances_meters=complete.distances_meters,
        matrix_hash=matrix_hash,
        profile=resolved_profile,
        dataset_version=resolved_version,
        from_cache=False,
        coordinates=tuple(coords),
    )
