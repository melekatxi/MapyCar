"""Puerto Geocoder. Ref: ADR-06. Ningún controlador debe invocar Nominatim directamente."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GeocodeCandidate:
    latitude: float
    longitude: float
    display_label: str
    score: float
    place_class: str | None = None


class Geocoder(ABC):
    @abstractmethod
    async def geocode(
        self, *, address_text: str, postal_code: str | None, municipality: str | None
    ) -> list[GeocodeCandidate]:
        """Devuelve hasta 5 candidatos para una dirección mínima (sin nombre de paciente)."""
