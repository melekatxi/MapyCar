"""Validaciones de fila de importación. Ref: RF-02, diseño sección 7.1.

Funciones puras (sin acceso a BD); la detección de duplicados internos/contra periodo
necesita contexto de otras filas y vive en `service.py`.
"""
from __future__ import annotations

import re

POSTAL_CODE_RE = re.compile(r"^\d{5}$")
MAX_FIELD_LENGTH = 300
# Prefijos de inyección de fórmula (CSV/Excel): si una hoja de cálculo abre este valor,
# lo interpretaría como fórmula. Se rechaza en vez de "evaluar de forma segura".
FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
REQUIRED_FIELDS = ("id_paciente", "direccion", "codigo_postal", "municipio", "provincia")


def validate_row_fields(row: dict[str, str | None]) -> list[dict[str, str]]:
    """Valida una fila normalizada. Devuelve una lista de `{field, code}`."""
    errors: list[dict[str, str]] = []

    for field in REQUIRED_FIELDS:
        value = (row.get(field) or "").strip()
        if not value:
            errors.append({"field": field, "code": "REQUIRED_FIELD_MISSING"})

    for field, raw_value in row.items():
        if raw_value is None:
            continue
        text_value = str(raw_value)
        if text_value.startswith(FORMULA_INJECTION_PREFIXES):
            errors.append({"field": field, "code": "FORMULA_INJECTION_REJECTED"})
        if len(text_value) > MAX_FIELD_LENGTH:
            errors.append({"field": field, "code": "FIELD_TOO_LONG"})
        if any(ord(ch) < 32 and ch != "\n" for ch in text_value):
            errors.append({"field": field, "code": "INVALID_CHARACTERS"})

    postal_code = (row.get("codigo_postal") or "").strip()
    if postal_code and not POSTAL_CODE_RE.match(postal_code):
        errors.append({"field": "codigo_postal", "code": "INVALID_POSTAL_CODE_FORMAT"})

    return errors
