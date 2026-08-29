from __future__ import annotations

from app.adapters.tile_provider.interface import TileProvider


class OsmTileProvider(TileProvider):
    """Teselas públicas OSM: solo para desarrollo. Ver ADR-07 para producción autoalojada."""

    def tile_url_template(self) -> str:
        return "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


class FakeTileProvider(TileProvider):
    def tile_url_template(self) -> str:
        return "http://fake-tiles.test/{z}/{x}/{y}.png"
