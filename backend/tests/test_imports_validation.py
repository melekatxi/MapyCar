"""Validaciones de fila de importación (funciones puras). Ref: RF-02, 1.BE.3."""
from __future__ import annotations

from app.modules.imports.validation import validate_row_fields


def _valid_row() -> dict[str, str]:
    return {
        "id_paciente": "PAC-001",
        "nombre_referencia": "Paciente 001",
        "direccion": "Calle Ledesma 12, 3º Izq",
        "codigo_postal": "48001",
        "municipio": "Bilbao",
        "provincia": "Bizkaia",
    }


def test_valid_row_has_no_errors() -> None:
    assert validate_row_fields(_valid_row()) == []


def test_missing_required_field_is_reported() -> None:
    row = _valid_row()
    row["direccion"] = ""

    errors = validate_row_fields(row)

    assert {"field": "direccion", "code": "REQUIRED_FIELD_MISSING"} in errors


def test_invalid_postal_code_format_is_reported() -> None:
    row = _valid_row()
    row["codigo_postal"] = "480A1"

    errors = validate_row_fields(row)

    assert {"field": "codigo_postal", "code": "INVALID_POSTAL_CODE_FORMAT"} in errors


def test_formula_injection_prefix_is_rejected() -> None:
    row = _valid_row()
    row["direccion"] = "=cmd|'/c calc'!A1"

    errors = validate_row_fields(row)

    assert {"field": "direccion", "code": "FORMULA_INJECTION_REJECTED"} in errors


def test_field_too_long_is_reported() -> None:
    row = _valid_row()
    row["direccion"] = "A" * 301

    errors = validate_row_fields(row)

    assert {"field": "direccion", "code": "FIELD_TOO_LONG"} in errors


def test_control_characters_are_reported() -> None:
    row = _valid_row()
    row["municipio"] = "Bilbao\x00"

    errors = validate_row_fields(row)

    assert {"field": "municipio", "code": "INVALID_CHARACTERS"} in errors
