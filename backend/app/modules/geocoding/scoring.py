"""Scoring y clasificación de candidatos de geocodificación. Ref: RF-05, diseño sección 7.2.

Umbral alto + diferencia suficiente con el segundo candidato para `matched`; el resto
queda `ambiguous` o `not_found`. No se acepta un centroide municipal como domicilio
(un candidato sin `house_number` nunca llega a `matched` en solitario, ver `score_candidate`).
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from app.adapters.geocoder.interface import GeocodeCandidate

MATCH_THRESHOLD = 0.55
AMBIGUOUS_THRESHOLD = 0.3
MIN_MARGIN_OVER_SECOND = 0.15
SAME_LOCATION_RADIUS_METERS = 50.0
EARTH_RADIUS_METERS = 6_371_000.0
# En caseríos/barrios rurales, la propia entidad (sin calle+número) YA es la máxima
# precisión disponible: OSM no modela un "house_number" para ellos. Ref: RF-05 sección 7.2
# ("no se acepta un centroide municipal", pero un caserío no es un centroide municipal).
RURAL_PRECISE_CLASSES = ("village", "hamlet", "isolated_dwelling", "locality", "neighbourhood", "suburb")


def _normalize_text(value: str) -> str:
    return value.strip().casefold()


def score_candidate(candidate: GeocodeCandidate, *, postal_code: str, municipality: str) -> float:
    score = 0.0
    if candidate.postal_code and candidate.postal_code == postal_code:
        score += 0.4
    # Nominatim no siempre desglosa el municipio administrativo para entidades rurales
    # pequeñas (ver docs de la sesión); comprobar también el nombre completo devuelto.
    municipality_matches = (
        candidate.municipality and _normalize_text(candidate.municipality) == _normalize_text(municipality)
    ) or _normalize_text(municipality) in _normalize_text(candidate.display_label)
    if municipality_matches:
        score += 0.3
    if candidate.house_number or candidate.place_class in RURAL_PRECISE_CLASSES:
        score += 0.15
    if candidate.place_class in ("building", "house", "place", *RURAL_PRECISE_CLASSES):
        score += 0.1
    score += min(max(candidate.score, 0.0), 1.0) * 0.05  # importancia Nominatim, desempate menor
    return round(score, 4)


def _same_location(a: GeocodeCandidate, b: GeocodeCandidate) -> bool:
    """Mismo domicilio: mismo portal/CP/municipio, o a menos de 50 m (dos nodos OSM
    distintos para el mismo edificio, p.ej. varios negocios en el mismo portal)."""
    if a.house_number and a.house_number == b.house_number and a.postal_code == b.postal_code:
        return True
    return _haversine_meters(a.latitude, a.longitude, b.latitude, b.longitude) <= SAME_LOCATION_RADIUS_METERS


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r, lat2_r, lon2_r = map(radians, (lat1, lon1, lat2, lon2))
    d_lat, d_lon = lat2_r - lat1_r, lon2_r - lon1_r
    a = sin(d_lat / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * asin(sqrt(a))


def classify(scored_candidates: list[tuple[GeocodeCandidate, float]]) -> str:
    if not scored_candidates:
        return "not_found"

    ranked = sorted(scored_candidates, key=lambda pair: pair[1], reverse=True)
    top_candidate, top_score = ranked[0]

    if top_score < AMBIGUOUS_THRESHOLD:
        return "not_found"
    if top_score < MATCH_THRESHOLD:
        return "ambiguous"

    # Candidatos en la misma ubicación que el mejor (mismo edificio) no cuentan como
    # "segundo candidato" a efectos de ambigüedad: son la misma dirección física.
    distinct_runner_up = next(
        (score for candidate, score in ranked[1:] if not _same_location(candidate, top_candidate)), None
    )
    if distinct_runner_up is not None and top_score - distinct_runner_up < MIN_MARGIN_OVER_SECOND:
        return "ambiguous"
    return "matched"
