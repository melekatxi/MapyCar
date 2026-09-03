"""Features de zonificación sobre fixture urbano/rural de Bizkaia. Ref: 2.BE.2, RF-12."""

from __future__ import annotations

from app.modules.zoning.features import (
    DENSITY_RADIUS_M,
    FEATURE_CRS,
    URBAN_DENSITY_THRESHOLD,
    ZoningPoint,
    classify_kind,
    compute_features,
    project_etrs89_utm30n,
)

# Depósito en Abando (Bilbao). Gran Vía Don Diego López de Haro.
_DEPOT = ZoningPoint(
    longitude=-2.9348,
    latitude=43.2630,
    point_id="depot",
    municipality="Bilbao",
    postal_code="48001",
)

# Cluster denso en Abando/Casco Viejo: todos a <300 m entre sí (radio 500 m).
_URBAN_OFFSETS_DEG = (
    (0.0, 0.0),
    (0.0010, 0.0),
    (-0.0010, 0.0),
    (0.0, 0.0014),
    (0.0, -0.0014),
    (0.0008, 0.0010),
    (-0.0008, 0.0010),
    (0.0008, -0.0010),
)

# Caseríos aislados: Karrantza (oeste) y Orduña (sur). Decenas de km al depósito.
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
)


def _bilbao_fixture() -> list[ZoningPoint]:
    points: list[ZoningPoint] = []
    for index, (d_lat, d_lon) in enumerate(_URBAN_OFFSETS_DEG):
        points.append(
            ZoningPoint(
                longitude=_DEPOT.longitude + d_lon,
                latitude=_DEPOT.latitude + d_lat,
                point_id=f"urban-bilbao-{index}",
                municipality="Bilbao",
                postal_code="48001",
            )
        )
    points.extend(_RURAL_POINTS)
    return points


def test_features_classify_bilbao_urban_and_caserio_rural() -> None:
    features = compute_features(_bilbao_fixture(), _DEPOT)
    by_id = {item.point_id: item for item in features}

    urban = [item for item in features if item.point_id and item.point_id.startswith("urban-")]
    rural = [item for item in features if item.point_id and item.point_id.startswith("rural-")]

    assert len(urban) == len(_URBAN_OFFSETS_DEG)
    assert len(rural) == len(_RURAL_POINTS)
    assert all(item.kind == "urban" for item in urban)
    assert all(item.kind == "rural" for item in rural)
    assert all(item.density >= URBAN_DENSITY_THRESHOLD for item in urban)
    assert all(item.density == 1 for item in rural)
    assert by_id["rural-karrantza"].municipality == "Karrantza Harana"


def test_projected_coords_are_metres_epsg_25830_not_wgs84_degrees() -> None:
    features = compute_features(_bilbao_fixture(), _DEPOT)
    urban = next(item for item in features if item.point_id == "urban-bilbao-0")
    rural = next(item for item in features if item.point_id == "rural-karrantza")

    assert FEATURE_CRS == "EPSG:25830"
    assert urban.crs == FEATURE_CRS
    # Este UTM 30N en Bizkaia: ~470–510 km. Norte: ~4.76–4.80 Mm. No son grados WGS84.
    for item in (urban, rural):
        assert 400_000 < item.x < 600_000
        assert 4_700_000 < item.y < 4_850_000
        assert abs(item.x) > 180
        assert abs(item.y) > 90
    # Karrantza está al oeste del meridiano −3° → este menor que Bilbao.
    assert rural.x < urban.x
    # Distancia proyectada entre dos portales de Abando es cientos de metros, no ~0.001°.
    neighbour = next(item for item in features if item.point_id == "urban-bilbao-1")
    projected_m = ((urban.x - neighbour.x) ** 2 + (urban.y - neighbour.y) ** 2) ** 0.5
    assert 50 < projected_m < DENSITY_RADIUS_M


def test_depot_time_rural_exceeds_urban_when_depot_in_bilbao() -> None:
    features = compute_features(_bilbao_fixture(), _DEPOT)
    urban_times = [
        item.depot_time_minutes
        for item in features
        if item.point_id and item.point_id.startswith("urban-")
    ]
    rural_times = [
        item.depot_time_minutes
        for item in features
        if item.point_id and item.point_id.startswith("rural-")
    ]
    assert max(urban_times) < 10
    assert min(rural_times) > max(urban_times)
    karrantza = next(item for item in features if item.point_id == "rural-karrantza")
    # ~35 km a 35 km/h → ~60 min; no es un valor de OSRM.
    assert karrantza.depot_distance_m > 30_000
    assert 40 < karrantza.depot_time_minutes < 90


def test_municipality_kind_hint_overrides_local_density() -> None:
    isolated_in_named_urban = ZoningPoint(
        longitude=-2.70,
        latitude=43.35,
        point_id="lonely-getxo",
        municipality="Getxo",
        postal_code="48992",
    )
    features = compute_features(
        [isolated_in_named_urban],
        _DEPOT,
        municipality_kinds={"Getxo": "urban"},
    )
    assert features[0].density == 1
    assert features[0].kind == "urban"


def test_classify_kind_is_the_single_rule() -> None:
    assert classify_kind(density=1) == "rural"
    assert classify_kind(density=URBAN_DENSITY_THRESHOLD) == "urban"
    assert classify_kind(density=1, municipality_kind="urban") == "urban"
    assert classify_kind(density=20, municipality_kind="rural") == "rural"


def test_project_known_bilbao_point_is_utm30n() -> None:
    easting, northing = project_etrs89_utm30n(-2.9348, 43.2630)
    # Gran Vía, comprobado contra la fórmula Snyder/GRS80 (no contra un servicio).
    assert abs(easting - 505_292) < 5
    assert abs(northing - 4_790_023) < 5


def test_empty_input_returns_empty_features() -> None:
    assert compute_features([], _DEPOT) == []
