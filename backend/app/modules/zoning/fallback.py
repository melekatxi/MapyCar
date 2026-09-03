"""Agrupación de fallback por municipio/CP y distancia geodésica. Ref: 2.BE.7, diseño §7.3.

Sin Router. Si falta la matriz OSRM, se agrupa por municipio y después por CP; los
grupos que superan `max_visits` se parten por centroide geodésico (haversine).
Un punto de municipio/CP aislado queda como zona de excepción (cluster de 1).
Sin municipio ni CP → outlier (asignación manual). Determinista.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, isfinite

from app.modules.zoning.clustering import ClusteringResult, ZoneCluster
from app.modules.zoning.features import PointFeatures, haversine_meters

FALLBACK_MUNICIPIO_CP = "municipio_cp"

_KIND_URBAN = "urban"
_KIND_RURAL = "rural"
_KIND_MIXED = "mixed"
_KIND_RANK = {_KIND_URBAN: 0, _KIND_MIXED: 1, _KIND_RURAL: 2}


@dataclass(frozen=True)
class _Tagged:
    point: PointFeatures
    member_id: str


def fallback_group(points: Sequence[PointFeatures], *, max_visits: int) -> ClusteringResult:
    """Agrupa por municipio, luego CP, y parte por haversine si hay sobrecapacidad."""
    if max_visits < 1:
        raise ValueError("max_visits must be >= 1")

    tagged = [_tag(point, index) for index, point in enumerate(points) if _has_coords(point)]
    by_muni: dict[str, list[_Tagged]] = defaultdict(list)
    no_muni: list[_Tagged] = []
    for item in tagged:
        municipality = item.point.municipality
        if municipality:
            by_muni[municipality].append(item)
        else:
            no_muni.append(item)

    groups: list[list[_Tagged]] = []
    for municipality in sorted(by_muni):
        groups.extend(_fit_admin(by_muni[municipality], max_visits=max_visits, split_by_cp=True))

    by_cp: dict[str, list[_Tagged]] = defaultdict(list)
    outliers: list[str] = []
    for item in no_muni:
        code = item.point.postal_code
        if code:
            by_cp[code].append(item)
        else:
            outliers.append(item.member_id)
    for code in sorted(by_cp):
        groups.extend(_fit_admin(by_cp[code], max_visits=max_visits, split_by_cp=False))

    clusters = [_to_cluster(group) for group in groups if group]
    labeled = _label_clusters(clusters)
    return ClusteringResult(clusters=tuple(labeled), outliers=tuple(sorted(outliers)))


def _tag(point: PointFeatures, index: int) -> _Tagged:
    member_id = point.point_id if point.point_id else f"idx:{index}"
    return _Tagged(point=point, member_id=member_id)


def _has_coords(point: PointFeatures) -> bool:
    values = (point.longitude, point.latitude, point.x, point.y)
    return all(value is not None and isfinite(value) for value in values)


def _fit_admin(
    items: Sequence[_Tagged], *, max_visits: int, split_by_cp: bool
) -> list[list[_Tagged]]:
    ordered = _sorted_tagged(items)
    if len(ordered) <= max_visits:
        return [ordered]
    if split_by_cp:
        by_cp: dict[str, list[_Tagged]] = defaultdict(list)
        no_cp: list[_Tagged] = []
        for item in ordered:
            code = item.point.postal_code
            if code:
                by_cp[code].append(item)
            else:
                no_cp.append(item)
        parts: list[list[_Tagged]] = []
        for code in sorted(by_cp):
            parts.extend(_fit_admin(by_cp[code], max_visits=max_visits, split_by_cp=False))
        if no_cp:
            parts.extend(_split_geodesic(no_cp, max_visits=max_visits))
        return parts
    return _split_geodesic(ordered, max_visits=max_visits)


def _split_geodesic(items: Sequence[_Tagged], *, max_visits: int) -> list[list[_Tagged]]:
    ordered = _sorted_tagged(items)
    n = len(ordered)
    if n == 0:
        return []
    if n <= max_visits:
        return [ordered]
    if max_visits == 1:
        return [[item] for item in ordered]

    k = ceil(n / max_visits)
    seeds = _farthest_seeds(ordered, k)
    groups = _assign_nearest_centroid(ordered, seeds, max_visits=max_visits)
    result: list[list[_Tagged]] = []
    for group in groups:
        if not group:
            continue
        if len(group) <= max_visits:
            result.append(_sorted_tagged(group))
        else:
            result.extend(_split_geodesic(group, max_visits=max_visits))
    assigned = {item.member_id for group in result for item in group}
    leftovers = [item for item in ordered if item.member_id not in assigned]
    if leftovers:
        result.extend(_split_geodesic(leftovers, max_visits=max_visits))
    return result


def _farthest_seeds(ordered: Sequence[_Tagged], k: int) -> list[_Tagged]:
    seeds = [ordered[0]]
    remaining = list(ordered[1:])
    while len(seeds) < k and remaining:
        best_i = 0
        best_d = -1.0
        for index, item in enumerate(remaining):
            distance = min(_haversine(item, seed) for seed in seeds)
            if distance > best_d:
                best_d = distance
                best_i = index
        seeds.append(remaining.pop(best_i))
    return seeds


def _assign_nearest_centroid(
    items: Sequence[_Tagged], seeds: Sequence[_Tagged], *, max_visits: int
) -> list[list[_Tagged]]:
    centroids = [(seed.point.longitude, seed.point.latitude) for seed in seeds]
    capacities = [max_visits] * len(seeds)
    groups: list[list[_Tagged]] = [[] for _ in seeds]
    seed_ids = {seed.member_id for seed in seeds}

    for index, seed in enumerate(seeds):
        groups[index].append(seed)
        capacities[index] -= 1

    rest = [item for item in items if item.member_id not in seed_ids]

    def min_distance(item: _Tagged) -> float:
        return min(_haversine_to(item, lon, lat) for lon, lat in centroids)

    for item in sorted(rest, key=lambda tagged: (min_distance(tagged), tagged.member_id)):
        ranked = sorted(
            ((_haversine_to(item, lon, lat), index) for index, (lon, lat) in enumerate(centroids)),
        )
        for _, index in ranked:
            if capacities[index] > 0:
                groups[index].append(item)
                capacities[index] -= 1
                break
    return groups


def _haversine(left: _Tagged, right: _Tagged) -> float:
    return haversine_meters(
        left.point.longitude,
        left.point.latitude,
        right.point.longitude,
        right.point.latitude,
    )


def _haversine_to(item: _Tagged, longitude: float, latitude: float) -> float:
    return haversine_meters(item.point.longitude, item.point.latitude, longitude, latitude)


def _sorted_tagged(items: Sequence[_Tagged]) -> list[_Tagged]:
    return sorted(
        items,
        key=lambda item: (item.point.latitude, item.point.longitude, item.member_id),
    )


def _cluster_kind(items: Sequence[_Tagged]) -> str:
    kinds = {item.point.kind for item in items}
    if len(kinds) == 1:
        return next(iter(kinds))
    return _KIND_MIXED


def _centroid_xy(items: Sequence[_Tagged]) -> tuple[float, float]:
    xs = [item.point.x for item in items]
    ys = [item.point.y for item in items]
    n = len(xs)
    return (sum(xs) / n, sum(ys) / n)


def _to_cluster(group: Sequence[_Tagged]) -> ZoneCluster:
    member_ids = tuple(sorted(item.member_id for item in group))
    return ZoneCluster(
        cluster_id="",
        kind=_cluster_kind(group),
        member_ids=member_ids,
        centroid_xy=_centroid_xy(group),
    )


def _label_clusters(clusters: Sequence[ZoneCluster]) -> list[ZoneCluster]:
    ordered = sorted(
        clusters,
        key=lambda cluster: (
            _KIND_RANK.get(cluster.kind, 9),
            cluster.centroid_xy[0],
            cluster.centroid_xy[1],
            cluster.member_ids,
        ),
    )
    counters: dict[str, int] = {}
    labeled: list[ZoneCluster] = []
    for cluster in ordered:
        index = counters.get(cluster.kind, 0)
        counters[cluster.kind] = index + 1
        labeled.append(
            ZoneCluster(
                cluster_id=f"{cluster.kind}-{index}",
                kind=cluster.kind,
                member_ids=cluster.member_ids,
                centroid_xy=cluster.centroid_xy,
            )
        )
    return labeled
