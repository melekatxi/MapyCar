"""Normalización de direcciones antes de geocodificar. Ref: RF-05, diseño sección 7.2.

Nunca debe usarse para alterar el original almacenado (`address_ciphertext`); solo
para construir la consulta al geocodificador.
"""
from __future__ import annotations

import re
import unicodedata

_ABBREVIATIONS = {
    r"\bc/\.?": "Calle",
    r"\bcl\.?\b": "Calle",
    r"\bavda\.?": "Avenida",
    r"\bavd\.?": "Avenida",
    r"\bpl\.?\b": "Plaza",
    r"\bpza\.?": "Plaza",
    r"\bpso\.?": "Paseo",
    r"\bctra\.?": "Carretera",
}


def normalize_for_geocoding(address_text: str) -> str:
    """Unicode NFC, espacios colapsados y abreviaturas controladas expandidas."""
    text = unicodedata.normalize("NFC", address_text).strip()
    for pattern, replacement in _ABBREVIATIONS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def strip_floor_door(address_text: str) -> str:
    """Retira piso/puerta (todo tras la primera coma); OSM no modela esa unidad.

    P.ej. "Calle Ledesma 12, 3º Izq" -> "Calle Ledesma 12".
    """
    return address_text.split(",", 1)[0].strip()


_HOUSE_NUMBER_RE = re.compile(r"^(?P<street>.+?)\s+(?P<number>\d+[A-Za-z]?)$")


def parse_street_and_number(address_text: str) -> tuple[str, str | None]:
    """Separa el portal del final de la dirección ya recortada (sin piso/puerta).

    "Calle Ledesma 12" -> ("Calle Ledesma", "12"). Sin número, el texto entero
    queda como calle y el portal es None (caseríos/barrios rurales).
    """
    text = address_text.strip()
    match = _HOUSE_NUMBER_RE.fullmatch(text)
    if match is None:
        return text, None
    return match.group("street").strip(), match.group("number")
