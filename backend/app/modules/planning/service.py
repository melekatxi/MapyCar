"""Planes mensuales: borrador, generación, validación, movimiento y publicación.

Ref: RF-13/RF-14/RF-15, diseño §7.4 y §8.4.

Publicar (2.BE.13) responde 200, no 202: plan + daily_routes + outbox se
confirman en la misma transacción del request. Un 202 implicaría un worker
que puede fallar después de marcar published. Las rutas nacen en status
`draft` (current_revision nulo hasta que Fase 3 publique una revisión; no `ready`).

Assignee: cualquier membresía de la org (FK a user_memberships). El rol
previsto es `field`; planner/admin/supervisor también valen porque el
default de publicación es `plan.created_by`.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.modules.identity import service as identity_service
from app.modules.identity.models import Team, UserMembership
from app.modules.imports.models import Address, Patient
from app.modules.notifications.models import (
    EVENT_PLAN_PUBLISHED,
    EVENT_ROUTE_REASSIGNED,
    RESOURCE_DAILY_ROUTE,
    RESOURCE_MONTHLY_PLAN,
)
from app.modules.notifications.service import record_event, schedule_outbox
from app.modules.planning.assignment import (
    AssignmentConflict,
    ConflictCode,
    VisitAssignment,
    VisitRequest,
    assign_daily_visits,
    validate_daily_assignments,
)
from app.modules.planning.calendar import (
    ZONE_KIND_RURAL,
    ZONE_KIND_URBAN,
    MonthlyCalendar,
    WorkingDay,
    build_monthly_calendar,
    constraints_from_json,
)
from app.modules.planning.models import DailyRoute, MonthlyPlan
from app.modules.planning.schemas import (
    DailyRouteOut,
    MonthlyCalendarOut,
    PlanAssignmentOut,
    PlanConflictOut,
    PlanCreateResponse,
    PlanListItem,
    PlanMetricsOut,
    PlanMoveVisitResponse,
    PlanOut,
    PlanPublishResponse,
    PlanRoutesResponse,
    PlanValidateResponse,
    PlanZoneAssignee,
    WorkingDayOut,
)
from app.modules.zoning.models import Zone, ZoneAssignment

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CONFIRMED_GEOCODE_STATUSES = frozenset({"matched", "manual"})
FIRST_VERSION = 1
# Sin revisión (3.BE.1) la ruta no está lista para optimizar/ejecutar.
PUBLISHED_ROUTE_STATUS = "draft"


class PlanJobError(Exception):
    """Error de dominio en el worker: se persiste en result_json y no se reintenta."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def create_plan(
    db: Session,
    *,
    organization_id: uuid.UUID,
    team_id: uuid.UUID,
    period: str,
    constraints: dict[str, Any] | None,
    created_by: uuid.UUID,
) -> MonthlyPlan:
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if not PERIOD_RE.match(period):
        raise DomainError(422, "INVALID_PERIOD", "El periodo debe tener formato AAAA-MM")

    team = db.get(Team, team_id)
    if team is None or team.organization_id != organization_id:
        raise DomainError(404, "TEAM_NOT_FOUND", "Equipo no encontrado")

    try:
        parsed = constraints_from_json(constraints)
        build_monthly_calendar(period, parsed)
    except (TypeError, ValueError) as exc:
        raise DomainError(422, "INVALID_CONSTRAINTS", str(exc)) from exc

    clash = (
        db.query(MonthlyPlan)
        .filter(
            MonthlyPlan.organization_id == organization_id,
            MonthlyPlan.team_id == team_id,
            MonthlyPlan.period == period,
        )
        .one_or_none()
    )
    if clash is not None:
        raise DomainError(
            409, "PLAN_ALREADY_EXISTS", "Ya existe un plan para este equipo y periodo"
        )

    plan = MonthlyPlan(
        organization_id=organization_id,
        team_id=team_id,
        period=period,
        status="draft",
        version=FIRST_VERSION,
        constraints_json=parsed.to_json(),
        result_json={},
        conflicts_json=[],
        created_by=created_by,
    )
    db.add(plan)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        identity_service.set_current_organization_context(db, organization_id=organization_id)
        raise DomainError(
            409, "PLAN_ALREADY_EXISTS", "Ya existe un plan para este equipo y periodo"
        ) from exc
    db.refresh(plan)
    return plan


def list_plans(db: Session, *, organization_id: uuid.UUID) -> list[PlanListItem]:
    """Borradores y publicados de la organización. RLS exige el contexto de tenant."""
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    rows = (
        db.query(MonthlyPlan)
        .filter(
            MonthlyPlan.organization_id == organization_id,
            MonthlyPlan.status.in_(("draft", "published")),
        )
        .order_by(MonthlyPlan.period.desc(), MonthlyPlan.id)
        .all()
    )
    return [
        PlanListItem(id=plan.id, period=plan.period, status=plan.status, team_id=plan.team_id)
        for plan in rows
    ]


def attach_job(db: Session, plan: MonthlyPlan, *, job_id: str) -> MonthlyPlan:
    plan.job_id = job_id
    db.commit()
    db.refresh(plan)
    return plan


def generate_plan(db: Session, *, plan_id: uuid.UUID, organization_id: uuid.UUID) -> MonthlyPlan:
    """Worker de la cola `planning`: calendario + asignación, persistidos en el plan."""
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    plan = db.get(MonthlyPlan, plan_id)
    if plan is None or plan.organization_id != organization_id:
        raise PlanJobError("PLAN_NOT_FOUND", "Plan no encontrado")
    if plan.status == "published":
        return plan

    try:
        result_json, conflicts_json = _compute_plan_result(db, plan)
    except PlanJobError as exc:
        plan.result_json = {"error_code": exc.code}
        plan.conflicts_json = []
        db.commit()
        db.refresh(plan)
        return plan
    except (TypeError, ValueError) as exc:
        plan.result_json = {"error_code": "INVALID_CONSTRAINTS", "detail": str(exc)}
        plan.conflicts_json = []
        db.commit()
        db.refresh(plan)
        return plan

    plan.result_json = result_json
    plan.conflicts_json = conflicts_json
    db.commit()
    db.refresh(plan)
    return plan


def validate_plan(db: Session, plan: MonthlyPlan) -> PlanValidateResponse:
    if plan.status == "published":
        raise DomainError(409, "PLAN_PUBLISHED", "El plan ya está publicado")

    calendar = build_monthly_calendar(plan.period, plan.constraints_json)
    visits, _pre = _load_visit_requests(db, organization_id=plan.organization_id)
    stored = (plan.result_json or {}).get("assignments") or []
    assignments = tuple(_assignment_from_json(item) for item in stored)
    found = validate_daily_assignments(calendar, visits, assignments)
    return PlanValidateResponse(
        conflicts=[_conflict_to_out(item) for item in found],
        warnings=[],
    )


def move_visit(
    db: Session,
    plan: MonthlyPlan,
    *,
    patient_id: uuid.UUID,
    target_date: date,
    zone_id: uuid.UUID,
    expected_version: int,
    confirm: bool,
) -> PlanMoveVisitResponse:
    """Dry-run (confirm=false) no muta. Apply exige conflictos vacíos e If-Match."""
    identity_service.set_current_organization_context(db, organization_id=plan.organization_id)
    if plan.status == "published":
        raise DomainError(409, "PLAN_PUBLISHED", "El plan ya está publicado")
    if plan.status != "draft":
        raise DomainError(409, "PLAN_NOT_DRAFT", "Solo se puede mover visitas en un plan borrador")
    if plan.version != expected_version:
        raise DomainError(409, "PLAN_VERSION_CONFLICT", "El plan ha sido modificado")

    zone = db.get(Zone, zone_id)
    if zone is None or zone.organization_id != plan.organization_id:
        raise DomainError(404, "ZONE_NOT_FOUND", "Zona no encontrada")

    patient_key = str(patient_id)
    stored = list((plan.result_json or {}).get("assignments") or [])
    proposed: list[VisitAssignment] = []
    found = False
    for item in stored:
        current = _assignment_from_json(item)
        if current.patient_id == patient_key:
            found = True
            proposed.append(
                VisitAssignment(patient_id=patient_key, date=target_date, zone_id=str(zone_id))
            )
        else:
            proposed.append(current)
    if not found:
        raise DomainError(404, "PATIENT_NOT_IN_PLAN", "La visita no está en este plan")

    calendar = build_monthly_calendar(plan.period, plan.constraints_json)
    visits = _visit_requests_for_move(db, plan=plan, patient_id=patient_key, zone=zone)
    parsed = constraints_from_json(plan.constraints_json)
    found_conflicts = validate_daily_assignments(
        calendar,
        visits,
        proposed,
        default_service_minutes=parsed.service_minutes,
    )
    conflicts_out = [_conflict_to_out(item) for item in found_conflicts]
    if not confirm:
        return PlanMoveVisitResponse(
            conflicts=conflicts_out,
            would_apply=False,
            version=plan.version,
        )
    if found_conflicts:
        codes = ", ".join(sorted({str(item.code) for item in found_conflicts}))
        raise DomainError(409, "PLAN_MOVE_CONFLICT", f"El movimiento tiene conflictos: {codes}")

    proposed.sort(key=lambda item: (item.date, item.zone_id, item.patient_id))
    result_json = dict(plan.result_json or {})
    assignments_json = [_assignment_to_json(item) for item in proposed]
    metrics = dict(result_json.get("metrics") or {})
    metrics["n_assigned"] = len(assignments_json)
    result_json["assignments"] = assignments_json
    result_json["metrics"] = metrics
    plan.result_json = result_json
    plan.version = expected_version + 1
    db.commit()
    db.refresh(plan)
    return PlanMoveVisitResponse(
        conflicts=[],
        would_apply=True,
        version=plan.version,
        plan=to_plan_out(plan),
    )


def publish_plan(
    db: Session,
    plan: MonthlyPlan,
    *,
    expected_version: int,
    assignees: list[PlanZoneAssignee] | None,
) -> PlanPublishResponse:
    """Publica el borrador: daily_routes draft + outbox `plan.published` + status.

    Una sola transacción. 200 (no 202): no hay worker posterior al commit.
    """
    identity_service.set_current_organization_context(db, organization_id=plan.organization_id)
    locked = db.query(MonthlyPlan).filter(MonthlyPlan.id == plan.id).with_for_update().one_or_none()
    if locked is None or locked.organization_id != plan.organization_id:
        raise DomainError(404, "PLAN_NOT_FOUND", "Plan no encontrado")
    if locked.status == "published":
        raise DomainError(409, "PLAN_PUBLISHED", "El plan ya está publicado")
    if locked.status != "draft":
        raise DomainError(409, "PLAN_NOT_DRAFT", "Solo se puede publicar un plan borrador")
    if locked.version != expected_version:
        raise DomainError(409, "PLAN_VERSION_CONFLICT", "El plan ha sido modificado")

    groups = _assignment_groups(locked)
    if not groups:
        raise DomainError(409, "PLAN_NO_ASSIGNMENTS", "El plan no tiene asignaciones para publicar")

    zone_assignees = _resolve_zone_assignees(
        db,
        plan=locked,
        groups=groups,
        assignees=assignees or [],
    )
    routes = [
        DailyRoute(
            organization_id=locked.organization_id,
            plan_id=locked.id,
            zone_id=zone_id,
            service_date=service_date,
            assignee_id=zone_assignees[zone_id],
            status=PUBLISHED_ROUTE_STATUS,
            current_revision=None,
            version=FIRST_VERSION,
        )
        for service_date, zone_id in groups
    ]
    payload = {
        "plan_id": str(locked.id),
        "period": locked.period,
        "team_id": str(locked.team_id),
        "plan_version": locked.version,
        "routes_created": len(routes),
        "assignee_ids": sorted({str(route.assignee_id) for route in routes}),
        "service_dates": sorted({route.service_date.isoformat() for route in routes}),
        "zone_ids": sorted({str(route.zone_id) for route in routes}),
    }
    try:
        db.add_all(routes)
        event = record_event(
            db,
            organization_id=locked.organization_id,
            event_type=EVENT_PLAN_PUBLISHED,
            resource_type=RESOURCE_MONTHLY_PLAN,
            resource_id=locked.id,
            payload=payload,
        )
        locked.status = "published"
        locked.published_at = datetime.now(UTC)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        identity_service.set_current_organization_context(db, organization_id=plan.organization_id)
        raise DomainError(409, "PLAN_PUBLISH_CONFLICT", "No se pudo publicar el plan") from exc
    schedule_outbox(event)
    db.refresh(locked)
    return PlanPublishResponse(
        id=locked.id,
        status=locked.status,
        routes_created=len(routes),
        outbox_id=event.id,
    )


def list_plan_routes(db: Session, plan: MonthlyPlan) -> PlanRoutesResponse:
    identity_service.set_current_organization_context(db, organization_id=plan.organization_id)
    routes = (
        db.query(DailyRoute)
        .filter(
            DailyRoute.plan_id == plan.id,
            DailyRoute.organization_id == plan.organization_id,
        )
        .order_by(DailyRoute.service_date, DailyRoute.zone_id, DailyRoute.assignee_id)
        .all()
    )
    return PlanRoutesResponse(routes=[_route_to_out(route) for route in routes])


def assign_route(
    db: Session,
    plan: MonthlyPlan,
    *,
    route_id: uuid.UUID,
    assignee_id: uuid.UUID,
    expected_version: int,
) -> DailyRouteOut:
    """Reasigna el visitador de una ruta de un plan publicado. If-Match = route.version.

    El destino debe tener membresía en la misma org (cualquier rol). Usuario de
    otra org o inexistente → 404 ASSIGNEE_NOT_FOUND (no filtramos 403 para no
    filtrar existencia). Choque UNIQUE (plan, fecha, zona, assignee) → 409.
    """
    identity_service.set_current_organization_context(db, organization_id=plan.organization_id)
    if plan.status != "published":
        raise DomainError(409, "PLAN_NOT_PUBLISHED", "Solo se asigna en un plan publicado")

    route = (
        db.query(DailyRoute)
        .filter(
            DailyRoute.id == route_id,
            DailyRoute.plan_id == plan.id,
            DailyRoute.organization_id == plan.organization_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if route is None:
        raise DomainError(404, "ROUTE_NOT_FOUND", "Ruta no encontrada")
    if route.version != expected_version:
        raise DomainError(409, "ROUTE_VERSION_CONFLICT", "La ruta ha sido modificada")
    if route.assignee_id == assignee_id:
        return _route_to_out(route)

    if _org_membership(db, user_id=assignee_id, organization_id=plan.organization_id) is None:
        raise DomainError(404, "ASSIGNEE_NOT_FOUND", "Visitador no encontrado")

    previous_assignee_id = route.assignee_id
    route.assignee_id = assignee_id
    route.version = expected_version + 1
    try:
        event = record_event(
            db,
            organization_id=plan.organization_id,
            event_type=EVENT_ROUTE_REASSIGNED,
            resource_type=RESOURCE_DAILY_ROUTE,
            resource_id=route.id,
            payload={
                "route_id": str(route.id),
                "previous_assignee_id": str(previous_assignee_id),
                "assignee_id": str(assignee_id),
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        identity_service.set_current_organization_context(db, organization_id=plan.organization_id)
        if _is_unique_violation(exc, "uq_daily_routes_plan_date_zone_assignee"):
            raise DomainError(
                409,
                "ROUTE_ASSIGNEE_CONFLICT",
                "Ese visitador ya tiene una ruta en esa zona y fecha",
            ) from exc
        raise DomainError(409, "ROUTE_ASSIGNEE_INVALID", "No se pudo asignar el visitador") from exc
    schedule_outbox(event)
    db.refresh(route)
    return _route_to_out(route)


def _visit_requests_for_move(
    db: Session, *, plan: MonthlyPlan, patient_id: str, zone: Zone
) -> list[VisitRequest]:
    visits, _pre = _load_visit_requests(db, organization_id=plan.organization_id)
    adjusted: list[VisitRequest] = []
    seen = False
    for visit in visits:
        if visit.patient_id == patient_id:
            seen = True
            adjusted.append(
                VisitRequest(
                    patient_id=visit.patient_id,
                    zone_id=str(zone.id),
                    kind=_visit_kind(zone.kind),
                    geocode_confirmed=visit.geocode_confirmed,
                    service_minutes=visit.service_minutes,
                    window_start=visit.window_start,
                    window_end=visit.window_end,
                )
            )
        else:
            adjusted.append(visit)
    if not seen:
        adjusted.append(
            VisitRequest(
                patient_id=patient_id,
                zone_id=str(zone.id),
                kind=_visit_kind(zone.kind),
                geocode_confirmed=True,
            )
        )
    return adjusted


def to_create_response(plan: MonthlyPlan) -> PlanCreateResponse:
    return PlanCreateResponse(
        id=plan.id,
        organization_id=plan.organization_id,
        team_id=plan.team_id,
        period=plan.period,
        status=plan.status,
        version=plan.version,
        constraints=plan.constraints_json or {},
        created_by=plan.created_by,
    )


def to_plan_out(plan: MonthlyPlan) -> PlanOut:
    calendar = build_monthly_calendar(plan.period, plan.constraints_json)
    result = plan.result_json or {}
    stored_assignments = result.get("assignments") or []
    stored_conflicts = plan.conflicts_json or []
    if not stored_conflicts and result.get("conflicts"):
        stored_conflicts = result["conflicts"]
    assignments = [_assignment_to_out(item) for item in stored_assignments]
    conflicts = [_conflict_dict_to_out(item) for item in stored_conflicts]
    return PlanOut(
        id=plan.id,
        organization_id=plan.organization_id,
        team_id=plan.team_id,
        period=plan.period,
        status=plan.status,
        version=plan.version,
        constraints=plan.constraints_json or {},
        calendar=_calendar_to_out(calendar),
        assignments=assignments,
        conflicts=conflicts,
        metrics=PlanMetricsOut(n_assigned=len(assignments), n_conflicts=len(conflicts)),
        job_id=plan.job_id,
        created_by=plan.created_by,
    )


def _compute_plan_result(db: Session, plan: MonthlyPlan) -> tuple[dict, list[dict]]:
    calendar = build_monthly_calendar(plan.period, plan.constraints_json)
    visits, pre_conflicts = _load_visit_requests(db, organization_id=plan.organization_id)
    result = assign_daily_visits(calendar, visits)
    conflicts = [*pre_conflicts, *result.conflicts]
    assignments_json = [_assignment_to_json(item) for item in result.assignments]
    conflicts_json = [_conflict_to_json(item) for item in conflicts]
    return (
        {
            "calendar": _calendar_to_json(calendar),
            "assignments": assignments_json,
            "metrics": {
                "n_assigned": len(assignments_json),
                "n_conflicts": len(conflicts_json),
            },
        },
        conflicts_json,
    )


def _load_visit_requests(
    db: Session, *, organization_id: uuid.UUID
) -> tuple[list[VisitRequest], list[AssignmentConflict]]:
    """Pacientes activos + zona actual. Sin zona → UNSCHEDULABLE; sin geocode → ADDRESS_NOT_CONFIRMED."""
    rows = (
        db.query(Patient, Address, ZoneAssignment, Zone)
        .outerjoin(
            Address,
            (Address.patient_id == Patient.id)
            & (Address.organization_id == Patient.organization_id)
            & Address.is_active.is_(True),
        )
        .outerjoin(
            ZoneAssignment,
            (ZoneAssignment.patient_id == Patient.id)
            & (ZoneAssignment.organization_id == Patient.organization_id)
            & ZoneAssignment.valid_to.is_(None),
        )
        .outerjoin(
            Zone,
            (Zone.id == ZoneAssignment.zone_id) & (Zone.organization_id == Patient.organization_id),
        )
        .filter(Patient.organization_id == organization_id, Patient.status == "active")
        .all()
    )

    visits: list[VisitRequest] = []
    pre_conflicts: list[AssignmentConflict] = []
    for patient, address, _assignment, zone in rows:
        confirmed = address is not None and address.geocode_status in CONFIRMED_GEOCODE_STATUSES
        if not confirmed:
            pre_conflicts.append(
                AssignmentConflict(
                    code=ConflictCode.ADDRESS_NOT_CONFIRMED,
                    patient_id=str(patient.id),
                    zone_id=str(zone.id) if zone is not None else None,
                    detail="dirección sin geocodificación confirmada",
                )
            )
            continue
        if zone is None:
            pre_conflicts.append(
                AssignmentConflict(
                    code=ConflictCode.UNSCHEDULABLE,
                    patient_id=str(patient.id),
                    detail="paciente sin zona actual",
                )
            )
            continue
        visits.append(
            VisitRequest(
                patient_id=str(patient.id),
                zone_id=str(zone.id),
                kind=_visit_kind(zone.kind),
                geocode_confirmed=True,
            )
        )
    return visits, pre_conflicts


def _visit_kind(zone_kind: str) -> str:
    if zone_kind == ZONE_KIND_RURAL:
        return ZONE_KIND_RURAL
    return ZONE_KIND_URBAN


def _calendar_to_json(calendar: MonthlyCalendar) -> dict:
    return {
        "period": calendar.period,
        "timezone": calendar.timezone,
        "working_days": [_working_day_to_json(day) for day in calendar.working_days],
        "skipped_holidays": [day.isoformat() for day in calendar.skipped_holidays],
    }


def _working_day_to_json(day: WorkingDay) -> dict:
    return {
        "date": day.date.isoformat(),
        "capacity_visits": day.capacity_visits,
        "capacity_minutes": day.capacity_minutes,
        "zone_kind": day.zone_kind,
        "window_start": _clock_to_json(day.window_start),
        "window_end": _clock_to_json(day.window_end),
    }


def _clock_to_json(value: time | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M")


def _calendar_to_out(calendar: MonthlyCalendar) -> MonthlyCalendarOut:
    return MonthlyCalendarOut(
        period=calendar.period,
        timezone=calendar.timezone,
        working_days=[
            WorkingDayOut(
                date=day.date,
                capacity_visits=day.capacity_visits,
                capacity_minutes=day.capacity_minutes,
                zone_kind=day.zone_kind,
                window_start=_clock_to_json(day.window_start),
                window_end=_clock_to_json(day.window_end),
            )
            for day in calendar.working_days
        ],
        skipped_holidays=list(calendar.skipped_holidays),
    )


def _assignment_to_json(item: VisitAssignment) -> dict:
    return {
        "patient_id": item.patient_id,
        "date": item.date.isoformat(),
        "zone_id": item.zone_id,
    }


def _assignment_from_json(raw: dict) -> VisitAssignment:
    return VisitAssignment(
        patient_id=str(raw["patient_id"]),
        date=date.fromisoformat(raw["date"]),
        zone_id=str(raw["zone_id"]),
    )


def _assignment_to_out(raw: dict) -> PlanAssignmentOut:
    return PlanAssignmentOut(
        patient_id=uuid.UUID(str(raw["patient_id"])),
        date=date.fromisoformat(raw["date"]),
        zone_id=uuid.UUID(str(raw["zone_id"])),
    )


def _conflict_to_json(item: AssignmentConflict) -> dict:
    return {
        "code": str(item.code),
        "patient_id": item.patient_id,
        "date": item.date.isoformat() if item.date is not None else None,
        "zone_id": item.zone_id,
        "detail": item.detail,
    }


def _conflict_to_out(item: AssignmentConflict) -> PlanConflictOut:
    return _conflict_dict_to_out(_conflict_to_json(item))


def _conflict_dict_to_out(raw: dict) -> PlanConflictOut:
    zone_raw = raw.get("zone_id")
    date_raw = raw.get("date")
    return PlanConflictOut(
        code=str(raw["code"]),
        patient_id=uuid.UUID(str(raw["patient_id"])),
        date=date.fromisoformat(date_raw) if date_raw else None,
        zone_id=uuid.UUID(str(zone_raw)) if zone_raw else None,
        detail=str(raw.get("detail") or ""),
    )


def _is_unique_violation(exc: IntegrityError, constraint: str) -> bool:
    orig = exc.orig
    name = getattr(getattr(orig, "diag", None), "constraint_name", None)
    if name == constraint:
        return True
    return constraint in str(orig or exc)


def _assignment_groups(plan: MonthlyPlan) -> list[tuple[date, uuid.UUID]]:
    stored = (plan.result_json or {}).get("assignments") or []
    groups: dict[tuple[date, uuid.UUID], None] = {}
    for item in stored:
        key = (date.fromisoformat(str(item["date"])), uuid.UUID(str(item["zone_id"])))
        groups[key] = None
    return sorted(groups, key=lambda item: (item[0], item[1]))


def _org_membership(
    db: Session, *, user_id: uuid.UUID, organization_id: uuid.UUID
) -> UserMembership | None:
    return (
        db.query(UserMembership)
        .filter(
            UserMembership.user_id == user_id,
            UserMembership.organization_id == organization_id,
        )
        .one_or_none()
    )


def _resolve_zone_assignees(
    db: Session,
    *,
    plan: MonthlyPlan,
    groups: list[tuple[date, uuid.UUID]],
    assignees: list[PlanZoneAssignee],
) -> dict[uuid.UUID, uuid.UUID]:
    zone_ids = {zone_id for _service_date, zone_id in groups}
    mapping: dict[uuid.UUID, uuid.UUID] = {}
    seen: set[uuid.UUID] = set()
    for item in assignees:
        if item.zone_id in seen:
            raise DomainError(422, "DUPLICATE_ZONE_ASSIGNEE", "Zona duplicada en assignees")
        seen.add(item.zone_id)
        if item.zone_id not in zone_ids:
            raise DomainError(422, "UNKNOWN_ZONE", "La zona no está en las asignaciones del plan")
        if (
            _org_membership(db, user_id=item.assignee_id, organization_id=plan.organization_id)
            is None
        ):
            raise DomainError(404, "ASSIGNEE_NOT_FOUND", "Visitador no encontrado")
        mapping[item.zone_id] = item.assignee_id

    default_id: uuid.UUID | None = None
    missing = [zone_id for zone_id in zone_ids if zone_id not in mapping]
    if missing:
        if (
            _org_membership(db, user_id=plan.created_by, organization_id=plan.organization_id)
            is None
        ):
            raise DomainError(422, "ASSIGNEE_REQUIRED", "Falta visitador para una zona del plan")
        default_id = plan.created_by

    resolved: dict[uuid.UUID, uuid.UUID] = {}
    for zone_id in zone_ids:
        if zone_id in mapping:
            resolved[zone_id] = mapping[zone_id]
        else:
            assert default_id is not None
            resolved[zone_id] = default_id
    return resolved


def _route_to_out(route: DailyRoute) -> DailyRouteOut:
    return DailyRouteOut(
        id=route.id,
        plan_id=route.plan_id,
        organization_id=route.organization_id,
        zone_id=route.zone_id,
        service_date=route.service_date,
        assignee_id=route.assignee_id,
        status=route.status,
        version=route.version,
        current_revision=route.current_revision,
    )
