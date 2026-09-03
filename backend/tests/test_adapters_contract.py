import respx
from httpx import Response

from app.adapters.geocoder.nominatim import NominatimGeocoder
from app.adapters.router.interface import Coordinate
from app.adapters.router.osrm import OsrmRouter


@respx.mock
async def test_nominatim_geocoder_parses_candidates() -> None:
    respx.get("http://nominatim.test/search").mock(
        return_value=Response(
            200,
            json=[
                {
                    "lat": "43.2630",
                    "lon": "-2.9350",
                    "display_name": "Calle Mayor 1, Bilbao, Bizkaia, España",
                    "importance": 0.8,
                    "class": "building",
                }
            ],
        )
    )
    geocoder = NominatimGeocoder("http://nominatim.test")

    candidates = await geocoder.geocode(address_text="Calle Mayor 1", postal_code="48001", municipality="Bilbao")

    assert len(candidates) == 1
    assert candidates[0].latitude == 43.263
    assert candidates[0].place_class == "building"


@respx.mock
async def test_nominatim_geocoder_maps_jsonv2_category_and_type() -> None:
    respx.get("http://nominatim.test/search").mock(
        return_value=Response(
            200,
            json=[
                {
                    "lat": "43.2820604",
                    "lon": "-2.8979386",
                    "display_name": "Galbarriatu, Zamudio, Bizkaia, 48160, España",
                    "importance": 0.4,
                    "category": "place",
                    "type": "village",
                    "address": {"postcode": "48160", "village": "Zamudio"},
                }
            ],
        )
    )
    geocoder = NominatimGeocoder("http://nominatim.test")

    candidates = await geocoder.geocode(
        address_text="Galbarriatu", postal_code="48160", municipality="Zamudio"
    )

    assert candidates[0].place_class == "village"


@respx.mock
async def test_osrm_router_table_returns_matrix() -> None:
    respx.get(url__startswith="http://osrm.test/table/v1/driving/").mock(
        return_value=Response(200, json={"durations": [[0, 60], [60, 0]], "distances": [[0, 500], [500, 0]]})
    )
    router = OsrmRouter("http://osrm.test")

    matrix = await router.table([Coordinate(43.26, -2.93), Coordinate(43.25, -2.92)])

    assert matrix.durations_seconds == [[0, 60], [60, 0]]
