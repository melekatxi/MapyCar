"""Normalización de direcciones antes de geocodificar. Ref: 1.BE.8."""
from __future__ import annotations

from app.modules.geocoding.normalization import (
    normalize_for_geocoding,
    parse_street_and_number,
    strip_floor_door,
)


def test_strip_floor_door_removes_everything_after_first_comma() -> None:
    assert strip_floor_door("Calle Ledesma 12, 3º Izq") == "Calle Ledesma 12"


def test_strip_floor_door_keeps_address_without_floor() -> None:
    assert strip_floor_door("Bengoetxe 5") == "Bengoetxe 5"


def test_normalize_expands_controlled_abbreviations() -> None:
    assert normalize_for_geocoding("C/ Mayor 1") == "Calle Mayor 1"
    assert normalize_for_geocoding("Avda. Zumalakarregi 40") == "Avenida Zumalakarregi 40"


def test_normalize_collapses_whitespace_and_keeps_original_untouched() -> None:
    original = "Calle   Mayor    1"
    assert normalize_for_geocoding(original) == "Calle Mayor 1"
    assert original == "Calle   Mayor    1"  # el original nunca se muta


def test_parse_street_and_number_splits_portal() -> None:
    assert parse_street_and_number("Calle Ledesma 12") == ("Calle Ledesma", "12")
    assert parse_street_and_number("Avenida de Zumalakarregi 40") == ("Avenida de Zumalakarregi", "40")
    assert parse_street_and_number("Galbarriatu") == ("Galbarriatu", None)
    assert parse_street_and_number("Irazola Auzoa") == ("Irazola Auzoa", None)
