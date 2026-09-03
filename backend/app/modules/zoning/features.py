"""Features de zonificación a partir de lon/lat WGS84. Ref: RF-12, diseño sección 7.3.

Puro: no toca DB, no llama a OSRM (la matriz viaria es 2.BE.4). El fallback geodésico
de agrupación por municipio/CP es 2.BE.7; aquí solo se calcula tiempo aproximado al
depósito por haversine. El clustering (K-means / HDBSCAN) es 2.BE.3.

CRS: ETRS89 / UTM zona 30N (EPSG:25830). Es el CRS proyectado oficial de Euskadi
(GeoEuskadi, catastro, IGN) en metros. La zona 30 (6°W–0°) cubre Bizkaia y el
meridiano central (3°W) pasa casi por Bilbao, así que la distorsión local es mínima.
Las coordenadas de PostGIS llegan en WGS84 (EPSG:4326); ETRS89≈WGS84 a esta escala
(decímetros frente a radios de densidad de cientos de metros).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt, tan

FEATURE_CRS = "EPSG:25830"
# Radio de vecindad local sobre coordenadas proyectadas (metros).
DENSITY_RADIUS_M = 500.0
# Vecinos (incluido el propio punto) a partir de los cuales se considera urbano.
URBAN_DENSITY_THRESHOLD = 4
# Velocidades conservadoras (subestiman km/h → sobreestiman minutos). No es OSRM.
# Urbana: tráfico stop-start en Bilbao. Rural: carreteras BI- de montaña, no AP-8.
URBAN_SPEED_KMH = 20.0
RURAL_SPEED_KMH = 35.0

_EARTH_RADIUS_M = 6_371_000.0
# Elipsoide GRS80 (EPSG:25830). WGS84 difiere en el aplanamiento a partir de 1e-9.
_GRS80_A = 6_378_137.0
_GRS80_F = 1 / 298.257222101
_UTM_K0 = 0.9996
_UTM_FALSE_EASTING = 500_000.0
_UTM_FALSE_NORTHING = 0.0
_UTM30_CENTRAL_MERIDIAN_DEG = -3.0

_KIND_URBAN = "urban"
_KIND_RURAL = "rural"
_VALID_KINDS = frozenset({_KIND_URBAN, _KIND_RURAL})


@dataclass(frozen=True)
class ZoningPoint:
    """Punto de entrada en WGS84. `longitude`/`latitude` como en PostGIS geography."""

    longitude: float
    latitude: float
    point_id: str | None = None
    municipality: str | None = None
    postal_code: str | None = None
    municipality_kind: str | None = None


@dataclass(frozen=True)
class PointFeatures:
    point_id: str | None
    longitude: float
    latitude: float
    x: float
    y: float
    density: int
    kind: str
    depot_distance_m: float
    depot_time_minutes: float
    municipality: str | None = None
    postal_code: str | None = None
    crs: str = FEATURE_CRS


def project_etrs89_utm30n(longitude: float, latitude: float) -> tuple[float, float]:
    """WGS84 lon/lat → este/norte en metros (ETRS89 / UTM 30N, EPSG:25830).

    Transversa de Mercator sobre GRS80 (fórmulas de Snyder). Precisión submétrica
    en Bizkaia, suficiente frente a radios de densidad de cientos de metros.
    """
    e2 = _GRS80_F * (2.0 - _GRS80_F)
    ep2 = e2 / (1.0 - e2)
    phi = radians(latitude)
    lam = radians(longitude)
    lam0 = radians(_UTM30_CENTRAL_MERIDIAN_DEG)
    sin_phi = sin(phi)
    cos_phi = cos(phi)
    tan_phi = tan(phi)
    n = _GRS80_A / sqrt(1.0 - e2 * sin_phi * sin_phi)
    t = tan_phi * tan_phi
    c = ep2 * cos_phi * cos_phi
    a = (lam - lam0) * cos_phi
    e4 = e2 * e2
    e6 = e4 * e2
    meridional = _GRS80_A * (
        (1.0 - e2 / 4.0 - 3.0 * e4 / 64.0 - 5.0 * e6 / 256.0) * phi
        - (3.0 * e2 / 8.0 + 3.0 * e4 / 32.0 + 45.0 * e6 / 1024.0) * sin(2.0 * phi)
        + (15.0 * e4 / 256.0 + 45.0 * e6 / 1024.0) * sin(4.0 * phi)
        - (35.0 * e6 / 3072.0) * sin(6.0 * phi)
    )
    a2 = a * a
    a3 = a2 * a
    a4 = a2 * a2
    a5 = a4 * a
    a6 = a3 * a3
    easting = _UTM_FALSE_EASTING + _UTM_K0 * n * (
        a + (1.0 - t + c) * a3 / 6.0 + (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * ep2) * a5 / 120.0
    )
    northing = _UTM_FALSE_NORTHING + _UTM_K0 * (
        meridional
        + n
        * tan_phi
        * (
            a2 / 2.0
            + (5.0 - t + 9.0 * c + 4.0 * c * c) * a4 / 24.0
            + (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * ep2) * a6 / 720.0
        )
    )
    return easting, northing


def haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Distancia geodésica aproximada en metros. Fallback hasta OSRM (2.BE.4)."""
    lat1_r, lon1_r, lat2_r, lon2_r = map(radians, (lat1, lon1, lat2, lon2))
    d_lat, d_lon = lat2_r - lat1_r, lon2_r - lon1_r
    a = sin(d_lat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(d_lon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * asin(sqrt(a))


def classify_kind(
    *,
    density: int,
    municipality_kind: str | None = None,
    urban_density_threshold: int = URBAN_DENSITY_THRESHOLD,
) -> str:
    """Única regla urbano/rural: clase explícita de municipio gana; si no, densidad.

    `municipality_kind` viene del catálogo / `tipo_zona` del dataset. Sin ella,
    `density >= urban_density_threshold` (vecinos en `DENSITY_RADIUS_M`, incluido
    el propio punto) se clasifica urbano. Las zonas `mixed` las decide el clustering.
    """
    if municipality_kind in _VALID_KINDS:
        return municipality_kind
    if density >= urban_density_threshold:
        return _KIND_URBAN
    return _KIND_RURAL


def _speed_kmh_for(kind: str, *, urban_speed_kmh: float, rural_speed_kmh: float) -> float:
    if kind == _KIND_RURAL:
        return rural_speed_kmh
    return urban_speed_kmh


def _resolve_municipality_kind(
    point: ZoningPoint, municipality_kinds: Mapping[str, str] | None
) -> str | None:
    if point.municipality_kind in _VALID_KINDS:
        return point.municipality_kind
    if municipality_kinds is None or point.municipality is None:
        return None
    hint = municipality_kinds.get(point.municipality)
    if hint in _VALID_KINDS:
        return hint
    folded = {key.casefold(): value for key, value in municipality_kinds.items()}
    hint = folded.get(point.municipality.casefold())
    return hint if hint in _VALID_KINDS else None


def _neighbor_count(index: int, projected: Sequence[tuple[float, float]], radius_m: float) -> int:
    x0, y0 = projected[index]
    radius2 = radius_m * radius_m
    return sum(1 for x, y in projected if (x - x0) ** 2 + (y - y0) ** 2 <= radius2)


def compute_features(
    points: Sequence[ZoningPoint],
    depot: ZoningPoint,
    *,
    municipality_kinds: Mapping[str, str] | None = None,
    density_radius_m: float = DENSITY_RADIUS_M,
    urban_density_threshold: int = URBAN_DENSITY_THRESHOLD,
    urban_speed_kmh: float = URBAN_SPEED_KMH,
    rural_speed_kmh: float = RURAL_SPEED_KMH,
) -> list[PointFeatures]:
    """Calcula features por punto. Conserva el orden de entrada. Sin I/O."""
    projected = [project_etrs89_utm30n(point.longitude, point.latitude) for point in points]
    features: list[PointFeatures] = []
    for index, point in enumerate(points):
        x, y = projected[index]
        density = _neighbor_count(index, projected, density_radius_m)
        kind = classify_kind(
            density=density,
            municipality_kind=_resolve_municipality_kind(point, municipality_kinds),
            urban_density_threshold=urban_density_threshold,
        )
        depot_distance_m = haversine_meters(
            point.longitude, point.latitude, depot.longitude, depot.latitude
        )
        speed_kmh = _speed_kmh_for(
            kind, urban_speed_kmh=urban_speed_kmh, rural_speed_kmh=rural_speed_kmh
        )
        depot_time_minutes = (depot_distance_m / 1000.0) / speed_kmh * 60.0
        features.append(
            PointFeatures(
                point_id=point.point_id,
                longitude=point.longitude,
                latitude=point.latitude,
                x=x,
                y=y,
                density=density,
                kind=kind,
                depot_distance_m=depot_distance_m,
                depot_time_minutes=depot_time_minutes,
                municipality=point.municipality,
                postal_code=point.postal_code,
            )
        )
    return features
