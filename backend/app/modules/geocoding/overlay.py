"""Gazetteer local de portales (piloto Bizkaia). Ref: RF-05.

Nominatim sigue siendo el geocodificador primario. Este overlay solo aporta un
punto de portal cuando la consulta tiene calle+número y esa clave está en el
fichero (CSV/GeoJSON) cargado desde una fuente independiente (callejero Eustat,
Cartociudad, geometría OSM ya existente). No inventa números.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.adapters.geocoder.interface import GeocodeCandidate
from app.modules.geocoding.normalization import parse_street_and_number

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_OVERLAY_CSV = DATA_DIR / "housenumber_overlay.csv"

# Prefijos de vía (es/eu) que no forman parte de la clave de calle.
_VIA_TOKENS = {
    "calle",
    "cl",
    "c",
    "avenida",
    "avda",
    "avd",
    "av",
    "alameda",
    "aldea",
    "plaza",
    "pl",
    "pza",
    "paseo",
    "pso",
    "barrio",
    "carretera",
    "ctra",
    "gran",
    "via",
    "kalea",
    "etorbidea",
    "zumarkalea",
    "zumardia",
    "auzoa",
    "errepidea",
    "de",
    "del",
    "la",
    "las",
    "el",
    "los",
}

# Variantes ortográficas frecuentes en el piloto (consulta → forma canónica).
STREET_ALIASES = {
    "rekalde": "recalde",
    "errekalde": "recalde",
    "iparragirre": "iparraguirre",
    "zumalacarregui": "zumalakarregi",
}


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_street_key(street: str) -> str:
    """Calle comparable: sin acentos, sin tipo de vía, con alias aplicados."""
    folded = re.sub(r"[^a-z0-9\s-]", " ", _fold(street))
    tokens = [tok for tok in re.split(r"[\s-]+", folded) if tok and tok not in _VIA_TOKENS]
    key = " ".join(tokens)
    return STREET_ALIASES.get(key, key)


def _normalize_house_number(number: str) -> str:
    return number.strip().casefold()


def _normalize_municipality(municipality: str) -> str:
    return _fold(municipality).strip()


def _nominatim_has_same_portal(candidate: GeocodeCandidate, point: OverlayPoint) -> bool:
    """True solo si Nominatim ya trajo ESTE portal, no otro con el mismo número.

    Un `house_number` suelto no basta: «Barrio Bengoetxe 5» devolvía el 5 de
    Olabarrieta (otro CP, otra vía) y el overlay se auto-desactivaba.
    """
    if candidate.house_number is None:
        return False
    if _normalize_house_number(candidate.house_number) != _normalize_house_number(point.house_number):
        return False
    folded_label = _fold(candidate.display_label)
    names = (point.street, *point.aliases)
    return any(_fold(name) in folded_label or normalize_street_key(name) in folded_label for name in names if name)


@dataclass(frozen=True)
class OverlayPoint:
    street: str
    house_number: str
    municipality: str
    postal_code: str
    latitude: float
    longitude: float
    source: str
    source_ref: str = ""
    aliases: tuple[str, ...] = ()

    def to_candidate(self) -> GeocodeCandidate:
        label = f"{self.street} {self.house_number}, {self.postal_code} {self.municipality}"
        return GeocodeCandidate(
            latitude=self.latitude,
            longitude=self.longitude,
            display_label=label,
            score=1.0,
            place_class="house",
            postal_code=self.postal_code or None,
            municipality=self.municipality,
            house_number=self.house_number,
        )


def _parse_aliases(raw: str | list | tuple | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return tuple(part.strip() for part in str(raw).split("|") if part.strip())


class HousenumberOverlay:
    """Índice calle+número+municipio[/CP] → punto de portal."""

    def __init__(self, points: list[OverlayPoint] | None = None) -> None:
        self._by_cp: dict[tuple[str, str, str, str], OverlayPoint] = {}
        self._by_muni: dict[tuple[str, str, str], OverlayPoint] = {}
        for point in points or []:
            self._index(point)

    def _index(self, point: OverlayPoint) -> None:
        street_names = (point.street, *point.aliases)
        hn = _normalize_house_number(point.house_number)
        muni = _normalize_municipality(point.municipality)
        cp = point.postal_code.strip()
        for name in street_names:
            street = normalize_street_key(name)
            if not street or not hn or not muni:
                continue
            self._by_muni.setdefault((street, hn, muni), point)
            if cp:
                self._by_cp.setdefault((street, hn, muni, cp), point)

    @classmethod
    def from_csv(cls, path: Path) -> HousenumberOverlay:
        overlay = cls()
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                overlay._index(
                    OverlayPoint(
                        street=row["street"].strip(),
                        house_number=row["house_number"].strip(),
                        municipality=row["municipality"].strip(),
                        postal_code=(row.get("postal_code") or "").strip(),
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                        source=(row.get("source") or "").strip(),
                        source_ref=(row.get("source_ref") or "").strip(),
                        aliases=_parse_aliases(row.get("aliases")),
                    )
                )
        return overlay

    @classmethod
    def from_geojson(cls, path: Path) -> HousenumberOverlay:
        overlay = cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        for feature in payload.get("features", []):
            props = feature.get("properties") or {}
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            overlay._index(
                OverlayPoint(
                    street=str(props.get("street") or "").strip(),
                    house_number=str(props.get("house_number") or "").strip(),
                    municipality=str(props.get("municipality") or "").strip(),
                    postal_code=str(props.get("postal_code") or "").strip(),
                    latitude=float(coords[1]),
                    longitude=float(coords[0]),
                    source=str(props.get("source") or "").strip(),
                    source_ref=str(props.get("source_ref") or "").strip(),
                    aliases=_parse_aliases(props.get("aliases")),
                )
            )
        return overlay

    @classmethod
    def from_records(cls, points: list[OverlayPoint]) -> HousenumberOverlay:
        return cls(points)

    def lookup(
        self,
        *,
        street: str,
        house_number: str,
        municipality: str,
        postal_code: str | None = None,
    ) -> OverlayPoint | None:
        street_key = normalize_street_key(street)
        hn = _normalize_house_number(house_number)
        muni = _normalize_municipality(municipality)
        if not street_key or not hn or not muni:
            return None
        if postal_code:
            hit = self._by_cp.get((street_key, hn, muni, postal_code.strip()))
            if hit is not None:
                return hit
        return self._by_muni.get((street_key, hn, muni))

    def lookup_from_address(
        self, address_text: str, *, postal_code: str, municipality: str
    ) -> OverlayPoint | None:
        street, number = parse_street_and_number(address_text)
        if number is None:
            return None
        return self.lookup(
            street=street, house_number=number, municipality=municipality, postal_code=postal_code
        )

    def augment(
        self,
        candidates: list[GeocodeCandidate],
        *,
        address_text: str,
        postal_code: str,
        municipality: str,
    ) -> list[GeocodeCandidate]:
        """Inserta el portal del overlay si Nominatim no trajo ese house_number.

        Si el overlay aporta el portal, se descartan candidatos sin número (tramo
        de calle o centroide municipal) para no contaminar el margen de `classify`.
        Nominatim con el mismo portal (mismo número **y** misma vía) se deja
        tal cual (primario). Un portal homónimo en otra calle no cuenta.
        """
        point = self.lookup_from_address(
            address_text, postal_code=postal_code, municipality=municipality
        )
        if point is None:
            return candidates
        if any(_nominatim_has_same_portal(c, point) for c in candidates):
            return candidates
        overlay_candidate = point.to_candidate()
        numbered = [c for c in candidates if c.house_number]
        return [overlay_candidate, *numbered]


@lru_cache
def get_default_overlay() -> HousenumberOverlay:
    if not DEFAULT_OVERLAY_CSV.is_file():
        return HousenumberOverlay()
    return HousenumberOverlay.from_csv(DEFAULT_OVERLAY_CSV)


def apply_overlay(
    candidates: list[GeocodeCandidate],
    *,
    address_text: str,
    postal_code: str,
    municipality: str,
    overlay: HousenumberOverlay | None = None,
) -> list[GeocodeCandidate]:
    gazetteer = overlay if overlay is not None else get_default_overlay()
    return gazetteer.augment(
        candidates, address_text=address_text, postal_code=postal_code, municipality=municipality
    )
