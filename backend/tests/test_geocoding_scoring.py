"""Scoring y clasificación de candidatos de geocodificación. Ref: 1.BE.10."""
from __future__ import annotations

from app.adapters.geocoder.interface import GeocodeCandidate
from app.modules.geocoding.scoring import classify, score_candidate


def _candidate(**overrides) -> GeocodeCandidate:
    defaults = {
        "latitude": 43.26,
        "longitude": -2.93,
        "display_label": "Calle Mayor 1, Bilbao",
        "score": 0.5,
        "place_class": "building",
        "postal_code": "48001",
        "municipality": "Bilbao",
        "house_number": "1",
    }
    defaults.update(overrides)
    return GeocodeCandidate(**defaults)


def test_full_match_scores_high() -> None:
    score = score_candidate(_candidate(), postal_code="48001", municipality="Bilbao")
    assert score >= 0.55


def test_wrong_postal_code_and_municipality_scores_low() -> None:
    candidate = _candidate(
        postal_code="48002",
        municipality="Barakaldo",
        display_label="Calle Mayor 1, Barakaldo",
        house_number=None,
        place_class="place",
    )
    score = score_candidate(candidate, postal_code="48001", municipality="Bilbao")
    assert score < 0.3


def test_classify_empty_candidates_is_not_found() -> None:
    assert classify([]) == "not_found"


def test_classify_single_strong_candidate_is_matched() -> None:
    assert classify([(_candidate(), 0.9)]) == "matched"


def test_classify_low_score_is_not_found() -> None:
    assert classify([(_candidate(), 0.1)]) == "not_found"


def test_classify_close_candidates_at_different_locations_is_ambiguous() -> None:
    other_location = _candidate(latitude=43.30, longitude=-2.80, house_number="2")
    result = classify([(_candidate(), 0.7), (other_location, 0.65)])
    assert result == "ambiguous"


def test_classify_close_scores_at_same_location_is_matched() -> None:
    # Dos nodos OSM del mismo portal (p.ej. dos negocios): no es ambigüedad real.
    result = classify([(_candidate(), 0.7), (_candidate(), 0.65)])
    assert result == "matched"


def test_classify_clear_winner_is_matched() -> None:
    result = classify([(_candidate(), 0.9), (_candidate(), 0.4)])
    assert result == "matched"


def test_rural_hamlet_without_house_number_scores_as_matched() -> None:
    hamlet = _candidate(
        house_number=None,
        place_class="hamlet",
        postal_code="48260",
        municipality="Zaldibar",
        display_label="Sallabente, Zaldibar, Bizkaia, 48260",
    )
    score = score_candidate(hamlet, postal_code="48260", municipality="Zaldibar")
    assert score >= 0.55
    assert classify([(hamlet, score)]) == "matched"


def test_rural_place_beats_same_name_highway() -> None:
    place = _candidate(
        house_number=None,
        place_class="village",
        postal_code="48160",
        municipality="Zamudio",
        display_label="Galbarriatu, Zamudio, 48160",
        latitude=43.28206,
        longitude=-2.89794,
    )
    highway = _candidate(
        house_number=None,
        place_class="highway",
        postal_code="48160",
        municipality="Zamudio",
        display_label="Galbarriatu, Egirleta errepidea, Zamudio, 48160",
        latitude=43.28232,
        longitude=-2.89723,
    )
    place_score = score_candidate(place, postal_code="48160", municipality="Zamudio")
    highway_score = score_candidate(highway, postal_code="48160", municipality="Zamudio")
    assert classify([(place, place_score), (highway, highway_score)]) == "matched"
