"""Gazetteer local de portales. No requiere Nominatim vivo."""
from __future__ import annotations

import json
from pathlib import Path

from app.adapters.geocoder.interface import GeocodeCandidate
from app.modules.geocoding.overlay import (
    DEFAULT_OVERLAY_CSV,
    HousenumberOverlay,
    OverlayPoint,
    apply_overlay,
    normalize_street_key,
)


def _street_candidate() -> GeocodeCandidate:
    return GeocodeCandidate(
        latitude=43.26,
        longitude=-2.93,
        display_label="Recalde zumarkalea, Bilbao",
        score=0.2,
        place_class="highway",
        postal_code="48009",
        municipality="Bilbao",
        house_number=None,
    )


def _overlay() -> HousenumberOverlay:
    return HousenumberOverlay.from_records(
        [
            OverlayPoint(
                street="Recalde",
                house_number="33",
                municipality="Bilbao",
                postal_code="48009",
                latitude=43.26357,
                longitude=-2.934599,
                source="eustat-callejero-bizkaia",
                source_ref="test",
                aliases=("rekalde",),
            )
        ]
    )


def test_normalize_street_key_strips_via_and_aliases() -> None:
    assert normalize_street_key("Calle Rekalde") == "recalde"
    assert normalize_street_key("Alameda Recalde") == "recalde"
    assert normalize_street_key("Avenida de Zumalakarregi") == "zumalakarregi"
    assert normalize_street_key("Calle Iparragirre") == "iparraguirre"


def test_overlay_lookup_by_alias_and_municipality_when_cp_differs() -> None:
    overlay = _overlay()
    hit = overlay.lookup(
        street="Calle Rekalde", house_number="33", municipality="Bilbao", postal_code="48000"
    )
    assert hit is not None
    assert hit.latitude == 43.26357
    assert hit.house_number == "33"


def test_overlay_does_not_invent_missing_housenumber() -> None:
    overlay = _overlay()
    assert (
        overlay.lookup(street="Zabalbide", house_number="90", municipality="Bilbao", postal_code="48006")
        is None
    )


def test_augment_replaces_street_centroid_with_portal() -> None:
    overlay = _overlay()
    result = overlay.augment(
        [_street_candidate()],
        address_text="Calle Rekalde 33",
        postal_code="48009",
        municipality="Bilbao",
    )
    assert len(result) == 1
    assert result[0].house_number == "33"
    assert result[0].place_class == "house"


def test_augment_ignores_homonymous_housenumber_on_another_street() -> None:
    overlay = HousenumberOverlay.from_records(
        [
            OverlayPoint(
                street="Bengoetxe",
                house_number="5",
                municipality="Galdakao",
                postal_code="48960",
                latitude=43.232828,
                longitude=-2.860011,
                source="eustat-callejero-bizkaia",
                source_ref="test",
            )
        ]
    )
    other_street = GeocodeCandidate(
        latitude=43.23638435,
        longitude=-2.86857745,
        display_label="5, Olabarrieta auzoa, Olabarrieta, Galdakao, Bizkaia, Euskadi, 48970, España",
        score=0.01,
        place_class="house",
        postal_code="48970",
        municipality="Galdakao",
        house_number="5",
    )
    result = overlay.augment(
        [other_street],
        address_text="Barrio Bengoetxe 5",
        postal_code="48960",
        municipality="Galdakao",
    )
    assert result[0].house_number == "5"
    assert result[0].postal_code == "48960"
    assert "Bengoetxe" in result[0].display_label
    assert other_street in result


def test_augment_keeps_nominatim_when_it_already_has_the_portal() -> None:
    overlay = _overlay()
    nominatim = GeocodeCandidate(
        latitude=43.2635728,
        longitude=-2.9345862,
        display_label="33, Recalde zumarkalea, Bilbao",
        score=0.8,
        place_class="house",
        postal_code="48009",
        municipality="Bilbao",
        house_number="33",
    )
    result = overlay.augment(
        [nominatim],
        address_text="Calle Rekalde 33",
        postal_code="48009",
        municipality="Bilbao",
    )
    assert result == [nominatim]


def test_from_csv_and_geojson_roundtrip(tmp_path: Path) -> None:
    csv_path = tmp_path / "overlay.csv"
    csv_path.write_text(
        "street,house_number,municipality,postal_code,latitude,longitude,source,source_ref,aliases\n"
        "Iturribide,53,Bilbao,48006,43.257044,-2.917171,eustat,ref,\n",
        encoding="utf-8",
    )
    from_csv = HousenumberOverlay.from_csv(csv_path)
    hit = from_csv.lookup(street="Calle Iturribide", house_number="53", municipality="Bilbao")
    assert hit is not None

    geojson_path = tmp_path / "overlay.geojson"
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [-2.917171, 43.257044]},
                        "properties": {
                            "street": "Iturribide",
                            "house_number": "53",
                            "municipality": "Bilbao",
                            "postal_code": "48006",
                            "source": "eustat",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    from_geojson = HousenumberOverlay.from_geojson(geojson_path)
    geo_hit = from_geojson.lookup(street="Iturribide", house_number="53", municipality="Bilbao")
    assert geo_hit is not None
    assert geo_hit.latitude == 43.257044


def test_seed_csv_covers_justified_pilot_portals_only() -> None:
    overlay = HousenumberOverlay.from_csv(DEFAULT_OVERLAY_CSV)
    assert overlay.lookup(street="Rekalde", house_number="33", municipality="Bilbao") is not None
    assert overlay.lookup(street="Mazarredo", house_number="15", municipality="Bilbao") is not None
    assert overlay.lookup(street="Zumalakarregi", house_number="40", municipality="Bilbao") is not None
    assert overlay.lookup(street="Iparragirre", house_number="60", municipality="Bilbao") is not None
    # Portal rural oficial (Eustat Bengoetxe 5); Nominatim no trae el housenumber.
    rural = overlay.lookup(street="Barrio Bengoetxe", house_number="5", municipality="Galdakao")
    assert rural is not None
    assert rural.house_number == "5"
    assert rural.postal_code == "48960"
    # Números que el callejero oficial de Eustat no contiene: no se inventan.
    assert overlay.lookup(street="Zabalbide", house_number="90", municipality="Bilbao") is None
    assert overlay.lookup(street="Iturribide", house_number="55", municipality="Bilbao") is None
    assert overlay.lookup(street="Kirikiño", house_number="3", municipality="Bilbao") is None
    assert overlay.lookup(street="Bengoetxe", house_number="4", municipality="Galdakao") is None


def test_apply_overlay_default_is_noop_without_portal() -> None:
    street = _street_candidate()
    result = apply_overlay(
        [street], address_text="Galbarriatu", postal_code="48160", municipality="Zamudio"
    )
    assert result == [street]
