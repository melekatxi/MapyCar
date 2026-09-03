"""Esquemas Pydantic del módulo de importación. Ref: diseño sección 8.3."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ImportBatchCreateResponse(BaseModel):
    batch_id: uuid.UUID
    job_id: str
    status: str
    status_url: str


class ImportBatchOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    period: str
    filename: str
    status: str
    counts_json: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportRowErrorOut(BaseModel):
    field: str
    code: str


class ImportRowOut(BaseModel):
    row_number: int
    validation_status: str
    errors: list[ImportRowErrorOut]
    fields: dict[str, str | None]


class ImportRowsPage(BaseModel):
    rows: list[ImportRowOut]
    next_after_row: int | None


class ImportRowCorrectionRequest(BaseModel):
    fields: dict[str, str]


class ImportCommitRequest(BaseModel):
    accepted_row_numbers: list[int]


class ImportCommitResponse(BaseModel):
    committed_patients: int
    skipped_rows: int


class PatientSummaryOut(BaseModel):
    id: uuid.UUID
    external_ref: str
    display_ref: str
    address_id: uuid.UUID
    postal_code: str
    municipality: str
    province: str
    geocode_status: str
    confidence: float | None
    latitude: float | None
    longitude: float | None
    # RF-07: el mapa distingue pendiente/planificada/completada. Hasta Fase 2
    # (DailyRoute) el origen es siempre "pending"; no fingir planificación.
    visit_status: Literal["pending", "planned", "completed"]
    assigned_day: str | None = None
    assigned_zone: str | None = None
    # Asignación vigente (zone_assignments.valid_to IS NULL). Nombre de zona, no calle.
    zone_id: uuid.UUID | None = None


class PatientsPage(BaseModel):
    patients: list[PatientSummaryOut]

