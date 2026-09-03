"""Cohesión viaria sobre clusters (OSRM via FakeRouter). Ref: 2.BE.4, diseño §7.3, ADR-10."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import hypot

import pytest

from app.adapters.router.fake import FakeRouter
from app.adapters.router.interface import Coordinate, DistanceMatrix
from app.modules.zoning.clustering import ClusteringResult, ZoneCluster
from app.modules.zoning.cohesion import (
    FALLBACK_ROUTER_TABLE_FAILED,
    apply_cohesion,
    mean_intra_cluster_minutes,
)
from app.modules.zoning.features import PointFeatures

# A está en Abando; B al este. P euclidiano-cerca de A, viario-cerca de B (barrera).
_A1 = PointFeatures(
    point_id="a1",
    longitude=-2.9348,
    latitude=43.2630,
    x=0.0,
    y=0.0,
    density=4,
    kind="urban",
    depot_distance_m=0.0,
    depot_time_minutes=0.0,
)
_A2 = PointFeatures(
    point_id="a2",
    longitude=-2.9338,
    latitude=43.2630,
    x=100.0,
    y=0.0,
    density=4,
    kind="urban",
    depot_distance_m=0.0,
    depot_time_minutes=0.0,
)
_P = PointFeatures(
    point_id="border-p",
    longitude=-2.9343,
    latitude=43.2630,
    x=50.0,
    y=0.0,
    density=4,
    kind="urban",
    depot_distance_m=0.0,
    depot_time_minutes=0.0,
)
_B1 = PointFeatures(
    point_id="b1",
    longitude=-2.8000,
    latitude=43.2630,
    x=10_000.0,
    y=0.0,
    density=4,
    kind="urban",
    depot_distance_m=0.0,
    depot_time_minutes=0.0,
)
_B2 = PointFeatures(
    point_id="b2",
    longitude=-2.7990,
    latitude=43.2630,
    x=10_100.0,
    y=0.0,
    density=4,
    kind="urban",
    depot_distance_m=0.0,
    depot_time_minutes=0.0,
)
_OUTLIER = PointFeatures(
    point_id="rural-iso",
    longitude=-3.3630,
    latitude=43.2210,
    x=-30_000.0,
    y=-5_000.0,
    density=1,
    kind="rural",
    depot_distance_m=0.0,
    depot_time_minutes=0.0,
)

_NEAR_S = 60.0
_FAR_S = 600.0
_ROAD_SECONDS = {
    ("a1", "a2"): _NEAR_S,
    ("a1", "border-p"): _FAR_S,
    ("a2", "border-p"): _FAR_S,
    ("b1", "b2"): _NEAR_S,
    ("b1", "border-p"): _NEAR_S,
    ("b2", "border-p"): _NEAR_S,
}


class _PairRouter(FakeRouter):
    """FakeRouter con duraciones por point_id. No llama a OSRM."""

    def __init__(
        self,
        points: Sequence[PointFeatures],
        pairwise_seconds: Mapping[tuple[str, str], float],
        *,
        default_seconds: float = _FAR_S,
    ) -> None:
        self._id_by_coord = {
            (point.latitude, point.longitude): point.point_id for point in points if point.point_id
        }
        self._pairwise = dict(pairwise_seconds)
        self._default = default_seconds

    def duration(self, left: str, right: str) -> float:
        if left == right:
            return 0.0
        if (left, right) in self._pairwise:
            return self._pairwise[(left, right)]
        if (right, left) in self._pairwise:
            return self._pairwise[(right, left)]
        return self._default

    async def table(self, coordinates: list[Coordinate]) -> DistanceMatrix:
        ids = [self._id_by_coord[(coord.latitude, coord.longitude)] for coord in coordinates]
        n = len(ids)
        durations = [[self.duration(ids[i], ids[j]) for j in range(n)] for i in range(n)]
        distances = [[value * 10.0 for value in row] for row in durations]
        return DistanceMatrix(durations_seconds=durations, distances_meters=distances)


class _FailingRouter(FakeRouter):
    async def table(self, coordinates: list[Coordinate]) -> DistanceMatrix:
        raise RuntimeError("osrm down")


def _cluster(
    a_members: tuple[str, ...],
    b_members: tuple[str, ...],
    *,
    outliers: tuple[str, ...] = (),
    a_kind: str = "urban",
    b_kind: str = "urban",
) -> ClusteringResult:
    points = {
        point.point_id: point for point in (_A1, _A2, _P, _B1, _B2, _OUTLIER) if point.point_id
    }
    return ClusteringResult(
        clusters=(
            ZoneCluster(
                cluster_id="urban-0",
                kind=a_kind,
                member_ids=tuple(sorted(a_members)),
                centroid_xy=_centroid(a_members, points),
            ),
            ZoneCluster(
                cluster_id="urban-1" if b_kind == "urban" else "rural-0",
                kind=b_kind,
                member_ids=tuple(sorted(b_members)),
                centroid_xy=_centroid(b_members, points),
            ),
        ),
        outliers=outliers,
    )


def _centroid(
    member_ids: tuple[str, ...], points: Mapping[str, PointFeatures]
) -> tuple[float, float]:
    n = len(member_ids)
    return (
        sum(points[member_id].x for member_id in member_ids) / n,
        sum(points[member_id].y for member_id in member_ids) / n,
    )


def _misassigned() -> tuple[ClusteringResult, list[PointFeatures], _PairRouter]:
    clustering = _cluster(("a1", "a2", "border-p"), ("b1", "b2"), outliers=("rural-iso",))
    points = [_A1, _A2, _P, _B1, _B2, _OUTLIER]
    return clustering, points, _PairRouter(points, _ROAD_SECONDS)


def _euclidean_to_centroid(point: PointFeatures, member_ids: tuple[str, ...]) -> float:
    points = {item.point_id: item for item in (_A1, _A2, _P, _B1, _B2) if item.point_id}
    cx, cy = _centroid(member_ids, points)
    return hypot(point.x - cx, point.y - cy)


def _assert_capacity(clustering: ClusteringResult, max_visits: int) -> None:
    for cluster in clustering.clusters:
        assert 1 <= len(cluster.member_ids) <= max_visits, cluster


def _membership(clustering: ClusteringResult) -> dict[str, frozenset[str]]:
    return {cluster.cluster_id: frozenset(cluster.member_ids) for cluster in clustering.clusters}


@pytest.mark.asyncio
async def test_road_distance_reassigns_border_and_reduces_mean_minutes() -> None:
    clustering, points, router = _misassigned()
    max_visits = 3

    assert _euclidean_to_centroid(_P, ("a1", "a2")) < _euclidean_to_centroid(_P, ("b1", "b2"))
    before = mean_intra_cluster_minutes(clustering, router.duration)

    result = await apply_cohesion(clustering, points, router, max_visits=max_visits)
    after = mean_intra_cluster_minutes(result.clustering, router.duration)

    assert result.used_router is True
    assert result.fallback_reason is None
    assert "border-p" in result.moved_member_ids
    assert after < before
    assert result.after_mean_intra_minutes is not None
    assert result.before_mean_intra_minutes is not None
    assert result.after_mean_intra_minutes < result.before_mean_intra_minutes
    assert after == result.after_mean_intra_minutes
    membership = _membership(result.clustering)
    assert "border-p" in membership["urban-1"]
    assert "border-p" not in membership["urban-0"]
    assert membership["urban-0"] == frozenset({"a1", "a2"})
    assert membership["urban-1"] == frozenset({"b1", "b2", "border-p"})
    _assert_capacity(result.clustering, max_visits)
    assert result.clustering.outliers == ("rural-iso",)


@pytest.mark.asyncio
async def test_capacity_still_held_after_cohesion() -> None:
    clustering, points, router = _misassigned()
    max_visits = 3
    result = await apply_cohesion(clustering, points, router, max_visits=max_visits)
    _assert_capacity(result.clustering, max_visits)
    assigned = [
        member_id for cluster in result.clustering.clusters for member_id in cluster.member_ids
    ]
    assert len(assigned) == len(set(assigned))
    assert set(assigned) == {"a1", "a2", "border-p", "b1", "b2"}


@pytest.mark.asyncio
async def test_full_cluster_does_not_receive_border_point() -> None:
    clustering = _cluster(("a1", "border-p"), ("b1", "b2"))
    points = [_A1, _P, _B1, _B2]
    router = _PairRouter(points, _ROAD_SECONDS)
    max_visits = 2
    before = mean_intra_cluster_minutes(clustering, router.duration)

    result = await apply_cohesion(clustering, points, router, max_visits=max_visits)

    assert result.moved_member_ids == ()
    assert _membership(result.clustering) == _membership(clustering)
    after = mean_intra_cluster_minutes(result.clustering, router.duration)
    assert after == before
    _assert_capacity(result.clustering, max_visits)
    assert "border-p" in _membership(result.clustering)["urban-0"]


@pytest.mark.asyncio
async def test_router_table_failure_keeps_original_assignment() -> None:
    clustering, points, _ = _misassigned()
    original = _membership(clustering)

    result = await apply_cohesion(clustering, points, _FailingRouter(), max_visits=3)

    assert result.used_router is False
    assert result.fallback_reason == FALLBACK_ROUTER_TABLE_FAILED
    assert result.moved_member_ids == ()
    assert result.clustering is clustering
    assert _membership(result.clustering) == original
    assert result.clustering.outliers == clustering.outliers
    assert result.before_mean_intra_minutes is None
    assert result.after_mean_intra_minutes is None


@pytest.mark.asyncio
async def test_malformed_matrix_keeps_original_assignment() -> None:
    clustering, points, _ = _misassigned()

    class _BadMatrix(FakeRouter):
        async def table(self, coordinates: list[Coordinate]) -> DistanceMatrix:
            return DistanceMatrix(durations_seconds=[[0.0]], distances_meters=[[0.0]])

    result = await apply_cohesion(clustering, points, _BadMatrix(), max_visits=3)
    assert result.fallback_reason == FALLBACK_ROUTER_TABLE_FAILED
    assert result.clustering is clustering


@pytest.mark.asyncio
async def test_outliers_are_not_absorbed() -> None:
    clustering, points, router = _misassigned()
    result = await apply_cohesion(clustering, points, router, max_visits=4)
    assigned = {
        member_id for cluster in result.clustering.clusters for member_id in cluster.member_ids
    }
    assert "rural-iso" not in assigned
    assert result.clustering.outliers == ("rural-iso",)


@pytest.mark.asyncio
async def test_uniform_fake_router_does_not_reshape_equal_duration_clusters() -> None:
    clustering, points, _ = _misassigned()
    result = await apply_cohesion(clustering, points, FakeRouter(), max_visits=4)
    assert result.used_router is True
    assert result.moved_member_ids == ()
    assert _membership(result.clustering) == _membership(clustering)


@pytest.mark.asyncio
async def test_does_not_mix_urban_and_rural() -> None:
    clustering = _cluster(("a1", "a2", "border-p"), ("b1", "b2"), b_kind="rural")
    points = [_A1, _A2, _P, _B1, _B2]
    router = _PairRouter(points, _ROAD_SECONDS)
    result = await apply_cohesion(clustering, points, router, max_visits=4)
    assert "border-p" in _membership(result.clustering)["urban-0"]
    assert result.moved_member_ids == ()
    assert result.clustering.clusters[0].kind == "urban"
    assert result.clustering.clusters[1].kind == "rural"


@pytest.mark.asyncio
async def test_same_input_is_deterministic() -> None:
    clustering, points, router = _misassigned()
    first = await apply_cohesion(clustering, points, router, max_visits=3)
    second = await apply_cohesion(clustering, points, router, max_visits=3)
    assert first.clustering == second.clustering
    assert first.moved_member_ids == second.moved_member_ids
    assert first.after_mean_intra_minutes == second.after_mean_intra_minutes


@pytest.mark.asyncio
async def test_empty_clusters_skip_router() -> None:
    empty = ClusteringResult(clusters=(), outliers=("rural-iso",))
    result = await apply_cohesion(empty, [_OUTLIER], _FailingRouter(), max_visits=3)
    assert result.clustering is empty
    assert result.used_router is False
    assert result.fallback_reason is None


@pytest.mark.asyncio
async def test_max_visits_must_be_positive() -> None:
    clustering, points, router = _misassigned()
    with pytest.raises(ValueError, match="max_visits"):
        await apply_cohesion(clustering, points, router, max_visits=0)
