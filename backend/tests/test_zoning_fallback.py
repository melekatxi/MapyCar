"""Fallback municipio/CP + geodésica cuando OSRM no da matriz. Ref: 2.BE.7, diseño §7.3."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.adapters.router.fake import FakeRouter
from app.adapters.router.interface import Coordinate, DistanceMatrix
from app.modules.zoning.clustering import ClusteringResult, cluster_points
from app.modules.zoning.fallback import FALLBACK_MUNICIPIO_CP, fallback_group
from app.modules.zoning.features import PointFeatures, ZoningPoint, compute_features
from app.modules.zoning.service import _serialize_result, run_proposal_clustering

_DEPOT = ZoningPoint(
    longitude=-2.9348,
    latitude=43.2630,
    point_id="depot",
    municipality="Bilbao",
    postal_code="48001",
)

# Pares intercalados ~80 m entre municipios, ~16 km norte-sur: DBSCAN/K-means
# agrupa blobs euclidianos; el fallback debe conservar municipio.
_SOUTH_LAT = 43.2630
_NORTH_LAT = 43.4100
_BILBAO_LON = -2.9348
_GETXO_LON = -2.9338


class _FailingRouter(FakeRouter):
    async def table(self, coordinates: list[Coordinate]) -> DistanceMatrix:
        raise RuntimeError("osrm down")


def _interleaved_points() -> list[ZoningPoint]:
    return [
        ZoningPoint(
            longitude=_BILBAO_LON,
            latitude=_SOUTH_LAT,
            point_id="bilbao-south",
            municipality="Bilbao",
            postal_code="48001",
        ),
        ZoningPoint(
            longitude=_GETXO_LON,
            latitude=_SOUTH_LAT,
            point_id="getxo-south",
            municipality="Getxo",
            postal_code="48992",
        ),
        ZoningPoint(
            longitude=_BILBAO_LON,
            latitude=_NORTH_LAT,
            point_id="bilbao-north",
            municipality="Bilbao",
            postal_code="48001",
        ),
        ZoningPoint(
            longitude=_GETXO_LON,
            latitude=_NORTH_LAT,
            point_id="getxo-north",
            municipality="Getxo",
            postal_code="48992",
        ),
    ]


def _features(points: Sequence[ZoningPoint]) -> list[PointFeatures]:
    return compute_features(list(points), _DEPOT)


def _municipality_sets(
    clustering: ClusteringResult, features: Sequence[PointFeatures]
) -> list[frozenset[str | None]]:
    by_id = {point.point_id: point for point in features if point.point_id}
    return [
        frozenset(by_id[member_id].municipality for member_id in cluster.member_ids)
        for cluster in clustering.clusters
    ]


def _assert_capacity(clustering: ClusteringResult, max_visits: int) -> None:
    for cluster in clustering.clusters:
        assert 1 <= len(cluster.member_ids) <= max_visits, cluster


def _assert_partition(clustering: ClusteringResult, expected_ids: set[str]) -> None:
    assigned: list[str] = []
    for cluster in clustering.clusters:
        assigned.extend(cluster.member_ids)
    assigned.extend(clustering.outliers)
    assert len(assigned) == len(set(assigned))
    assert set(assigned) == expected_ids


def test_euclidean_clustering_mixes_interleaved_municipalities() -> None:
    features = _features(_interleaved_points())
    clustering = cluster_points(features, max_visits=3)
    mixed = [towns for towns in _municipality_sets(clustering, features) if len(towns) > 1]
    assert mixed, clustering


def test_raising_router_groups_by_municipality_not_euclidean_blobs() -> None:
    features = _features(_interleaved_points())
    result, extra = run_proposal_clustering(features, max_visits=3, router=_FailingRouter())

    assert extra["fallback"] == FALLBACK_MUNICIPIO_CP
    assert extra["used_router"] is False
    towns = _municipality_sets(result, features)
    assert {"Bilbao"} in towns
    assert {"Getxo"} in towns
    assert all(len(group) == 1 for group in towns)
    _assert_capacity(result, 3)
    _assert_partition(result, {point.point_id for point in features if point.point_id})


def test_isolated_municipality_is_not_dumped_into_foreign_cluster() -> None:
    # ~650 m: rural (fuera del radio 500 m) pero un solo grupo DBSCAN (eps 2.5 km).
    points = [
        ZoningPoint(
            longitude=-2.9338 + index * 0.008,
            latitude=43.3430,
            point_id=f"getxo-{index}",
            municipality="Getxo",
            postal_code="48992",
        )
        for index in range(3)
    ]
    points.append(
        ZoningPoint(
            longitude=-2.9338 + 0.024,
            latitude=43.3430,
            point_id="bilbao-iso",
            municipality="Bilbao",
            postal_code="48001",
        )
    )
    features = _features(points)
    clustering = cluster_points(features, max_visits=4)
    assert any(len(group) > 1 for group in _municipality_sets(clustering, features))

    result, extra = run_proposal_clustering(features, max_visits=4, router=_FailingRouter())
    assert extra["fallback"] == FALLBACK_MUNICIPIO_CP
    by_id = {point.point_id: point for point in features if point.point_id}
    getxo_cluster = next(cluster for cluster in result.clusters if "getxo-0" in cluster.member_ids)
    assert set(getxo_cluster.member_ids) == {"getxo-0", "getxo-1", "getxo-2"}
    isolated = next(cluster for cluster in result.clusters if "bilbao-iso" in cluster.member_ids)
    assert isolated.member_ids == ("bilbao-iso",)
    assert by_id["bilbao-iso"].municipality not in {
        by_id[member_id].municipality for member_id in getxo_cluster.member_ids
    }
    _assert_capacity(result, 4)


def test_isolated_cp_is_not_absorbed_by_full_same_municipality_cluster() -> None:
    points = [
        ZoningPoint(
            longitude=-2.9348 + index * 0.0004,
            latitude=43.2630,
            point_id=f"cp-full-{index}",
            municipality="Bilbao",
            postal_code="48001",
        )
        for index in range(3)
    ]
    points.append(
        ZoningPoint(
            longitude=-2.9348 + 0.0016,
            latitude=43.2630,
            point_id="cp-iso",
            municipality="Bilbao",
            postal_code="48013",
        )
    )
    features = _features(points)
    result = fallback_group(features, max_visits=3)
    by_member = {
        member_id: cluster.cluster_id
        for cluster in result.clusters
        for member_id in cluster.member_ids
    }
    assert by_member["cp-iso"] != by_member["cp-full-0"]
    assert len(next(c for c in result.clusters if "cp-full-0" in c.member_ids).member_ids) == 3
    assert next(c for c in result.clusters if "cp-iso" in c.member_ids).member_ids == ("cp-iso",)
    _assert_capacity(result, 3)
    assert result.outliers == ()


def test_max_visits_held_when_splitting_by_geodesic() -> None:
    points = [
        ZoningPoint(
            longitude=-2.9348 + index * 0.01,
            latitude=43.2630,
            point_id=f"line-{index}",
            municipality="Bilbao",
            postal_code="48001",
        )
        for index in range(5)
    ]
    features = _features(points)
    result = fallback_group(features, max_visits=2)
    _assert_capacity(result, 2)
    _assert_partition(result, {f"line-{index}" for index in range(5)})
    assert len(result.clusters) == 3


def test_missing_admin_identity_becomes_outlier() -> None:
    points = [
        ZoningPoint(
            longitude=-2.9348,
            latitude=43.2630,
            point_id="with-muni",
            municipality="Bilbao",
            postal_code="48001",
        ),
        ZoningPoint(
            longitude=-3.3630,
            latitude=43.2210,
            point_id="no-admin",
            municipality=None,
            postal_code=None,
        ),
    ]
    result = fallback_group(_features(points), max_visits=3)
    assigned = {member_id for cluster in result.clusters for member_id in cluster.member_ids}
    assert "with-muni" in assigned
    assert "no-admin" in result.outliers
    assert "no-admin" not in assigned


def test_fake_router_runs_cohesion_without_fallback() -> None:
    features = _features(_interleaved_points())
    clustering = cluster_points(features, max_visits=3)
    result, extra = run_proposal_clustering(features, max_visits=3, router=FakeRouter())
    assert extra["used_router"] is True
    assert extra.get("fallback") is None
    assert {cluster.member_ids for cluster in result.clusters} == {
        cluster.member_ids for cluster in clustering.clusters
    }


def test_serialized_metrics_include_municipio_cp_fallback() -> None:
    features = _features(_interleaved_points())
    clustering, extra = run_proposal_clustering(features, max_visits=3, router=_FailingRouter())
    payload = _serialize_result(clustering, features, max_visits=3, extra_metrics=extra)
    assert payload["metrics"]["fallback"] == FALLBACK_MUNICIPIO_CP
    assert payload["metrics"]["used_router"] is False
    assert payload["metrics"]["max_visits"] == 3


def test_same_input_is_deterministic() -> None:
    features = _features(_interleaved_points())
    first = fallback_group(features, max_visits=3)
    second = fallback_group(features, max_visits=3)
    assert first == second
    a, _ = run_proposal_clustering(features, max_visits=3, router=_FailingRouter())
    b, _ = run_proposal_clustering(features, max_visits=3, router=_FailingRouter())
    assert a == b


def test_empty_input_returns_empty_result() -> None:
    result = fallback_group([], max_visits=5)
    assert result.clusters == ()
    assert result.outliers == ()


def test_max_visits_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_visits"):
        fallback_group([], max_visits=0)
