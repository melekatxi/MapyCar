from __future__ import annotations

from app.adapters.router.interface import Coordinate, DistanceMatrix, Router


class FakeRouter(Router):
    async def table(self, coordinates: list[Coordinate]) -> DistanceMatrix:
        n = len(coordinates)
        return DistanceMatrix(
            durations_seconds=[[0.0 if i == j else 60.0 for j in range(n)] for i in range(n)],
            distances_meters=[[0.0 if i == j else 500.0 for j in range(n)] for i in range(n)],
        )

    async def route(self, coordinates: list[Coordinate]) -> dict:
        return {"geometry": None, "coordinates": [(c.latitude, c.longitude) for c in coordinates]}
