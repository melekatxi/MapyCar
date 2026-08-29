"""Adaptador Nominatim autoalojado. Ref: ADR-07, diseño sección 7.2."""
from __future__ import annotations

import httpx

from app.adapters.geocoder.interface import GeocodeCandidate, Geocoder

USER_AGENT = "sofia-app/0.1 (contacto: soporte@sofia.example)"


class NominatimGeocoder(Geocoder):
    def __init__(self, base_url: str, *, bounding_box: tuple[float, float, float, float] | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._bounding_box = bounding_box  # (min_lon, min_lat, max_lon, max_lat) de Bizkaia/Euskadi

    async def geocode(
        self, *, address_text: str, postal_code: str | None, municipality: str | None
    ) -> list[GeocodeCandidate]:
        query_parts = [address_text]
        if postal_code:
            query_parts.append(postal_code)
        if municipality:
            query_parts.append(municipality)
        params: dict[str, str] = {
            "q": ", ".join(query_parts),
            "format": "jsonv2",
            "limit": "5",
            "addressdetails": "1",
        }
        if self._bounding_box:
            min_lon, min_lat, max_lon, max_lat = self._bounding_box
            params["viewbox"] = f"{min_lon},{max_lat},{max_lon},{min_lat}"
            params["bounded"] = "1"

        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base_url}/search", params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()

        return [
            GeocodeCandidate(
                latitude=float(item["lat"]),
                longitude=float(item["lon"]),
                display_label=item.get("display_name", ""),
                score=float(item.get("importance", 0.0)),
                place_class=item.get("class"),
            )
            for item in payload
        ]
