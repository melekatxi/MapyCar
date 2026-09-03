"""Clustering capacitado sobre fixtures urbano/rural de Bizkaia. Ref: 2.BE.3, RF-09, RF-11, RF-12."""

from __future__ import annotations

from math import ceil

import pytest

from app.modules.zoning.clustering import ClusteringResult, cluster_points
from app.modules.zoning.features import PointFeatures, ZoningPoint, compute_features

_RNG_SEED = 42

_DEPOT = ZoningPoint(
    longitude=-2.9348,
    latitude=43.2630,
    point_id="depot",
    municipality="Bilbao",
    postal_code="48001",
)

# Caseríos a decenas de km: Karrantza, Orduña, Bermeo, Lekeitio, Otxandio, Balmaseda.
_RURAL_POINTS = (
    ZoningPoint(
        longitude=-3.3630,
        latitude=43.2210,
        point_id="rural-karrantza",
        municipality="Karrantza Harana",
        postal_code="48891",
    ),
    ZoningPoint(
        longitude=-3.0095,
        latitude=42.9947,
        point_id="rural-orduna",
        municipality="Orduña",
        postal_code="48460",
    ),
    ZoningPoint(
        longitude=-2.7214,
        latitude=43.4208,
        point_id="rural-bermeo",
        municipality="Bermeo",
        postal_code="48370",
    ),
    ZoningPoint(
        longitude=-2.4961,
        latitude=43.3625,
        point_id="rural-lekeitio",
        municipality="Lekeitio",
        postal_code="48280",
    ),
    ZoningPoint(
        longitude=-2.6547,
        latitude=43.0394,
        point_id="rural-otxandio",
        municipality="Otxandio",
        postal_code="48210",
    ),
    ZoningPoint(
        longitude=-3.2000,
        latitude=43.1958,
        point_id="rural-balmaseda",
        municipality="Balmaseda",
        postal_code="48800",
    ),
)


def _urban_grid(
    n: int,
    *,
    origin_lon: float = -2.9348,
    origin_lat: float = 43.2630,
    municipality: str = "Bilbao",
    postal_code: str = "48001",
    id_prefix: str = "urban",
) -> list[ZoningPoint]:
    # ~67 m: grid denso dentro del radio de 500 m → kind urbano por densidad.
    step_deg = 0.0006
    cols = max(1, ceil(n**0.5))
    points: list[ZoningPoint] = []
    for index in range(n):
        row, col = divmod(index, cols)
        points.append(
            ZoningPoint(
                longitude=origin_lon + col * step_deg,
                latitude=origin_lat + row * step_deg,
                point_id=f"{id_prefix}-{index}",
                municipality=municipality,
                postal_code=postal_code,
            )
        )
    return points


def _cluster(
    points: list[ZoningPoint],
    *,
    max_visits: int,
    target_zones: int | None = None,
    rng_seed: int = _RNG_SEED,
) -> tuple[ClusteringResult, list[PointFeatures]]:
    features = compute_features(points, _DEPOT)
    return cluster_points(
        features, max_visits=max_visits, target_zones=target_zones, rng_seed=rng_seed
    ), features


def _assert_capacity(result: ClusteringResult, max_visits: int) -> None:
    for cluster in result.clusters:
        assert 1 <= len(cluster.member_ids) <= max_visits, cluster


def _assert_partition(result: ClusteringResult, expected_ids: set[str]) -> None:
    assigned: list[str] = []
    for cluster in result.clusters:
        assigned.extend(cluster.member_ids)
    assigned.extend(result.outliers)
    assert len(assigned) == len(set(assigned))
    assert set(assigned) == expected_ids


def test_urban_blob_respects_max_visits_and_has_enough_clusters() -> None:
    n, max_visits = 36, 5
    result, features = _cluster(_urban_grid(n), max_visits=max_visits)
    ids = {item.point_id for item in features if item.point_id}

    assert all(item.kind == "urban" for item in features)
    _assert_capacity(result, max_visits)
    _assert_partition(result, ids)
    assert result.outliers == ()
    assert len(result.clusters) >= ceil(n / max_visits)
    assert all(cluster.kind == "urban" for cluster in result.clusters)


def test_rural_scattered_points_are_outliers_or_singletons_not_one_giant_cluster() -> None:
    max_visits = 15
    result, features = _cluster(list(_RURAL_POINTS), max_visits=max_visits)
    ids = {item.point_id for item in features if item.point_id}

    assert all(item.kind == "rural" for item in features)
    _assert_capacity(result, max_visits)
    _assert_partition(result, ids)
    clustered = [cluster.member_ids for cluster in result.clusters]
    assert not (len(clustered) == 1 and len(clustered[0]) == len(_RURAL_POINTS))
    assert all(len(members) <= 2 for members in clustered)
    assert result.outliers or all(len(members) == 1 for members in clustered)
    assert all(cluster.kind == "rural" for cluster in result.clusters)


def test_mixed_urban_and_rural_are_not_forced_into_the_same_cluster() -> None:
    points = [*_urban_grid(16), *_RURAL_POINTS]
    result, features = _cluster(points, max_visits=6)
    by_id = {item.point_id: item for item in features if item.point_id}
    ids = set(by_id)

    _assert_capacity(result, 6)
    _assert_partition(result, ids)
    for cluster in result.clusters:
        kinds = {by_id[member_id].kind for member_id in cluster.member_ids}
        assert kinds in ({"urban"}, {"rural"})
        assert "urban" not in kinds or "rural" not in kinds


def test_capacity_never_exceeded_on_mixed_fixture() -> None:
    points = [*_urban_grid(25, id_prefix="urban-a"), *_RURAL_POINTS]
    result, features = _cluster(points, max_visits=4, target_zones=8)
    _assert_capacity(result, 4)
    _assert_partition(result, {item.point_id for item in features if item.point_id})


def test_municipality_seed_keeps_compact_towns_separate_when_under_capacity() -> None:
    points = [
        *_urban_grid(4, municipality="Bilbao", postal_code="48001", id_prefix="bilbao"),
        *_urban_grid(
            4,
            origin_lon=-3.0110,
            origin_lat=43.3430,
            municipality="Getxo",
            postal_code="48992",
            id_prefix="getxo",
        ),
    ]
    result, features = _cluster(points, max_visits=10)
    by_id = {item.point_id: item for item in features if item.point_id}

    assert all(item.kind == "urban" for item in features)
    assert len(result.clusters) == 2
    towns = [
        {by_id[member_id].municipality for member_id in cluster.member_ids}
        for cluster in result.clusters
    ]
    assert {"Bilbao"} in towns
    assert {"Getxo"} in towns


def test_missing_coordinates_are_skipped() -> None:
    valid, _ = _cluster(_urban_grid(8), max_visits=3)
    ghost = PointFeatures(
        point_id="no-coords",
        longitude=None,  # type: ignore[arg-type]
        latitude=None,  # type: ignore[arg-type]
        x=505_000.0,
        y=4_790_000.0,
        density=1,
        kind="urban",
        depot_distance_m=0.0,
        depot_time_minutes=0.0,
    )
    mixed = [*compute_features(_urban_grid(8), _DEPOT), ghost]
    result = cluster_points(mixed, max_visits=3, rng_seed=_RNG_SEED)
    assigned = {member_id for cluster in result.clusters for member_id in cluster.member_ids}
    assigned.update(result.outliers)
    assert "no-coords" not in assigned
    assert len(assigned) == 8
    assert {cluster.member_ids for cluster in result.clusters} == {
        cluster.member_ids for cluster in valid.clusters
    }


def test_same_seed_is_deterministic() -> None:
    points = [*_urban_grid(20), *_RURAL_POINTS]
    first, _ = _cluster(points, max_visits=5)
    second, _ = _cluster(points, max_visits=5)
    assert first == second


def test_empty_input_returns_empty_result() -> None:
    result = cluster_points([], max_visits=5, rng_seed=_RNG_SEED)
    assert result.clusters == ()
    assert result.outliers == ()


def test_max_visits_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_visits"):
        cluster_points([], max_visits=0)
