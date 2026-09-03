"""Esquemas Pydantic del módulo de geocodificación. Ref: diseño sección 8.3."""
from __future__ import annotations

import uuid

from pydantic import BaseModel


class GeocodeBatchResponse(BaseModel):
    job_id: str
    status: str


class CandidateOut(BaseModel):
    lat: float
    lon: float
    score: float
    place_class: str | None = None


class AddressCandidatesOut(BaseModel):
    address_id: uuid.UUID
    geocode_status: str
    candidates: list[CandidateOut]


class GeocodeSelectionRequest(BaseModel):
    candidate_index: int | None = None
    lat: float | None = None
    lon: float | None = None
    reason: str


class AddressOut(BaseModel):
    id: uuid.UUID
    geocode_status: str
    confidence: float | None
    postal_code: str
    municipality: str
    province: str

    model_config = {"from_attributes": True}
