"""Esquemas Pydantic de planes mensuales. Ref: diseño sección 8.4, RF-13."""

from __future__ import annotations

import uuid
from datetime import date as Date
from typing import Any

from pydantic import BaseModel, Field


class PlanCreateRequest(BaseModel):
    organization_id: uuid.UUID
    team_id: uuid.UUID
    period: str = Field(min_length=7, max_length=7)
    constraints: dict[str, Any] = Field(default_factory=dict)


class PlanCreateResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    team_id: uuid.UUID
    period: str
    status: str
    version: int
    constraints: dict[str, Any]
    created_by: uuid.UUID


class PlanListItem(BaseModel):
    """Listado delgado para el calendario (2.FE.2). Sin calendar/assignments."""

    id: uuid.UUID
    period: str
    status: str
    team_id: uuid.UUID


class PlansPage(BaseModel):
    plans: list[PlanListItem]


class PlanGenerateResponse(BaseModel):
    id: uuid.UUID
    job_id: str
    status: str


class WorkingDayOut(BaseModel):
    date: Date
    capacity_visits: int
    capacity_minutes: int
    zone_kind: str
    window_start: str | None = None
    window_end: str | None = None


class MonthlyCalendarOut(BaseModel):
    period: str
    timezone: str
    working_days: list[WorkingDayOut]
    skipped_holidays: list[Date]


class PlanAssignmentOut(BaseModel):
    patient_id: uuid.UUID
    date: Date
    zone_id: uuid.UUID


class PlanConflictOut(BaseModel):
    code: str
    patient_id: uuid.UUID
    date: Date | None = None
    zone_id: uuid.UUID | None = None
    detail: str = ""


class PlanMetricsOut(BaseModel):
    n_assigned: int
    n_conflicts: int


class PlanOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    team_id: uuid.UUID
    period: str
    status: str
    version: int
    constraints: dict[str, Any]
    calendar: MonthlyCalendarOut
    assignments: list[PlanAssignmentOut]
    conflicts: list[PlanConflictOut]
    metrics: PlanMetricsOut
    job_id: str | None = None
    created_by: uuid.UUID


class PlanValidateResponse(BaseModel):
    conflicts: list[PlanConflictOut]
    warnings: list[PlanConflictOut]


class PlanMoveVisitRequest(BaseModel):
    """`confirm` omitido o false = dry-run; no muta."""

    date: Date
    zone_id: uuid.UUID
    confirm: bool = False


class PlanMoveVisitResponse(BaseModel):
    """Dry-run: would_apply=false y plan=None. Apply: plan actualizado."""

    conflicts: list[PlanConflictOut]
    would_apply: bool
    version: int
    plan: PlanOut | None = None


class PlanZoneAssignee(BaseModel):
    zone_id: uuid.UUID
    assignee_id: uuid.UUID


class PlanPublishRequest(BaseModel):
    """Opcional. Zona ausente → assignee = plan.created_by si tiene membresía."""

    assignees: list[PlanZoneAssignee] = Field(default_factory=list)


class PlanPublishResponse(BaseModel):
    id: uuid.UUID
    status: str
    routes_created: int
    outbox_id: uuid.UUID


class DailyRouteOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    organization_id: uuid.UUID
    zone_id: uuid.UUID
    service_date: Date
    assignee_id: uuid.UUID
    status: str
    version: int
    current_revision: uuid.UUID | None = None


class PlanRoutesResponse(BaseModel):
    routes: list[DailyRouteOut]


class RouteAssigneeRequest(BaseModel):
    assignee_id: uuid.UUID
