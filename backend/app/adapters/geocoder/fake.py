"""Doble de prueba del Geocoder para tests unitarios/de contrato."""
from __future__ import annotations

from app.adapters.geocoder.interface import GeocodeCandidate, Geocoder


class FakeGeocoder(Geocoder):
    def __init__(self, candidates: list[GeocodeCandidate] | None = None) -> None:
        self._candidates = candidates or []
        self.calls: list[str] = []

    async def geocode(
        self, *, address_text: str, postal_code: str | None, municipality: str | None
    ) -> list[GeocodeCandidate]:
        self.calls.append(address_text)
        return self._candidates
