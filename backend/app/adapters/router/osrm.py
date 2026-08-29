"""Adaptador OSRM autoalojado. Ref: ADR-07, diseño sección 7.5."""
from __future__ import annotations

import httpx

from app.adapters.router.interface import Coordinate, DistanceMatrix, Router


class OsrmRouter(Router):
    def __init__(self, base_url: str, *, profile: str = "driving") -> None:
        self._base_url = base_url.rstrip("/")
        self._profile = profile

    def _coords_param(self, coordinates: list[Coordinate]) -> str:
        return ";".join(f"{c.longitude},{c.latitude}" for c in coordinates)

    async def table(self, coordinates: list[Coordinate]) -> DistanceMatrix:
        coords = self._coords_param(coordinates)
        url = f"{self._base_url}/table/v1/{self._profile}/{coords}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params={"annotations": "duration,distance"})
            response.raise_for_status()
            payload = response.json()
        return DistanceMatrix(
            durations_seconds=payload["durations"], distances_meters=payload["distances"]
        )

    async def route(self, coordinates: list[Coordinate]) -> dict:
        coords = self._coords_param(coordinates)
        url = f"{self._base_url}/route/v1/{self._profile}/{coords}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params={"overview": "full", "geometries": "geojson"})
            response.raise_for_status()
            return response.json()
