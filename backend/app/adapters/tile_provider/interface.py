"""Puerto TileProvider. Ref: ADR-06, ADR-02. Por defecto teselas OpenStreetMap, sin coste."""
from __future__ import annotations

from abc import ABC, abstractmethod


class TileProvider(ABC):
    @abstractmethod
    def tile_url_template(self) -> str:
        """URL de plantilla de teselas ({z}/{x}/{y}) para el mapa Leaflet."""
