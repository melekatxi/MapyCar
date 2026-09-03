"""Lógica de geocodificación. Ref: RF-05, diseño sección 7.2, 1.BE.8 a 1.BE.13."""
from __future__ import annotations

import asyncio
import uuid

import httpx
from sqlalchemy.orm import Session

from app.adapters.geocoder.interface import GeocodeCandidate, Geocoder
from app.core.crypto import FieldCipher
from app.core.ids import uuid7
from app.modules.geocoding.cache import GeocodeCache
from app.modules.geocoding.models import GeocodeAttempt
from app.modules.geocoding.normalization import normalize_for_geocoding, strip_floor_door
from app.modules.geocoding.overlay import HousenumberOverlay, apply_overlay, get_default_overlay
from app.modules.geocoding.scoring import classify, score_candidate
from app.modules.imports.models import Address, ImportRow

MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _point_ewkt(candidate: GeocodeCandidate) -> str:
    return f"SRID=4326;POINT({candidate.longitude} {candidate.latitude})"


async def _geocode_with_retry(
    geocoder: Geocoder, *, address_text: str, postal_code: str, municipality: str
) -> list[GeocodeCandidate]:
    """Reintento exponencial ante 429/5xx (1.BE.13)."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await geocoder.geocode(address_text=address_text, postal_code=postal_code, municipality=municipality)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    return []  # pragma: no cover - inalcanzable, el bucle siempre retorna o lanza


async def geocode_address(
    db: Session,
    geocoder: Geocoder,
    cache: GeocodeCache,
    cipher: FieldCipher,
    *,
    address: Address,
    overlay: HousenumberOverlay | None = None,
) -> Address:
    """Normaliza, consulta caché/Nominatim, puntúa y clasifica. Ref: 1.BE.8, 1.BE.9, 1.BE.10, 1.BE.13."""
    original_text = cipher.decrypt(address.address_ciphertext)
    normalized = normalize_for_geocoding(strip_floor_door(original_text))
    gazetteer = overlay if overlay is not None else get_default_overlay()

    query_hash = GeocodeCache.hash_query(normalized, postal_code=address.postal_code, municipality=address.municipality)
    cached = cache.get(query_hash)
    if cached is not None:
        candidates = [GeocodeCandidate(**c) for c in cached]
    else:
        try:
            candidates = await _geocode_with_retry(
                geocoder, address_text=normalized, postal_code=address.postal_code, municipality=address.municipality
            )
        except httpx.HTTPStatusError:
            candidates = []

        overlay_hit = gazetteer.lookup_from_address(
            normalized, postal_code=address.postal_code, municipality=address.municipality
        )
        if not candidates and overlay_hit is None:
            # Fallback (1.BE.13): sin portal en Nominatim ni overlay, buscar CP+municipio.
            try:
                candidates = await _geocode_with_retry(
                    geocoder,
                    address_text=address.municipality,
                    postal_code=address.postal_code,
                    municipality=address.municipality,
                )
            except httpx.HTTPStatusError:
                candidates = []
        cache.set(query_hash, [vars(c) for c in candidates])

    candidates = apply_overlay(
        candidates,
        address_text=normalized,
        postal_code=address.postal_code,
        municipality=address.municipality,
        overlay=gazetteer,
    )
    scored = [(c, score_candidate(c, postal_code=address.postal_code, municipality=address.municipality)) for c in candidates]
    outcome = classify(scored)
    best_candidate, best_score = max(scored, key=lambda pair: pair[1]) if scored else (None, None)

    db.add(
        GeocodeAttempt(
            id=uuid7(),
            address_id=address.id,
            provider="nominatim",
            query_hash=query_hash,
            candidate_json_minimized=[
                {"lat": c.latitude, "lon": c.longitude, "score": s, "class": c.place_class} for c, s in scored[:5]
            ],
            result_location=_point_ewkt(best_candidate) if outcome == "matched" and best_candidate else None,
            score=best_score,
            outcome=outcome,
        )
    )

    address.geocode_status = outcome
    address.confidence = best_score
    if outcome == "matched" and best_candidate:
        address.location = _point_ewkt(best_candidate)
    db.commit()
    db.refresh(address)
    return address


async def geocode_eligible_addresses_for_batch(
    db: Session,
    geocoder: Geocoder,
    cache: GeocodeCache,
    cipher: FieldCipher,
    *,
    batch_id: uuid.UUID,
    overlay: HousenumberOverlay | None = None,
) -> dict[str, int]:
    """Worker de `POST /imports/{id}/geocode` (1.BE.11): geocodifica direcciones `pending`."""
    patient_ids = {
        row.patient_id
        for row in db.query(ImportRow).filter(ImportRow.batch_id == batch_id, ImportRow.patient_id.isnot(None)).all()
    }
    addresses = (
        db.query(Address)
        .filter(Address.patient_id.in_(patient_ids), Address.is_active.is_(True), Address.geocode_status == "pending")
        .all()
        if patient_ids
        else []
    )

    counts = {"matched": 0, "ambiguous": 0, "not_found": 0}
    for address in addresses:
        updated = await geocode_address(db, geocoder, cache, cipher, address=address, overlay=overlay)
        counts[updated.geocode_status] = counts.get(updated.geocode_status, 0) + 1
    return counts


def get_latest_candidates(db: Session, *, address_id: uuid.UUID) -> GeocodeAttempt | None:
    return (
        db.query(GeocodeAttempt)
        .filter(GeocodeAttempt.address_id == address_id)
        .order_by(GeocodeAttempt.requested_at.desc())
        .first()
    )


def select_candidate(
    db: Session,
    *,
    address: Address,
    candidate_index: int | None,
    manual_latitude: float | None,
    manual_longitude: float | None,
    reason: str,
    reviewed_by: uuid.UUID,
) -> Address:
    """Confirma la dirección: candidato elegido o marcador manual (1.BE.12). Siempre registra motivo."""
    if candidate_index is not None:
        latest = get_latest_candidates(db, address_id=address.id)
        candidates = latest.candidate_json_minimized if latest else []
        if latest is None or candidate_index < 0 or candidate_index >= len(candidates):
            raise ValueError("candidate_index fuera de rango")
        chosen = candidates[candidate_index]
        latitude, longitude = chosen["lat"], chosen["lon"]
    elif manual_latitude is not None and manual_longitude is not None:
        latitude, longitude = manual_latitude, manual_longitude
    else:
        raise ValueError("Debe indicarse candidate_index o {lat, lon}")

    point = f"SRID=4326;POINT({longitude} {latitude})"
    db.add(
        GeocodeAttempt(
            id=uuid7(),
            address_id=address.id,
            provider="manual",
            query_hash="manual",
            candidate_json_minimized=[{"manual_reason": reason}],
            result_location=point,
            score=1.0,
            outcome="manual",
            reviewed_by=reviewed_by,
        )
    )
    address.location = point
    address.geocode_status = "manual"
    address.confidence = 1.0
    db.commit()
    db.refresh(address)
    return address
