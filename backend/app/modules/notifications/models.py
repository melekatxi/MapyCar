"""Outbox transaccional. Delta vs diseño 6.1/4.BE.9: no hay tabla `notifications` aún.

2.BE.13 persiste `plan.published` aquí en la misma transacción que daily_routes.
Fase 4 consumirá estas filas; `processed_at` queda nulo hasta entonces.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

EVENT_PLAN_PUBLISHED = "plan.published"
RESOURCE_MONTHLY_PLAN = "monthly_plan"


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_outbox_events_id_org"),
        Index("ix_outbox_events_organization_id", "organization_id"),
        Index("ix_outbox_events_resource", "resource_type", "resource_id"),
        Index(
            "ix_outbox_events_unprocessed",
            "processed_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
