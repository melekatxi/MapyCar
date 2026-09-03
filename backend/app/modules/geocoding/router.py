"""Endpoints de geocodificación sobre direcciones. Ref: diseño sección 8.3, 1.BE.12."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.session import get_db
from app.modules.geocoding import service
from app.modules.geocoding.deps import get_address_for_member
from app.modules.geocoding.schemas import (
    AddressCandidatesOut,
    CandidateOut,
    GeocodeSelectionRequest,
)
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.imports.models import Address

router = APIRouter(prefix="/addresses", tags=["geocoding"])


@router.get("/{address_id}/candidates", response_model=AddressCandidatesOut)
def get_candidates(
    address: Address = Depends(get_address_for_member),
    db: Session = Depends(get_db),
) -> AddressCandidatesOut:
    latest = service.get_latest_candidates(db, address_id=address.id)
    candidates = latest.candidate_json_minimized if latest else []
    return AddressCandidatesOut(
        address_id=address.id,
        geocode_status=address.geocode_status,
        candidates=[
            CandidateOut(lat=c["lat"], lon=c["lon"], score=c["score"], place_class=c.get("class"))
            for c in candidates
            if "lat" in c
        ],
    )


@router.post("/{address_id}/geocode-selection", response_model=AddressCandidatesOut)
def confirm_geocode_selection(
    payload: GeocodeSelectionRequest,
    address: Address = Depends(get_address_for_member),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AddressCandidatesOut:
    try:
        updated = service.select_candidate(
            db,
            address=address,
            candidate_index=payload.candidate_index,
            manual_latitude=payload.lat,
            manual_longitude=payload.lon,
            reason=payload.reason,
            reviewed_by=current_user.id,
        )
    except ValueError as exc:
        raise DomainError(422, "INVALID_GEOCODE_SELECTION", str(exc)) from exc

    return AddressCandidatesOut(address_id=updated.id, geocode_status=updated.geocode_status, candidates=[])
