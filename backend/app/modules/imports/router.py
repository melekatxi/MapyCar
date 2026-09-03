"""Endpoints de importación. Ref: diseño sección 8.3."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Form, Header, UploadFile
from sqlalchemy.orm import Session

from app.adapters.object_store.interface import ObjectStore
from app.core.crypto import FieldCipher
from app.core.errors import DomainError
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.modules.geocoding.schemas import GeocodeBatchResponse
from app.modules.identity.models import User
from app.modules.imports import service
from app.modules.imports.deps import (
    get_batch_for_member,
    get_field_cipher,
    get_object_store,
    require_import_creator,
    require_organization_access,
)
from app.modules.imports.models import ImportBatch
from app.modules.imports.schemas import (
    ImportBatchCreateResponse,
    ImportBatchOut,
    ImportCommitRequest,
    ImportCommitResponse,
    ImportRowCorrectionRequest,
    ImportRowOut,
    ImportRowsPage,
    PatientsPage,
    PatientSummaryOut,
)

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("", status_code=202, response_model=ImportBatchCreateResponse)
async def create_import(
    file: UploadFile,
    period: str = Form(...),
    mapping: str | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    creator: tuple[User, uuid.UUID] = Depends(require_import_creator),
    db: Session = Depends(get_db),
    object_store: ObjectStore = Depends(get_object_store),
    queue: JobQueue = Depends(get_job_queue),
) -> ImportBatchCreateResponse:
    if not idempotency_key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Falta la cabecera Idempotency-Key")

    current_user, organization_id = creator
    content = await file.read()
    mapping_dict = json.loads(mapping) if mapping else None

    batch = service.create_batch(
        db,
        object_store,
        organization_id=organization_id,
        user_id=current_user.id,
        period=period,
        filename=file.filename or "import",
        content=content,
        mapping=mapping_dict,
    )

    job = queue.enqueue(queue="imports", payload={"batch_id": str(batch.id), "organization_id": str(organization_id)})
    return ImportBatchCreateResponse(
        batch_id=batch.id, job_id=job.id, status=batch.status, status_url=f"/api/v1/imports/{batch.id}"
    )


@router.get("/{batch_id}", response_model=ImportBatchOut)
def get_import(batch: ImportBatch = Depends(get_batch_for_member)) -> ImportBatch:
    return batch


@router.get("/{batch_id}/rows", response_model=ImportRowsPage)
def list_import_rows(
    status: str | None = None,
    after_row: int = 0,
    limit: int = 50,
    batch: ImportBatch = Depends(get_batch_for_member),
    db: Session = Depends(get_db),
    cipher: FieldCipher = Depends(get_field_cipher),
) -> ImportRowsPage:
    rows, decoded_fields, next_after_row = service.list_rows(
        db, cipher, batch_id=batch.id, status_filter=status, after_row=after_row, limit=limit
    )
    return ImportRowsPage(
        rows=[
            ImportRowOut(row_number=row.row_number, validation_status=row.validation_status, errors=row.errors_json, fields=fields)
            for row, fields in zip(rows, decoded_fields, strict=True)
        ],
        next_after_row=next_after_row,
    )


@router.patch("/{batch_id}/rows/{row_number}", response_model=ImportRowOut)
def correct_import_row(
    row_number: int,
    payload: ImportRowCorrectionRequest,
    batch: ImportBatch = Depends(get_batch_for_member),
    db: Session = Depends(get_db),
    cipher: FieldCipher = Depends(get_field_cipher),
) -> ImportRowOut:
    row = service.correct_row(db, cipher, batch_id=batch.id, row_number=row_number, corrected_fields=payload.fields)
    fields = json.loads(cipher.decrypt(row.raw_json_encrypted))
    return ImportRowOut(row_number=row.row_number, validation_status=row.validation_status, errors=row.errors_json, fields=fields)


@router.post("/{batch_id}/commit", response_model=ImportCommitResponse)
def commit_import(
    payload: ImportCommitRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    batch: ImportBatch = Depends(get_batch_for_member),
    db: Session = Depends(get_db),
    cipher: FieldCipher = Depends(get_field_cipher),
) -> ImportCommitResponse:
    if not idempotency_key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Falta la cabecera Idempotency-Key")
    committed, skipped = service.commit_batch(
        db, cipher, batch=batch, accepted_row_numbers=payload.accepted_row_numbers
    )
    return ImportCommitResponse(committed_patients=committed, skipped_rows=skipped)


@router.post("/{batch_id}/geocode", status_code=202, response_model=GeocodeBatchResponse)
def geocode_import(
    batch: ImportBatch = Depends(get_batch_for_member),
    queue: JobQueue = Depends(get_job_queue),
) -> GeocodeBatchResponse:
    """Encola la geocodificación de las direcciones `pending` de los pacientes confirmados (1.BE.11)."""
    job = queue.enqueue(
        queue="geocoding", payload={"batch_id": str(batch.id), "organization_id": str(batch.organization_id)}
    )
    return GeocodeBatchResponse(job_id=job.id, status="queued")


# Router aparte (sin prefijo /imports): los pacientes son un recurso propio, no anidado
# bajo una carga concreta. Soporta el mapa operativo (1.FE.4).
patients_router = APIRouter(prefix="/patients", tags=["patients"])


@patients_router.get("", response_model=PatientsPage)
def list_patients(
    organization_id: uuid.UUID = Depends(require_organization_access),
    db: Session = Depends(get_db),
) -> PatientsPage:
    patients = service.list_patients_with_active_address(db, organization_id=organization_id)
    return PatientsPage(patients=[PatientSummaryOut(**p) for p in patients])

