"""Matriz OSRM `/table` NxN con caché Redis. Ref: 3.BE.2, diseño 7.5 / 11.5."""

from __future__ import annotations

import math

import fakeredis
import pytest

from app.adapters.router.fake import FakeRouter
from app.adapters.router.interface import Coordinate, DistanceMatrix
from app.core.config import Settings
from app.modules.routing.matrix import (
    CACHE_KEY_PREFIX,
    IncompleteDistanceMatrixError,
    OsrmTableCache,
    assemble_table_coordinates,
    compute_matrix,
    hash_table_query,
    redis_cache_key,
)


class CountingRouter(FakeRouter):
    def __init__(self) -> None:
        self.table_calls = 0
        self.last_coordinates: list[Coordinate] | None = None

    async def table(self, coordinates: list[Coordinate]) -> DistanceMatrix:
        self.table_calls += 1
        self.last_coordinates = list(coordinates)
        return await super().table(coordinates)


class NoneCellRouter(FakeRouter):
    async def table(self, coordinates: list[Coordinate]) -> DistanceMatrix:
        matrix = await super().table(coordinates)
        durations = [list(row) for row in matrix.durations_seconds]
        durations[0][1] = None  # type: ignore[assignment]
        return DistanceMatrix(durations_seconds=durations, distances_meters=matrix.distances_meters)


def _cache() -> OsrmTableCache:
    return OsrmTableCache(fakeredis.FakeStrictRedis())


def _dummy_stops(count: int) -> tuple[Coordinate, list[Coordinate], Coordinate]:
    origin = Coordinate(43.26200123, -2.93456789)
    stops = [
        Coordinate(43.26 + i * 0.00123456, -2.93 - i * 0.00098765) for i in range(1, count + 1)
    ]
    return origin, stops, origin


def test_osrm_settings_defaults() -> None:
    settings = Settings()
    assert settings.osrm_profile == "driving"
    assert settings.osrm_dataset_version == "dev"


def test_assemble_table_coordinates_depot_first_and_last() -> None:
    origin = Coordinate(43.26, -2.93)
    stops = [Coordinate(43.27, -2.94), Coordinate(43.28, -2.95)]
    coords = assemble_table_coordinates(origin, stops)
    assert coords[0] is origin
    assert coords[-1] is origin
    assert coords[1:-1] == stops
    assert len(coords) == 4


def test_hash_changes_with_profile_and_dataset_version() -> None:
    coords = [Coordinate(43.26, -2.93), Coordinate(43.25, -2.92)]
    base = hash_table_query(coords, profile="driving", dataset_version="dev")
    other_profile = hash_table_query(coords, profile="walking", dataset_version="dev")
    other_extract = hash_table_query(coords, profile="driving", dataset_version="osm-2026")
    assert base != other_profile
    assert base != other_extract
    assert redis_cache_key(base).startswith(CACHE_KEY_PREFIX)


def test_hash_uses_rounded_coordinates() -> None:
    a = [Coordinate(43.260001, -2.930001), Coordinate(43.250001, -2.920001)]
    b = [Coordinate(43.260004, -2.930004), Coordinate(43.250004, -2.920004)]
    assert hash_table_query(a, profile="driving", dataset_version="dev") == hash_table_query(
        b, profile="driving", dataset_version="dev"
    )


@pytest.mark.asyncio
async def test_compute_matrix_25_stops_second_call_hits_cache() -> None:
    origin, stops, destination = _dummy_stops(25)
    coordinates = assemble_table_coordinates(origin, stops, destination)
    assert len(coordinates) == 27

    router = CountingRouter()
    cache = _cache()

    first = await compute_matrix(
        router, cache, coordinates, profile="driving", dataset_version="dev"
    )
    second = await compute_matrix(
        router, cache, coordinates, profile="driving", dataset_version="dev"
    )

    assert router.table_calls == 1
    assert first.from_cache is False
    assert second.from_cache is True
    assert first.matrix_hash == second.matrix_hash
    assert len(first.durations_seconds) == 27
    assert all(len(row) == 27 for row in first.durations_seconds)
    assert len(first.distances_meters) == 27
    assert first.durations_seconds == second.durations_seconds
    assert first.distances_meters == second.distances_meters
    assert router.last_coordinates == coordinates
    assert any(not math.isclose(c.latitude, round(c.latitude, 5)) for c in coordinates)


@pytest.mark.asyncio
async def test_compute_matrix_passes_unrounded_coords_to_router() -> None:
    origin = Coordinate(43.26200123, -2.93456789)
    stop = Coordinate(43.27123456, -2.94111222)
    coordinates = assemble_table_coordinates(origin, [stop], origin)
    router = CountingRouter()

    await compute_matrix(router, _cache(), coordinates, profile="driving", dataset_version="dev")

    assert router.last_coordinates == coordinates
    assert router.last_coordinates is not None
    assert router.last_coordinates[0].latitude == origin.latitude
    assert router.last_coordinates[0].longitude == origin.longitude


@pytest.mark.asyncio
async def test_none_cell_raises_incomplete_matrix_error() -> None:
    coordinates = assemble_table_coordinates(Coordinate(43.26, -2.93), [Coordinate(43.27, -2.94)])
    with pytest.raises(IncompleteDistanceMatrixError) as exc_info:
        await compute_matrix(
            NoneCellRouter(),
            _cache(),
            coordinates,
            profile="driving",
            dataset_version="dev",
        )
    assert exc_info.value.row == 0
    assert exc_info.value.column == 1


@pytest.mark.asyncio
async def test_incomplete_matrix_is_not_cached() -> None:
    coordinates = assemble_table_coordinates(Coordinate(43.26, -2.93), [Coordinate(43.27, -2.94)])
    cache = _cache()
    router = NoneCellRouter()
    with pytest.raises(IncompleteDistanceMatrixError):
        await compute_matrix(router, cache, coordinates, profile="driving", dataset_version="dev")

    counting = CountingRouter()
    result = await compute_matrix(
        counting, cache, coordinates, profile="driving", dataset_version="dev"
    )
    assert counting.table_calls == 1
    assert result.from_cache is False
