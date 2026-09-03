"""Modelos ORM de importación. Ref: diseño sección 6.1. No conoce geocodificación/zonificación."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

IMPORT_BATCH_STATUSES = (
    "uploaded",
    "validating",
    "requires_correction",
    "validated",
    "geocoding",
    "ready",
    "failed",
    "cancelled",
)
IMPORT_ROW_STATUSES = ("pending", "valid", "invalid", "corrected")
GEOCODE_STATUSES = ("pending", "matched", "ambiguous", "not_found", "manual")


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        Index(
            "uq_import_batches_org_period_hash_active",
            "organization_id",
            "period",
            "file_sha256",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
        CheckConstraint(f"status IN {IMPORT_BATCH_STATUSES}", name="ck_import_batch_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="uploaded")
    mapping_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    counts_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_import_rows_batch_row"),
        CheckConstraint(f"validation_status IN {IMPORT_ROW_STATUSES}", name="ck_import_row_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_json_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    errors_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=True)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("organization_id", "external_ref", name="uq_patients_org_ref"),
        # UNIQUE (id, organization_id) habilita FK compuesta tenant-safe desde zone_assignments.
        UniqueConstraint("id", "organization_id", name="uq_patients_id_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    external_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    display_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    source_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class Address(Base):
    __tablename__ = "addresses"
    __table_args__ = (
        Index("uq_addresses_active_per_patient", "patient_id", unique=True, postgresql_where=text("is_active")),
        CheckConstraint(f"geocode_status IN {GEOCODE_STATUSES}", name="ck_address_geocode_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False)
    address_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    postal_code: Mapped[str] = mapped_column(String(5), nullable=False)
    municipality: Mapped[str] = mapped_column(String(150), nullable=False)
    province: Mapped[str] = mapped_column(String(150), nullable=False)
    location = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    geocode_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
