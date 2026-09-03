"""Clustering capacitado de features de zonificación. Ref: RF-09, RF-11, RF-12, diseño §7.3.

Puro: no toca DB, no llama a OSRM (cohesión viaria es 2.BE.4). Urbano: K-means
capacitado sobre coordenadas proyectadas. Rural: DBSCAN para hamlets y outliers.
K-means puro no respeta capacidad ni aísla caseríos; la semilla municipio/CP se
usa solo cuando el grupo cabe en `max_visits` y es compacto.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, inf, isfinite

import numpy as np
from sklearn.cluster import DBSCAN, KMeans

from app.modules.zoning.features import PointFeatures

_KIND_URBAN = "urban"
_KIND_RURAL = "rural"
_KIND_MIXED = "mixed"

# Diámetro máximo (m) para conservar un grupo municipio/CP como semilla continua.
SEED_MAX_DIAMETER_M = 12_000.0
# Radio DBSCAN rural (m). Caseríos a decenas de km quedan ruido; un hamlet no.
RURAL_EPS_M = 2_500.0
RURAL_MIN_SAMPLES = 2


@dataclass(frozen=True)
class ZoneCluster:
    cluster_id: str
    kind: str
    member_ids: tuple[str, ...]
    centroid_xy: tuple[float, float]


@dataclass(frozen=True)
class ClusteringResult:
    clusters: tuple[ZoneCluster, ...]
    outliers: tuple[str, ...]


@dataclass(frozen=True)
class _Tagged:
    point: PointFeatures
    member_id: str


def cluster_points(
    points: Sequence[PointFeatures],
    *,
    max_visits: int,
    target_zones: int | None = None,
    rng_seed: int = 0,
    rural_eps_m: float = RURAL_EPS_M,
    rural_min_samples: int = RURAL_MIN_SAMPLES,
    seed_max_diameter_m: float = SEED_MAX_DIAMETER_M,
) -> ClusteringResult:
    """Agrupa puntos en zonas que respetan `max_visits`. Omite lon/lat ausentes.

    `target_zones` es una cota blanda (la capacidad gana). Urbano y rural no se
    mezclan. Puntos rurales aislados van a `outliers`, no a un cluster lleno.
    """
    if max_visits < 1:
        raise ValueError("max_visits must be >= 1")
    if target_zones is not None and target_zones < 1:
        raise ValueError("target_zones must be >= 1")

    tagged = [_tag(point, index) for index, point in enumerate(points) if _has_coords(point)]
    urban = [item for item in tagged if item.point.kind == _KIND_URBAN]
    rural = [item for item in tagged if item.point.kind != _KIND_URBAN]

    rural_groups, outlier_ids = _cluster_rural(
        rural,
        max_visits=max_visits,
        eps_m=rural_eps_m,
        min_samples=rural_min_samples,
        rng_seed=rng_seed,
    )
    urban_k = _urban_k(
        len(urban), max_visits=max_visits, target_zones=target_zones, n_rural=len(rural_groups)
    )
    urban_groups = _cluster_urban(
        urban,
        max_visits=max_visits,
        min_k=urban_k,
        rng_seed=rng_seed,
        seed_max_diameter_m=seed_max_diameter_m,
        allow_merge=target_zones is not None,
    )

    clusters = (
        *(_to_cluster(group, kind_hint=_KIND_URBAN) for group in urban_groups if group),
        *(_to_cluster(group, kind_hint=_KIND_RURAL) for group in rural_groups if group),
    )
    ordered = _order_clusters(clusters)
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
    return ClusteringResult(clusters=tuple(labeled), outliers=tuple(sorted(outlier_ids)))


def _tag(point: PointFeatures, index: int) -> _Tagged:
    member_id = point.point_id if point.point_id else f"idx:{index}"
    return _Tagged(point=point, member_id=member_id)


def _has_coords(point: PointFeatures) -> bool:
    lon, lat = point.longitude, point.latitude
    if lon is None or lat is None:
        return False
    x, y = point.x, point.y
    if x is None or y is None:
        return False
    return all(isfinite(value) for value in (lon, lat, x, y))


def _urban_k(n_urban: int, *, max_visits: int, target_zones: int | None, n_rural: int) -> int:
    if n_urban == 0:
        return 0
    floor_k = ceil(n_urban / max_visits)
    if target_zones is None:
        return floor_k
    return max(floor_k, target_zones - n_rural)


def _cluster_urban(
    points: Sequence[_Tagged],
    *,
    max_visits: int,
    min_k: int,
    rng_seed: int,
    seed_max_diameter_m: float,
    allow_merge: bool,
) -> list[list[_Tagged]]:
    if not points:
        return []
    seeds, leftovers = _seed_by_admin(
        points, max_visits=max_visits, max_diameter_m=seed_max_diameter_m
    )
    leftover_k = max(1, min_k - len(seeds)) if leftovers else 0
    leftover_groups = _capacitated_kmeans(
        leftovers, max_visits=max_visits, k=leftover_k, rng_seed=rng_seed
    )
    groups = [*seeds, *leftover_groups]
    return _fit_target_k(
        groups,
        max_visits=max_visits,
        target_k=min_k,
        rng_seed=rng_seed,
        allow_merge=allow_merge,
    )


def _seed_by_admin(
    points: Sequence[_Tagged],
    *,
    max_visits: int,
    max_diameter_m: float,
) -> tuple[list[list[_Tagged]], list[_Tagged]]:
    by_muni: dict[str, list[_Tagged]] = defaultdict(list)
    leftovers: list[_Tagged] = []
    for item in points:
        muni = item.point.municipality
        if muni:
            by_muni[muni].append(item)
        else:
            leftovers.append(item)

    seeds: list[list[_Tagged]] = []
    for muni in sorted(by_muni):
        group = by_muni[muni]
        if _is_continuous_seed(group, max_visits=max_visits, max_diameter_m=max_diameter_m):
            seeds.append(group)
            continue
        if len(group) <= max_visits:
            leftovers.extend(group)
            continue
        cp_seeds, cp_left = _seed_by_postal(
            group, max_visits=max_visits, max_diameter_m=max_diameter_m
        )
        seeds.extend(cp_seeds)
        leftovers.extend(cp_left)
    return seeds, leftovers


def _seed_by_postal(
    points: Sequence[_Tagged],
    *,
    max_visits: int,
    max_diameter_m: float,
) -> tuple[list[list[_Tagged]], list[_Tagged]]:
    by_cp: dict[str, list[_Tagged]] = defaultdict(list)
    leftovers: list[_Tagged] = []
    for item in points:
        code = item.point.postal_code
        if code:
            by_cp[code].append(item)
        else:
            leftovers.append(item)
    seeds: list[list[_Tagged]] = []
    for code in sorted(by_cp):
        group = by_cp[code]
        if _is_continuous_seed(group, max_visits=max_visits, max_diameter_m=max_diameter_m):
            seeds.append(group)
        else:
            leftovers.extend(group)
    return seeds, leftovers


def _is_continuous_seed(
    group: Sequence[_Tagged], *, max_visits: int, max_diameter_m: float
) -> bool:
    return bool(group) and len(group) <= max_visits and _diameter_m(group) <= max_diameter_m


def _cluster_rural(
    points: Sequence[_Tagged],
    *,
    max_visits: int,
    eps_m: float,
    min_samples: int,
    rng_seed: int,
) -> tuple[list[list[_Tagged]], list[str]]:
    if not points:
        return [], []
    if len(points) == 1:
        return [], [points[0].member_id]

    labels = DBSCAN(eps=eps_m, min_samples=min_samples).fit_predict(_coords(points))
    by_label: dict[int, list[_Tagged]] = defaultdict(list)
    outliers: list[str] = []
    for item, label in zip(points, labels, strict=True):
        if int(label) < 0:
            outliers.append(item.member_id)
        else:
            by_label[int(label)].append(item)

    groups: list[list[_Tagged]] = []
    for label in sorted(by_label):
        group = by_label[label]
        if len(group) <= max_visits:
            groups.append(group)
        else:
            groups.extend(
                _capacitated_kmeans(
                    group,
                    max_visits=max_visits,
                    k=ceil(len(group) / max_visits),
                    rng_seed=rng_seed + 17 + label,
                )
            )
    return groups, outliers


def _capacitated_kmeans(
    points: Sequence[_Tagged],
    *,
    max_visits: int,
    k: int,
    rng_seed: int,
) -> list[list[_Tagged]]:
    n = len(points)
    if n == 0:
        return []
    if n == 1 or max_visits >= n:
        return [list(points)]
    if max_visits == 1:
        return [[item] for item in points]

    k = min(n, max(k, ceil(n / max_visits)))
    coords = _coords(points)
    model = KMeans(n_clusters=k, random_state=rng_seed, n_init=10)
    centroids = model.fit(coords).cluster_centers_
    groups = _assign_capacitated(points, centroids, max_visits=max_visits)

    result: list[list[_Tagged]] = []
    for index, group in enumerate(groups):
        if not group:
            continue
        if len(group) <= max_visits:
            result.append(group)
            continue
        result.extend(
            _capacitated_kmeans(
                group,
                max_visits=max_visits,
                k=ceil(len(group) / max_visits),
                rng_seed=rng_seed + 1 + index,
            )
        )
    assigned = {item.member_id for group in result for item in group}
    leftovers = [item for item in points if item.member_id not in assigned]
    if leftovers:
        result.extend(
            _capacitated_kmeans(
                leftovers,
                max_visits=max_visits,
                k=ceil(len(leftovers) / max_visits),
                rng_seed=rng_seed + 97,
            )
        )
    return result


def _assign_capacitated(
    points: Sequence[_Tagged],
    centroids: np.ndarray,
    *,
    max_visits: int,
) -> list[list[_Tagged]]:
    coords = _coords(points)
    delta = coords[:, None, :] - centroids[None, :, :]
    distances = np.linalg.norm(delta, axis=2)
    order = np.argsort(distances.min(axis=1), kind="mergesort")
    capacities = [max_visits] * len(centroids)
    groups: list[list[_Tagged]] = [[] for _ in centroids]
    for idx in order:
        nearest = np.argsort(distances[idx], kind="mergesort")
        for centroid_i in nearest:
            slot = int(centroid_i)
            if capacities[slot] > 0:
                groups[slot].append(points[int(idx)])
                capacities[slot] -= 1
                break
    return groups


def _fit_target_k(
    groups: list[list[_Tagged]],
    *,
    max_visits: int,
    target_k: int,
    rng_seed: int,
    allow_merge: bool,
) -> list[list[_Tagged]]:
    groups = [group for group in groups if group]
    groups = _split_over_capacity(groups, max_visits=max_visits, rng_seed=rng_seed)
    if target_k <= 0:
        return groups

    split_seed = rng_seed
    while len(groups) < target_k:
        split_at = _largest_splittable(groups)
        if split_at is None:
            break
        split_seed += 1
        parts = _capacitated_kmeans(
            groups[split_at], max_visits=max_visits, k=2, rng_seed=split_seed
        )
        if len(parts) < 2:
            break
        groups.pop(split_at)
        groups.extend(parts)

    if not allow_merge:
        return groups
    while len(groups) > target_k:
        pair = _nearest_mergeable(groups, max_visits=max_visits)
        if pair is None:
            break
        i, j = pair
        merged = groups[i] + groups[j]
        for index in sorted((i, j), reverse=True):
            groups.pop(index)
        groups.append(merged)
    return groups


def _split_over_capacity(
    groups: Sequence[list[_Tagged]], *, max_visits: int, rng_seed: int
) -> list[list[_Tagged]]:
    result: list[list[_Tagged]] = []
    for index, group in enumerate(groups):
        if len(group) <= max_visits:
            result.append(group)
        else:
            result.extend(
                _capacitated_kmeans(
                    group,
                    max_visits=max_visits,
                    k=ceil(len(group) / max_visits),
                    rng_seed=rng_seed + 31 + index,
                )
            )
    return result


def _largest_splittable(groups: Sequence[list[_Tagged]]) -> int | None:
    best_i: int | None = None
    best_n = 1
    for index, group in enumerate(groups):
        if len(group) > best_n:
            best_n = len(group)
            best_i = index
    return best_i


def _nearest_mergeable(
    groups: Sequence[list[_Tagged]], *, max_visits: int
) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    best_d = inf
    centroids = [_centroid_xy(group) for group in groups]
    for i, left in enumerate(groups):
        for j in range(i + 1, len(groups)):
            right = groups[j]
            if len(left) + len(right) > max_visits:
                continue
            dx = centroids[i][0] - centroids[j][0]
            dy = centroids[i][1] - centroids[j][1]
            dist = dx * dx + dy * dy
            if dist < best_d:
                best_d = dist
                best = (i, j)
    return best


def _coords(points: Sequence[_Tagged]) -> np.ndarray:
    return np.array([[item.point.x, item.point.y] for item in points], dtype=float)


def _diameter_m(points: Sequence[_Tagged]) -> float:
    if len(points) <= 1:
        return 0.0
    coords = _coords(points)
    delta = coords[:, None, :] - coords[None, :, :]
    return float(np.linalg.norm(delta, axis=2).max())


def _centroid_xy(points: Sequence[_Tagged]) -> tuple[float, float]:
    n = len(points)
    return (
        sum(item.point.x for item in points) / n,
        sum(item.point.y for item in points) / n,
    )


def _cluster_kind(points: Sequence[_Tagged], *, kind_hint: str) -> str:
    kinds = {item.point.kind for item in points}
    if len(kinds) == 1:
        return next(iter(kinds))
    return _KIND_MIXED if kinds else kind_hint


def _to_cluster(group: Sequence[_Tagged], *, kind_hint: str) -> ZoneCluster:
    member_ids = tuple(sorted(item.member_id for item in group))
    return ZoneCluster(
        cluster_id="",
        kind=_cluster_kind(group, kind_hint=kind_hint),
        member_ids=member_ids,
        centroid_xy=_centroid_xy(group),
    )


def _order_clusters(clusters: Sequence[ZoneCluster]) -> list[ZoneCluster]:
    kind_rank = {_KIND_URBAN: 0, _KIND_MIXED: 1, _KIND_RURAL: 2}
    return sorted(
        clusters,
        key=lambda cluster: (
            kind_rank.get(cluster.kind, 9),
            cluster.centroid_xy[0],
            cluster.centroid_xy[1],
            cluster.member_ids,
        ),
    )
