"""Segunda pasada de cohesión viaria sobre clusters. Ref: RF-09, diseño §7.3, ADR-10.

Consume `ZoneCluster` como dato (no reagrupa). Llama a `Router.table` (OSRM) y
mueve un punto de borde al vecino si baja la dispersión media en minutos sin
romper `max_visits`. Greedy y determinista. Los outliers no se absorben.

Si `Router.table` falla, devuelve los clusters de entrada. El fallback
municipio/CP + geodésica es 2.BE.7 (`FALLBACK_ROUTER_TABLE_FAILED`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import isfinite

from app.adapters.router.interface import Coordinate, DistanceMatrix, Router
from app.modules.zoning.clustering import ClusteringResult, ZoneCluster
from app.modules.zoning.features import PointFeatures

# 2.BE.7 consume este valor para agrupar por municipio/CP si falta la matriz.
FALLBACK_ROUTER_TABLE_FAILED = "router_table_failed"


@dataclass(frozen=True)
class CohesionResult:
    clustering: ClusteringResult
    before_mean_intra_minutes: float | None
    after_mean_intra_minutes: float | None
    moved_member_ids: tuple[str, ...]
    used_router: bool
    fallback_reason: str | None = None


def mean_intra_cluster_minutes(
    clustering: ClusteringResult,
    duration_seconds: Callable[[str, str], float],
) -> float:
    """Media de pares intra-cluster (minutos). Clusters de 1 punto no aportan pares."""
    total = 0.0
    n_pairs = 0
    for cluster in clustering.clusters:
        members = cluster.member_ids
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                total += duration_seconds(left, right)
                n_pairs += 1
    if n_pairs == 0:
        return 0.0
    return (total / n_pairs) / 60.0


async def apply_cohesion(
    clustering: ClusteringResult,
    points: Sequence[PointFeatures],
    router: Router,
    *,
    max_visits: int,
) -> CohesionResult:
    """Ajusta bordes con distancia viaria. No muta `clustering` ni absorbe outliers."""
    if max_visits < 1:
        raise ValueError("max_visits must be >= 1")

    if not clustering.clusters:
        return _unchanged(clustering)

    by_id = _index_points(points)
    clustered_ids = [
        member_id for cluster in clustering.clusters for member_id in cluster.member_ids
    ]
    if any(
        member_id not in by_id or not _has_wgs84(by_id[member_id]) for member_id in clustered_ids
    ):
        return _unchanged(clustering)
    table_ids = tuple(sorted(set(clustered_ids)))
    if len(table_ids) < 2:
        return _unchanged(clustering)

    coordinates = [
        Coordinate(latitude=by_id[member_id].latitude, longitude=by_id[member_id].longitude)
        for member_id in table_ids
    ]
    durations = await _durations_or_none(router, coordinates)
    if durations is None:
        return _unchanged(clustering, fallback_reason=FALLBACK_ROUTER_TABLE_FAILED)

    index = {member_id: i for i, member_id in enumerate(table_ids)}
    movable = set(table_ids)

    def duration_seconds(left: str, right: str) -> float:
        i, j = index[left], index[right]
        return (durations[i][j] + durations[j][i]) / 2.0

    members = {cluster.cluster_id: list(cluster.member_ids) for cluster in clustering.clusters}
    kinds = {cluster.cluster_id: cluster.kind for cluster in clustering.clusters}
    before = mean_intra_cluster_minutes(clustering, duration_seconds)

    moved: list[str] = []
    seen: set[str] = set()
    n_clusters = len(members)
    limit = max(1, len(table_ids) * n_clusters)
    for _ in range(limit):
        move = _best_move(
            members,
            kinds=kinds,
            max_visits=max_visits,
            duration_seconds=duration_seconds,
            movable=movable,
        )
        if move is None:
            break
        member_id, src, dst = move
        members[src].remove(member_id)
        members[dst].append(member_id)
        if member_id not in seen:
            seen.add(member_id)
            moved.append(member_id)

    if not moved:
        return CohesionResult(
            clustering=clustering,
            before_mean_intra_minutes=before,
            after_mean_intra_minutes=before,
            moved_member_ids=(),
            used_router=True,
        )

    adjusted = _rebuild(clustering, members, by_id)
    after = mean_intra_cluster_minutes(adjusted, duration_seconds)
    return CohesionResult(
        clustering=adjusted,
        before_mean_intra_minutes=before,
        after_mean_intra_minutes=after,
        moved_member_ids=tuple(moved),
        used_router=True,
    )


def _unchanged(
    clustering: ClusteringResult, *, fallback_reason: str | None = None
) -> CohesionResult:
    return CohesionResult(
        clustering=clustering,
        before_mean_intra_minutes=None if fallback_reason else 0.0,
        after_mean_intra_minutes=None if fallback_reason else 0.0,
        moved_member_ids=(),
        used_router=False,
        fallback_reason=fallback_reason,
    )


def _index_points(points: Sequence[PointFeatures]) -> dict[str, PointFeatures]:
    by_id: dict[str, PointFeatures] = {}
    for point in points:
        if point.point_id:
            by_id[point.point_id] = point
    return by_id


def _has_wgs84(point: PointFeatures) -> bool:
    lon, lat = point.longitude, point.latitude
    return lon is not None and lat is not None and isfinite(lon) and isfinite(lat)


async def _durations_or_none(
    router: Router, coordinates: list[Coordinate]
) -> list[list[float]] | None:
    try:
        matrix = await router.table(coordinates)
    except Exception:  # noqa: BLE001 — 2.BE.7: matriz OSRM ausente no tumba la zonificación
        return None
    return _validate_durations(matrix, len(coordinates))


def _validate_durations(matrix: DistanceMatrix, n: int) -> list[list[float]] | None:
    rows = matrix.durations_seconds
    if len(rows) != n:
        return None
    out: list[list[float]] = []
    for row in rows:
        if len(row) != n:
            return None
        converted: list[float] = []
        for value in row:
            if value is None:
                return None
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            if not isfinite(number) or number < 0:
                return None
            converted.append(number)
        out.append(converted)
    return out


def _pair_stats(
    members: dict[str, list[str]],
    duration_seconds: Callable[[str, str], float],
    movable: set[str],
) -> tuple[float, int]:
    total = 0.0
    n_pairs = 0
    for group in members.values():
        known = [member_id for member_id in group if member_id in movable]
        for i, left in enumerate(known):
            for right in known[i + 1 :]:
                total += duration_seconds(left, right)
                n_pairs += 1
    return total, n_pairs


def _mean_seconds(total: float, n_pairs: int) -> float:
    if n_pairs == 0:
        return 0.0
    return total / n_pairs


def _best_move(
    members: dict[str, list[str]],
    *,
    kinds: dict[str, str],
    max_visits: int,
    duration_seconds: Callable[[str, str], float],
    movable: set[str],
) -> tuple[str, str, str] | None:
    """Mejor reasignación greedy: (member_id, src, dst) que baja la media. Orden estable."""
    total, n_pairs = _pair_stats(members, duration_seconds, movable)
    current = _mean_seconds(total, n_pairs)
    best: tuple[str, str, str] | None = None
    best_mean = current
    for src in sorted(members):
        src_members = members[src]
        if len(src_members) <= 1:
            continue
        src_known = [member_id for member_id in src_members if member_id in movable]
        for member_id in sorted(src_known):
            lost_n = sum(1 for other in src_known if other != member_id)
            lost = sum(
                duration_seconds(member_id, other) for other in src_known if other != member_id
            )
            for dst in sorted(members):
                if dst == src or kinds[dst] != kinds[src]:
                    continue
                dst_members = members[dst]
                if len(dst_members) >= max_visits:
                    continue
                dst_known = [other for other in dst_members if other in movable]
                gained_n = len(dst_known)
                gained = sum(duration_seconds(member_id, other) for other in dst_known)
                new_n = n_pairs - lost_n + gained_n
                new_mean = _mean_seconds(total - lost + gained, new_n)
                if new_mean < best_mean:
                    best_mean = new_mean
                    best = (member_id, src, dst)
    if best is None or best_mean >= current:
        return None
    return best


def _rebuild(
    original: ClusteringResult,
    members: dict[str, list[str]],
    by_id: dict[str, PointFeatures],
) -> ClusteringResult:
    clusters: list[ZoneCluster] = []
    for cluster in original.clusters:
        member_ids = tuple(sorted(members[cluster.cluster_id]))
        clusters.append(
            ZoneCluster(
                cluster_id=cluster.cluster_id,
                kind=cluster.kind,
                member_ids=member_ids,
                centroid_xy=_centroid_xy(member_ids, by_id, fallback=cluster.centroid_xy),
            )
        )
    return ClusteringResult(clusters=tuple(clusters), outliers=original.outliers)


def _centroid_xy(
    member_ids: Sequence[str],
    by_id: dict[str, PointFeatures],
    *,
    fallback: tuple[float, float],
) -> tuple[float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for member_id in member_ids:
        point = by_id.get(member_id)
        if point is None or point.x is None or point.y is None:
            continue
        if not isfinite(point.x) or not isfinite(point.y):
            continue
        xs.append(point.x)
        ys.append(point.y)
    if not xs:
        return fallback
    n = len(xs)
    return (sum(xs) / n, sum(ys) / n)
