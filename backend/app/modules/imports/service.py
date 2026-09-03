"""Lógica de negocio de importación. Ref: RF-01 a RF-04, diseño sección 7.1."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime

from geoalchemy2 import Geometry
from sqlalchemy import and_, cast, func
from sqlalchemy.orm import Session

from app.adapters.object_store.interface import ObjectStore
from app.core.crypto import FieldCipher
from app.core.errors import DomainError
from app.core.ids import uuid7
from app.modules.identity import service as identity_service
from app.modules.imports import parsing
from app.modules.imports.models import Address, ImportBatch, ImportRow, Patient
from app.modules.imports.validation import validate_row_fields
from app.modules.zoning.models import Zone, ZoneAssignment

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MiB; ver criterio RNF-01/sección 7.1
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _object_store_key(*, organization_id: uuid.UUID, batch_id: uuid.UUID, filename: str) -> str:
    return f"imports/{organization_id}/{batch_id}/{filename}"


def _normalized_external_ref_hash(external_ref: str) -> str:
    normalized = external_ref.strip().casefold()
    return hashlib.sha256(normalized.encode()).hexdigest()


def create_batch(
    db: Session,
    object_store: ObjectStore,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    period: str,
    filename: str,
    content: bytes,
    mapping: dict[str, str] | None = None,
) -> ImportBatch:
    if not PERIOD_RE.match(period):
        raise DomainError(422, "INVALID_PERIOD", "El periodo debe tener formato AAAA-MM")
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise DomainError(413, "FILE_TOO_LARGE", "El fichero supera el tamaño máximo permitido")
    # Valida la firma real del fichero (415 si no coincide con la extensión declarada).
    parsing.detect_format(filename=filename, content=content)

    file_hash = sha256_hex(content)
    existing = (
        db.query(ImportBatch)
        .filter(
            ImportBatch.organization_id == organization_id,
            ImportBatch.period == period,
            ImportBatch.file_sha256 == file_hash,
            ImportBatch.status != "cancelled",
        )
        .one_or_none()
    )
    if existing is not None:
        raise DomainError(409, "IMPORT_DUPLICATE", "Ya existe una carga con el mismo fichero y periodo")

    batch = ImportBatch(
        id=uuid7(),
        organization_id=organization_id,
        period=period,
        filename=filename,
        file_sha256=file_hash,
        status="uploaded",
        mapping_json=mapping or {},
        counts_json={},
        created_by=user_id,
    )
    db.add(batch)
    db.flush()

    object_store.put(
        key=_object_store_key(organization_id=organization_id, batch_id=batch.id, filename=filename),
        content=content,
        content_type="application/octet-stream",
    )
    db.commit()
    return batch


def validate_import(
    db: Session,
    object_store: ObjectStore,
    cipher: FieldCipher,
    *,
    batch_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> ImportBatch:
    """Worker `validate_import` (1.BE.2): parsea, normaliza y deja las filas en staging.

    Se ejecuta fuera de una petición HTTP (sin `current_user`), así que recibe
    `organization_id` explícito para fijar el contexto RLS antes de leer el batch.
    """
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.organization_id != organization_id:
        raise DomainError(404, "IMPORT_BATCH_NOT_FOUND", "Carga no encontrada")

    batch.status = "validating"
    db.flush()

    content = object_store.get(
        key=_object_store_key(organization_id=batch.organization_id, batch_id=batch.id, filename=batch.filename)
    )
    rows = parsing.parse_rows(filename=batch.filename, content=content, mapping=batch.mapping_json or None)

    seen_hashes_in_batch: set[str] = set()
    other_batches_refs = _existing_external_refs_for_period(
        db, organization_id=batch.organization_id, period=batch.period, exclude_batch_id=batch.id
    )

    valid_count = 0
    invalid_count = 0
    for index, row in enumerate(rows, start=1):
        errors = validate_row_fields(row)
        external_ref = (row.get("id_paciente") or "").strip()

        if external_ref:
            ref_hash = _normalized_external_ref_hash(external_ref)
            if ref_hash in seen_hashes_in_batch:
                errors.append({"field": "id_paciente", "code": "DUPLICATE_IN_BATCH"})
            elif ref_hash in other_batches_refs:
                errors.append({"field": "id_paciente", "code": "DUPLICATE_IN_PERIOD"})
            seen_hashes_in_batch.add(ref_hash)
        normalized_hash = _normalized_external_ref_hash(external_ref) if external_ref else uuid7().hex

        status = "invalid" if errors else "valid"
        if status == "valid":
            valid_count += 1
        else:
            invalid_count += 1

        db.add(
            ImportRow(
                id=uuid7(),
                batch_id=batch.id,
                row_number=index,
                raw_json_encrypted=cipher.encrypt(json.dumps(row, ensure_ascii=False)),
                normalized_hash=normalized_hash,
                validation_status=status,
                errors_json=errors,
            )
        )

    batch.counts_json = {"total": len(rows), "valid": valid_count, "invalid": invalid_count}
    batch.status = "requires_correction" if invalid_count else "validated"
    batch.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(batch)
    return batch


def _existing_external_refs_for_period(
    db: Session, *, organization_id: uuid.UUID, period: str, exclude_batch_id: uuid.UUID
) -> set[str]:
    rows = (
        db.query(ImportRow)
        .join(ImportBatch, ImportRow.batch_id == ImportBatch.id)
        .filter(
            ImportBatch.organization_id == organization_id,
            ImportBatch.period == period,
            ImportBatch.id != exclude_batch_id,
            ImportBatch.status != "cancelled",
            ImportRow.validation_status.in_(("valid", "corrected")),
        )
        .all()
    )
    refs: set[str] = set()
    for row in rows:
        # El hash normalizado ya identifica la referencia; reconstruir el valor exacto
        # requeriría descifrar cada fila. Se compara por hash en el flujo principal
        # y este set solo se usa para el caso, más costoso, de listar por periodo.
        refs.add(row.normalized_hash)
    return refs


def list_rows(
    db: Session,
    cipher: FieldCipher,
    *,
    batch_id: uuid.UUID,
    status_filter: str | None,
    after_row: int,
    limit: int,
) -> tuple[list[ImportRow], list[dict[str, str | None]], int | None]:
    query = db.query(ImportRow).filter(ImportRow.batch_id == batch_id, ImportRow.row_number > after_row)
    if status_filter:
        query = query.filter(ImportRow.validation_status == status_filter)
    rows = query.order_by(ImportRow.row_number).limit(limit + 1).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    decoded = [json.loads(cipher.decrypt(row.raw_json_encrypted)) for row in rows]
    next_after_row = rows[-1].row_number if has_more and rows else None
    return rows, decoded, next_after_row


def correct_row(
    db: Session,
    cipher: FieldCipher,
    *,
    batch_id: uuid.UUID,
    row_number: int,
    corrected_fields: dict[str, str],
) -> ImportRow:
    row = (
        db.query(ImportRow)
        .filter(ImportRow.batch_id == batch_id, ImportRow.row_number == row_number)
        .one_or_none()
    )
    if row is None:
        raise DomainError(404, "IMPORT_ROW_NOT_FOUND", "Fila no encontrada")

    current = json.loads(cipher.decrypt(row.raw_json_encrypted))
    current.update(corrected_fields)

    errors = validate_row_fields(current)
    row.raw_json_encrypted = cipher.encrypt(json.dumps(current, ensure_ascii=False))
    row.errors_json = errors
    row.validation_status = "invalid" if errors else "corrected"
    db.flush()

    batch = db.get(ImportBatch, batch_id)
    if batch is not None:
        remaining_invalid = (
            db.query(func.count(ImportRow.id))
            .filter(ImportRow.batch_id == batch_id, ImportRow.validation_status == "invalid")
            .scalar()
        )
        batch.status = "validated" if remaining_invalid == 0 else "requires_correction"
    db.commit()
    db.refresh(row)
    return row


def commit_batch(
    db: Session,
    cipher: FieldCipher,
    *,
    batch: ImportBatch,
    accepted_row_numbers: list[int],
) -> tuple[int, int]:
    if batch.status not in ("validated", "requires_correction"):
        raise DomainError(409, "IMPORT_BATCH_NOT_COMMITTABLE", "La carga no está en un estado que permita confirmar")

    rows = (
        db.query(ImportRow)
        .filter(
            ImportRow.batch_id == batch.id,
            ImportRow.row_number.in_(accepted_row_numbers),
            ImportRow.validation_status.in_(("valid", "corrected")),
        )
        .all()
    )
    skipped = len(accepted_row_numbers) - len(rows)

    committed = 0
    for row in rows:
        data = json.loads(cipher.decrypt(row.raw_json_encrypted))
        external_ref = data["id_paciente"].strip()
        display_ref = (data.get("nombre_referencia") or external_ref).strip()

        patient = (
            db.query(Patient)
            .filter(Patient.organization_id == batch.organization_id, Patient.external_ref == external_ref)
            .one_or_none()
        )
        if patient is None:
            patient = Patient(
                id=uuid7(),
                organization_id=batch.organization_id,
                external_ref=external_ref,
                display_ref=display_ref,
                source_batch_id=batch.id,
            )
            db.add(patient)
            db.flush()
        else:
            patient.display_ref = display_ref
            patient.updated_at = datetime.now(UTC)

        previous_active = (
            db.query(Address).filter(Address.patient_id == patient.id, Address.is_active.is_(True)).one_or_none()
        )
        next_version = 1
        if previous_active is not None:
            previous_active.is_active = False
            next_version = previous_active.version + 1

        db.add(
            Address(
                id=uuid7(),
                organization_id=batch.organization_id,
                patient_id=patient.id,
                address_ciphertext=cipher.encrypt(data["direccion"].strip()),
                postal_code=data["codigo_postal"].strip(),
                municipality=data["municipio"].strip(),
                province=data["provincia"].strip(),
                geocode_status="pending",
                is_active=True,
                version=next_version,
            )
        )
        row.patient_id = patient.id
        committed += 1

    db.commit()
    return committed, skipped


def list_patients_with_active_address(db: Session, *, organization_id: uuid.UUID) -> list[dict]:
    """Pacientes + dirección activa de una organización (para el mapa operativo, 1.FE.4).

    `zone_id` / `assigned_zone` salen de `zone_assignments` vigentes (`valid_to IS NULL`).
    No incluye calle ni nombre real (ADR-09).
    """
    rows = (
        db.query(
            Patient,
            Address,
            func.ST_Y(cast(Address.location, Geometry)),
            func.ST_X(cast(Address.location, Geometry)),
            Zone.id,
            Zone.name,
        )
        .join(Address, Address.patient_id == Patient.id)
        .outerjoin(
            ZoneAssignment,
            and_(
                ZoneAssignment.patient_id == Patient.id,
                ZoneAssignment.organization_id == organization_id,
                ZoneAssignment.valid_to.is_(None),
            ),
        )
        .outerjoin(
            Zone,
            and_(Zone.id == ZoneAssignment.zone_id, Zone.organization_id == organization_id),
        )
        .filter(
            Patient.organization_id == organization_id,
            Address.organization_id == organization_id,
            Address.is_active.is_(True),
        )
        .all()
    )
    return [
        {
            "id": patient.id,
            "external_ref": patient.external_ref,
            "display_ref": patient.display_ref,
            "address_id": address.id,
            "postal_code": address.postal_code,
            "municipality": address.municipality,
            "province": address.province,
            "geocode_status": address.geocode_status,
            "confidence": address.confidence,
            "latitude": lat,
            "longitude": lon,
            # Fase 2 DailyRoute: no hay visitas planificadas; RF-07 exige el campo.
            "visit_status": "pending",
            "assigned_day": None,
            "assigned_zone": zone_name,
            "zone_id": zone_id,
        }
        for patient, address, lat, lon, zone_id, zone_name in rows
    ]
