import pytest

from app.adapters.geocoder.fake import FakeGeocoder
from app.adapters.geocoder.interface import GeocodeCandidate, Geocoder
from app.adapters.optimizer.fake import FakeOptimizer
from app.adapters.router.fake import FakeRouter
from app.adapters.router.interface import Coordinate


async def _consume_geocoder(geocoder: Geocoder) -> list[GeocodeCandidate]:
    return await geocoder.geocode(address_text="Calle Mayor 1", postal_code="48001", municipality="Bilbao")


@pytest.mark.asyncio
async def test_fake_geocoder_can_replace_real_implementation_transparently() -> None:
    expected = [GeocodeCandidate(latitude=43.26, longitude=-2.93, display_label="Bilbao", score=0.9)]
    geocoder: Geocoder = FakeGeocoder(candidates=expected)

    result = await _consume_geocoder(geocoder)

    assert result == expected


@pytest.mark.asyncio
async def test_fake_router_returns_square_matrix() -> None:
    router = FakeRouter()
    coords = [Coordinate(43.26, -2.93), Coordinate(43.25, -2.92), Coordinate(43.24, -2.91)]

    matrix = await router.table(coords)

    assert len(matrix.durations_seconds) == 3
    assert all(len(row) == 3 for row in matrix.durations_seconds)


def test_fake_optimizer_returns_identity_order() -> None:
    optimizer = FakeOptimizer()
    result = optimizer.solve(
        durations_seconds=[[0, 1], [1, 0]],
        distances_meters=[[0, 10], [10, 0]],
        vehicle_count=2,
        objective="cost",
        time_windows=[None, (0.0, 100.0)],
    )
    assert result.order == [0, 1]
    assert result.diagnostics == []
    assert result.estimated_cost == 0.0
    assert result.service_duration_seconds == 0.0
    assert result.routes == []
