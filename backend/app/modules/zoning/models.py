"""Modelos ORM de zonificación. Ref: diseño sección 6.1. No conoce planificación publicada."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from geoalchemy2 import Geography, Geometry
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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

ZONE_KINDS = ("urban", "rural", "mixed")
ZONE_ASSIGNMENT_SOURCES = ("cluster", "postal", "manual")
ZONE_PROPOSAL_STATUSES = ("queued", "running", "succeeded", "failed")


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_zones_org_name"),
        UniqueConstraint("id", "organization_id", name="uq_zones_id_org"),
        CheckConstraint(f"kind IN {ZONE_KINDS}", name="ck_zone_kind"),
        Index("ix_zones_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    max_visits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    boundary = mapped_column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=True)
    centroid = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ZoneAssignment(Base):
    __tablename__ = "zone_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["zone_id", "organization_id"],
            ["zones.id", "zones.organization_id"],
            name="fk_zone_assignments_zone_org",
        ),
        ForeignKeyConstraint(
            ["patient_id", "organization_id"],
            ["patients.id", "patients.organization_id"],
            name="fk_zone_assignments_patient_org",
        ),
        CheckConstraint(f"source IN {ZONE_ASSIGNMENT_SOURCES}", name="ck_zone_assignment_source"),
        Index(
            "uq_zone_assignments_current_patient",
            "patient_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
        Index("ix_zone_assignments_zone_id", "zone_id"),
        Index("ix_zone_assignments_patient_id", "patient_id"),
        Index("ix_zone_assignments_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ZoneProposal(Base):
    """Propuesta de clustering persistida. El status Redis es efímero; esta tabla es el recurso 8.4.

    Delta respecto a diseño 6.1 (no listaba `zone_proposals`): sin esta tabla GET no puede
    devolver clusters/outliers/métricas tras expirar el job.
    """

    __tablename__ = "zone_proposals"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_zone_proposals_id_org"),
        CheckConstraint(f"status IN {ZONE_PROPOSAL_STATUSES}", name="ck_zone_proposal_status"),
        Index("ix_zone_proposals_organization_id", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    params_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
