"""Outbox transaccional y notificaciones in-app. Ref: 4.BE.9, diseño 6.1 / 11.1.

`outbox_events` nació en 2.BE.13 (Alembic e4c8a2b91d07). Esta tarea añade
`notifications` y el consumidor idempotente por `event_id`. GET/PATCH = 4.BE.10.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

EVENT_PLAN_PUBLISHED = "plan.published"
EVENT_SHARE_CREATED = "share.created"
EVENT_SHARE_REVOKED = "share.revoked"
EVENT_ROUTE_REASSIGNED = "route.reassigned"

RESOURCE_MONTHLY_PLAN = "monthly_plan"
RESOURCE_SHARE_GRANT = "share_grant"
RESOURCE_DAILY_ROUTE = "daily_route"

NOTIFICATION_ROUTE_SHARED = "route.shared"
NOTIFICATION_ROUTE_REASSIGNED = "route.reassigned"
NOTIFICATION_PLAN_PUBLISHED = "plan.published"

NOTIFICATION_STATUS_UNREAD = "unread"
NOTIFICATION_STATUS_READ = "read"


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


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_notifications_id_org"),
        UniqueConstraint("event_id", "recipient_id", name="uq_notifications_event_recipient"),
        CheckConstraint(
            "\"type\" IN ('route.shared', 'route.reassigned', 'plan.published')",
            name="ck_notifications_type",
        ),
        CheckConstraint(
            "status IN ('unread', 'read')",
            name="ck_notifications_status",
        ),
        ForeignKeyConstraint(
            ["recipient_id", "organization_id"],
            ["user_memberships.user_id", "user_memberships.organization_id"],
            name="fk_notifications_recipient_org",
        ),
        ForeignKeyConstraint(
            ["event_id", "organization_id"],
            ["outbox_events.id", "outbox_events.organization_id"],
            name="fk_notifications_event_org",
        ),
        Index("ix_notifications_organization_id", "organization_id"),
        Index("ix_notifications_recipient_status", "recipient_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NOTIFICATION_STATUS_UNREAD
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
