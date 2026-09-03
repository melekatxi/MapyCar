"""Casos sintéticos de clustering con óptimo conocido y semilla fija. Ref: 2.QA.2, RF-11, RF-12."""

from __future__ import annotations

from collections.abc import Sequence
from math import ceil, hypot

from app.modules.zoning.clustering import RURAL_EPS_M, ClusteringResult, cluster_points
from app.modules.zoning.features import PointFeatures, ZoningPoint, compute_features

_RNG_SEED = 0
_MAX_VISITS = 10

_DEPOT = ZoningPoint(
    longitude=-2.9348,
    latitude=43.2630,
    point_id="depot",
    municipality="Bilbao",
    postal_code="48001",
)

# Grids densos: paso ~67 m → diámetro de 10–25 puntos << 500 m → kind urbano.
_URBAN_STEP_DEG = 0.0006
# Hamlet rural: ~90 m entre vecinos, << RURAL_EPS_M y dentro de DENSITY_RADIUS_M.
# 3 puntos → density=3 < umbral urbano (4) → kind rural.
_RURAL_STEP_DEG = 0.0008

# Caseríos de Bizkaia a decenas de km: intra-hamlet << 2.5 km; inter-grupo >> 2.5 km.
_HAMLET_ORIGINS = (
    ("hamlet-karrantza", -3.3630, 43.2210, "Karrantza Harana", "48891"),
    ("hamlet-orduna", -3.0095, 42.9947, "Orduña", "48460"),
    ("hamlet-lekeitio", -2.4961, 43.3625, "Lekeitio", "48280"),
)
_ISOLATES = (
    ZoningPoint(
        longitude=-2.7214,
        latitude=43.4208,
        point_id="isolate-bermeo",
        municipality="Bermeo",
        postal_code="48370",
    ),
    ZoningPoint(
        longitude=-2.6547,
        latitude=43.0394,
        point_id="isolate-otxandio",
        municipality="Otxandio",
        postal_code="48210",
    ),
)


def _grid(
    n: int,
    *,
    origin_lon: float,
    origin_lat: float,
    id_prefix: str,
    municipality: str | None = None,
    postal_code: str | None = None,
    step_deg: float = _URBAN_STEP_DEG,
) -> list[ZoningPoint]:
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


def _two_urban_blobs() -> list[ZoningPoint]:
    # Mismo municipio/CP: 20 > max_visits, no hay semilla admin; K-means debe recuperar los blobs.
    return [
        *_grid(
            10,
            origin_lon=-2.9348,
            origin_lat=43.2630,
            id_prefix="blob-a",
            municipality="Bilbao",
            postal_code="48001",
        ),
        *_grid(
            10,
            origin_lon=-3.0110,
            origin_lat=43.3430,
            id_prefix="blob-b",
            municipality="Bilbao",
            postal_code="48001",
        ),
    ]


def _one_urban_blob(n: int = 25) -> list[ZoningPoint]:
    return _grid(
        n,
        origin_lon=-2.9348,
        origin_lat=43.2630,
        id_prefix="urban",
        municipality="Bilbao",
        postal_code="48001",
    )


def _rural_hamlets_and_isolates() -> list[ZoningPoint]:
    points: list[ZoningPoint] = []
    for prefix, lon, lat, municipality, postal_code in _HAMLET_ORIGINS:
        points.extend(
            _grid(
                3,
                origin_lon=lon,
                origin_lat=lat,
                id_prefix=prefix,
                municipality=municipality,
                postal_code=postal_code,
                step_deg=_RURAL_STEP_DEG,
            )
        )
    points.extend(_ISOLATES)
    return points


def _cluster(
    points: list[ZoningPoint],
    *,
    max_visits: int,
    rng_seed: int = _RNG_SEED,
) -> tuple[ClusteringResult, list[PointFeatures]]:
    features = compute_features(points, _DEPOT)
    return cluster_points(features, max_visits=max_visits, rng_seed=rng_seed), features


def _ids(features: Sequence[PointFeatures]) -> set[str]:
    return {item.point_id for item in features if item.point_id}


def _sizes(result: ClusteringResult) -> list[int]:
    return sorted(len(cluster.member_ids) for cluster in result.clusters)


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


def _xy(features: Sequence[PointFeatures], point_id: str) -> tuple[float, float]:
    match = next(item for item in features if item.point_id == point_id)
    assert match.x is not None and match.y is not None
    return match.x, match.y


def _max_pair_distance_m(features: Sequence[PointFeatures], ids: Sequence[str]) -> float:
    coords = [_xy(features, point_id) for point_id in ids]
    return max(
        hypot(ax - bx, ay - by)
        for index, (ax, ay) in enumerate(coords)
        for bx, by in coords[index + 1 :]
    )


def _min_cross_distance_m(
    features: Sequence[PointFeatures], left_ids: Sequence[str], right_ids: Sequence[str]
) -> float:
    left = [_xy(features, point_id) for point_id in left_ids]
    right = [_xy(features, point_id) for point_id in right_ids]
    return min(hypot(ax - bx, ay - by) for ax, ay in left for bx, by in right)


def test_two_separated_urban_blobs_recover_known_optimum_with_seed_zero() -> None:
    result, features = _cluster(_two_urban_blobs(), max_visits=_MAX_VISITS)
    blob_a = frozenset(f"blob-a-{index}" for index in range(10))
    blob_b = frozenset(f"blob-b-{index}" for index in range(10))

    assert all(item.kind == "urban" for item in features)
    _assert_capacity(result, _MAX_VISITS)
    _assert_partition(result, set(blob_a | blob_b))
    assert result.outliers == ()
    assert len(result.clusters) == 2
    assert _sizes(result) == [10, 10]
    assert {frozenset(cluster.member_ids) for cluster in result.clusters} == {blob_a, blob_b}
    assert all(cluster.kind == "urban" for cluster in result.clusters)


def test_single_urban_blob_splits_to_capacity_floor_with_seed_zero() -> None:
    n = 25
    result, features = _cluster(_one_urban_blob(n), max_visits=_MAX_VISITS)
    expected_k = ceil(n / _MAX_VISITS)

    assert all(item.kind == "urban" for item in features)
    _assert_capacity(result, _MAX_VISITS)
    _assert_partition(result, _ids(features))
    assert result.outliers == ()
    assert len(result.clusters) == expected_k == 3
    assert all(size <= _MAX_VISITS for size in _sizes(result))
    assert sum(_sizes(result)) == n
    assert all(cluster.kind == "urban" for cluster in result.clusters)


def test_rural_hamlets_cluster_and_isolated_points_stay_outliers() -> None:
    result, features = _cluster(_rural_hamlets_and_isolates(), max_visits=_MAX_VISITS)
    hamlets = [tuple(f"{prefix}-{index}" for index in range(3)) for prefix, *_ in _HAMLET_ORIGINS]
    isolate_ids = tuple(point.point_id for point in _ISOLATES if point.point_id)

    assert all(item.kind == "rural" for item in features)
    for hamlet in hamlets:
        assert _max_pair_distance_m(features, hamlet) < RURAL_EPS_M
    for left, right in (
        (hamlets[0], hamlets[1]),
        (hamlets[0], hamlets[2]),
        (hamlets[1], hamlets[2]),
        (hamlets[0], isolate_ids),
        (hamlets[1], isolate_ids),
        (hamlets[2], isolate_ids),
        (isolate_ids[:1], isolate_ids[1:]),
    ):
        assert _min_cross_distance_m(features, left, right) > RURAL_EPS_M

    _assert_capacity(result, _MAX_VISITS)
    _assert_partition(result, _ids(features))
    assert len(result.clusters) == 3
    assert _sizes(result) == [3, 3, 3]
    assert {cluster.member_ids for cluster in result.clusters} == {
        tuple(sorted(h)) for h in hamlets
    }
    assert result.outliers == tuple(sorted(isolate_ids))
    assert all(cluster.kind == "rural" for cluster in result.clusters)


def test_same_inputs_and_seed_yield_identical_membership() -> None:
    points = [*_two_urban_blobs(), *_one_urban_blob(25), *_rural_hamlets_and_isolates()]
    first, _ = _cluster(points, max_visits=_MAX_VISITS, rng_seed=_RNG_SEED)
    second, _ = _cluster(points, max_visits=_MAX_VISITS, rng_seed=_RNG_SEED)
    third, _ = _cluster(points, max_visits=_MAX_VISITS, rng_seed=_RNG_SEED)

    assert first == second == third
    assert {cluster.member_ids for cluster in first.clusters} == {
        cluster.member_ids for cluster in second.clusters
    }
    assert first.outliers == second.outliers


def test_max_visits_never_exceeded_on_synthetic_cases() -> None:
    cases = (
        (_two_urban_blobs(), 10),
        (_one_urban_blob(25), 10),
        (_one_urban_blob(25), 7),
        (_rural_hamlets_and_isolates(), 10),
        (_rural_hamlets_and_isolates(), 2),
        ([*_two_urban_blobs(), *_rural_hamlets_and_isolates()], 5),
        ([*_one_urban_blob(25), *_rural_hamlets_and_isolates()], 1),
    )
    for points, max_visits in cases:
        result, features = _cluster(points, max_visits=max_visits)
        _assert_capacity(result, max_visits)
        _assert_partition(result, _ids(features))
        assert sum(len(cluster.member_ids) for cluster in result.clusters) + len(
            result.outliers
        ) == len(features)
        assert all(len(cluster.member_ids) <= max_visits for cluster in result.clusters)
