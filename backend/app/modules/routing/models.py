"""Modelos ORM de revisiones de ruta. Ref: diseño 6.1–6.2, 3.BE.1.

Una revisión `published` es inmutable en capa de aplicación: no hay trigger de
UPDATE. El CHECK `draft|published` (y `published_at` coherente) documenta el
estado; un cambio posterior crea una nueva revisión `draft`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time

from geoalchemy2 import Geography
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
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

ROUTE_REVISION_STATUSES = ("draft", "published")
ROUTE_OBJECTIVES = ("time", "cost")
SOLVER_STATUSES = (
    "pending",
    "running",
    "feasible",
    "infeasible",
    "timeout",
    "failed",
)
ROUTE_STOP_STATUSES = ("pending", "completed", "failed", "skipped")
ROUTE_METRIC_VARIANTS = ("original", "optimized", "actual")


class RouteRevision(Base):
    __tablename__ = "route_revisions"
    __table_args__ = (
        UniqueConstraint("route_id", "revision", name="uq_route_revisions_route_revision"),
        UniqueConstraint("id", "organization_id", name="uq_route_revisions_id_org"),
        ForeignKeyConstraint(
            ["route_id", "organization_id"],
            ["daily_routes.id", "daily_routes.organization_id"],
            name="fk_route_revisions_route_org",
        ),
        CheckConstraint(f"status IN {ROUTE_REVISION_STATUSES}", name="ck_route_revision_status"),
        CheckConstraint(f"objective IN {ROUTE_OBJECTIVES}", name="ck_route_revision_objective"),
        CheckConstraint(
            f"solver_status IN {SOLVER_STATUSES}", name="ck_route_revision_solver_status"
        ),
        CheckConstraint("revision >= 1", name="ck_route_revision_number"),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) "
            "OR (status = 'published' AND published_at IS NOT NULL)",
            name="ck_route_revision_published_at",
        ),
        Index("ix_route_revisions_organization_id", "organization_id"),
        Index("ix_route_revisions_route_id", "route_id"),
        Index("ix_route_revisions_created_by", "created_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    route_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    objective: Mapped[str] = mapped_column(String(20), nullable=False, default="time")
    # Payload de origen/retorno del solver (p. ej. {"lat": 43.26, "lon": -2.93}).
    origin: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    destination: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    solver_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    constraints_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    osrm_dataset_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RouteStop(Base):
    __tablename__ = "route_stops"
    __table_args__ = (
        UniqueConstraint("revision_id", "sequence", name="uq_route_stops_revision_sequence"),
        UniqueConstraint("revision_id", "patient_id", name="uq_route_stops_revision_patient"),
        ForeignKeyConstraint(
            ["revision_id", "organization_id"],
            ["route_revisions.id", "route_revisions.organization_id"],
            name="fk_route_stops_revision_org",
        ),
        ForeignKeyConstraint(
            ["patient_id", "organization_id"],
            ["patients.id", "patients.organization_id"],
            name="fk_route_stops_patient_org",
        ),
        CheckConstraint(f"status IN {ROUTE_STOP_STATUSES}", name="ck_route_stop_status"),
        CheckConstraint("sequence >= 1", name="ck_route_stop_sequence"),
        CheckConstraint("service_minutes >= 0", name="ck_route_stop_service_minutes"),
        CheckConstraint("version >= 1", name="ck_route_stop_version"),
        CheckConstraint(
            "window_start IS NULL OR window_end IS NULL OR window_start < window_end",
            name="ck_route_stop_window",
        ),
        Index("ix_route_stops_organization_id", "organization_id"),
        Index("ix_route_stops_revision_id", "revision_id"),
        Index("ix_route_stops_patient_id", "patient_id"),
        Index("idx_route_stops_location", "location", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Snapshot cifrado en publish (ADR-08). Optimize puede dejarlo vacío.
    address_snapshot_ciphertext: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    service_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    window_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class RouteMetric(Base):
    __tablename__ = "route_metrics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_id", "organization_id"],
            ["route_revisions.id", "route_revisions.organization_id"],
            name="fk_route_metrics_revision_org",
        ),
        CheckConstraint(f"variant IN {ROUTE_METRIC_VARIANTS}", name="ck_route_metric_variant"),
        CheckConstraint("distance_m >= 0", name="ck_route_metric_distance"),
        CheckConstraint("travel_seconds >= 0", name="ck_route_metric_travel"),
        CheckConstraint("service_seconds >= 0", name="ck_route_metric_service"),
        Index("ix_route_metrics_organization_id", "organization_id"),
        Index("ix_route_metrics_revision_id", "revision_id"),
    )

    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    variant: Mapped[str] = mapped_column(String(20), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    distance_m: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    travel_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    service_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    calculation_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
