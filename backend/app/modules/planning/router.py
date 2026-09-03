"""Endpoints de planes mensuales. Ref: diseño sección 8.4, RF-13, RF-14, RF-15."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Response
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.modules.identity import service as identity_service
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.planning import service
from app.modules.planning.deps import (
    get_plan_for_creator,
    get_plan_for_member,
    require_if_match,
    require_plan_creator,
)
from app.modules.planning.models import MonthlyPlan
from app.modules.planning.schemas import (
    DailyRouteOut,
    PlanCreateRequest,
    PlanCreateResponse,
    PlanGenerateResponse,
    PlanMoveVisitRequest,
    PlanMoveVisitResponse,
    PlanOut,
    PlanPublishRequest,
    PlanPublishResponse,
    PlanRoutesResponse,
    PlansPage,
    PlanValidateResponse,
    RouteAssigneeRequest,
)

router = APIRouter(prefix="/plans", tags=["planning"])


def _etag(version: int) -> str:
    return f'"{version}"'


@router.post("", status_code=201, response_model=PlanCreateResponse)
def create_plan(
    payload: PlanCreateRequest,
    current_user: User = Depends(require_plan_creator),
    db: Session = Depends(get_db),
) -> PlanCreateResponse:
    plan = service.create_plan(
        db,
        organization_id=payload.organization_id,
        team_id=payload.team_id,
        period=payload.period,
        constraints=payload.constraints,
        created_by=current_user.id,
    )
    return service.to_create_response(plan)


@router.get("", response_model=PlansPage)
def list_plans(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlansPage:
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if not identity_service.is_member_of_organization(
        db, user_id=current_user.id, organization_id=organization_id
    ):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    return PlansPage(plans=service.list_plans(db, organization_id=organization_id))


@router.post("/{plan_id}/generate", status_code=202, response_model=PlanGenerateResponse)
def generate_plan(
    plan: MonthlyPlan = Depends(get_plan_for_creator),
    db: Session = Depends(get_db),
    queue: JobQueue = Depends(get_job_queue),
) -> PlanGenerateResponse:
    if plan.status == "published":
        raise DomainError(409, "PLAN_PUBLISHED", "El plan ya está publicado")
    job = queue.enqueue(
        queue="planning",
        payload={"plan_id": str(plan.id), "organization_id": str(plan.organization_id)},
    )
    plan = service.attach_job(db, plan, job_id=job.id)
    return PlanGenerateResponse(id=plan.id, job_id=job.id, status=plan.status)


@router.get("/{plan_id}", response_model=PlanOut)
def get_plan(response: Response, plan: MonthlyPlan = Depends(get_plan_for_member)) -> PlanOut:
    response.headers["ETag"] = _etag(plan.version)
    return service.to_plan_out(plan)


@router.post("/{plan_id}/validate", response_model=PlanValidateResponse)
def validate_plan(
    plan: MonthlyPlan = Depends(get_plan_for_creator),
    db: Session = Depends(get_db),
) -> PlanValidateResponse:
    return service.validate_plan(db, plan)


@router.patch("/{plan_id}/visits/{patient_id}", response_model=PlanMoveVisitResponse)
def move_plan_visit(
    patient_id: uuid.UUID,
    payload: PlanMoveVisitRequest,
    response: Response,
    plan: MonthlyPlan = Depends(get_plan_for_creator),
    expected_version: int = Depends(require_if_match),
    db: Session = Depends(get_db),
) -> PlanMoveVisitResponse:
    moved = service.move_visit(
        db,
        plan,
        patient_id=patient_id,
        target_date=payload.date,
        zone_id=payload.zone_id,
        expected_version=expected_version,
        confirm=payload.confirm,
    )
    response.headers["ETag"] = _etag(moved.version)
    return moved


@router.post("/{plan_id}/publish", status_code=200, response_model=PlanPublishResponse)
def publish_plan(
    response: Response,
    payload: PlanPublishRequest = Body(default_factory=PlanPublishRequest),
    plan: MonthlyPlan = Depends(get_plan_for_creator),
    expected_version: int = Depends(require_if_match),
    db: Session = Depends(get_db),
) -> PlanPublishResponse:
    published = service.publish_plan(
        db,
        plan,
        expected_version=expected_version,
        assignees=payload.assignees,
    )
    response.headers["ETag"] = _etag(plan.version)
    return published


@router.get("/{plan_id}/routes", response_model=PlanRoutesResponse)
def list_plan_routes(
    plan: MonthlyPlan = Depends(get_plan_for_creator),
    db: Session = Depends(get_db),
) -> PlanRoutesResponse:
    return service.list_plan_routes(db, plan)


@router.put("/{plan_id}/routes/{route_id}/assignee", response_model=DailyRouteOut)
def assign_plan_route(
    route_id: uuid.UUID,
    payload: RouteAssigneeRequest,
    response: Response,
    plan: MonthlyPlan = Depends(get_plan_for_creator),
    expected_version: int = Depends(require_if_match),
    db: Session = Depends(get_db),
) -> DailyRouteOut:
    route = service.assign_route(
        db,
        plan,
        route_id=route_id,
        assignee_id=payload.assignee_id,
        expected_version=expected_version,
    )
    response.headers["ETag"] = _etag(route.version)
    return route
