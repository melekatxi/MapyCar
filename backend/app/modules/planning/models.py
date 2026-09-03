"""Modelos ORM de planificación mensual/diaria. Ref: diseño sección 6.1.

`daily_routes.current_revision` apunta a `route_revisions.id` (3.BE.1, nullable).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

# Estados de diseño §5.1 (7.4 no enumera CHECK de status).
MONTHLY_PLAN_STATUSES = ("draft", "validating", "published", "archived")
DAILY_ROUTE_STATUSES = (
    "draft",
    "optimizing",
    "ready",
    "published",
    "in_progress",
    "completed",
    "cancelled",
)


class MonthlyPlan(Base):
    __tablename__ = "monthly_plans"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "team_id",
            "period",
            "version",
            name="uq_monthly_plans_org_team_period_version",
        ),
        UniqueConstraint("id", "organization_id", name="uq_monthly_plans_id_org"),
        ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["teams.id", "teams.organization_id"],
            name="fk_monthly_plans_team_org",
        ),
        CheckConstraint(f"status IN {MONTHLY_PLAN_STATUSES}", name="ck_monthly_plan_status"),
        Index("ix_monthly_plans_organization_id", "organization_id"),
        Index("ix_monthly_plans_team_id", "team_id"),
        Index("ix_monthly_plans_created_by", "created_by"),
        Index("ix_monthly_plans_org_period_status", "organization_id", "period", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Shape: CalendarConstraints.to_json() en calendar.py (weekday_mask ISO, holidays,
    # extra_off_days, workday/service minutes, max_visits, zone_kind, window, timezone).
    constraints_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Resultado del solver (2.BE.11): calendar, assignments, metrics.
    # 2.BE.13 materializa DailyRoute al publicar; current_revision se rellena en Fase 3.
    result_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    conflicts_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DailyRoute(Base):
    __tablename__ = "daily_routes"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "service_date",
            "zone_id",
            "assignee_id",
            name="uq_daily_routes_plan_date_zone_assignee",
        ),
        ForeignKeyConstraint(
            ["plan_id", "organization_id"],
            ["monthly_plans.id", "monthly_plans.organization_id"],
            name="fk_daily_routes_plan_org",
        ),
        ForeignKeyConstraint(
            ["zone_id", "organization_id"],
            ["zones.id", "zones.organization_id"],
            name="fk_daily_routes_zone_org",
        ),
        ForeignKeyConstraint(
            ["assignee_id", "organization_id"],
            ["user_memberships.user_id", "user_memberships.organization_id"],
            name="fk_daily_routes_assignee_org",
        ),
        UniqueConstraint("id", "organization_id", name="uq_daily_routes_id_org"),
        ForeignKeyConstraint(
            ["current_revision", "organization_id"],
            ["route_revisions.id", "route_revisions.organization_id"],
            name="fk_daily_routes_current_revision_org",
            use_alter=True,
        ),
        CheckConstraint(f"status IN {DAILY_ROUTE_STATUSES}", name="ck_daily_route_status"),
        Index("ix_daily_routes_organization_id", "organization_id"),
        Index("ix_daily_routes_plan_id", "plan_id"),
        Index("ix_daily_routes_zone_id", "zone_id"),
        Index("ix_daily_routes_assignee_id", "assignee_id"),
        Index("ix_daily_routes_date_assignee_status", "service_date", "assignee_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    assignee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    current_revision: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


# Resuelve la FK current_revision → route_revisions sin ciclo de importación inverso.
from app.modules.routing import models as _routing_models  # noqa: F401
