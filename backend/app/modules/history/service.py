"""Consulta de histórico sobre revisiones publicadas (no el paciente actual).

Ref: 4.BE.1, RF-23, RF-24, diseño 7.6 / 8.5.
"""

from __future__ import annotations

import base64
import uuid
from datetime import date, datetime

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.modules.history.schemas import HistoryRouteOut, HistoryRoutesPage, HistoryStopOut
from app.modules.identity import service as identity_service
from app.modules.identity.models import User, UserMembership
from app.modules.planning.models import DailyRoute
from app.modules.routing.models import RouteRevision

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_FIELD_ROLE = "field"


def list_route_history(
    db: Session,
    *,
    organization_id: uuid.UUID,
    current_user: User,
    date_from: date | None,
    date_to: date | None,
    zone_id: uuid.UUID | None,
    assignee_id: uuid.UUID | None,
    patient_ref: str | None,
    cursor: str | None,
    limit: int,
) -> HistoryRoutesPage:
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if date_from is not None and date_to is not None and date_from > date_to:
        raise DomainError(422, "DATE_RANGE_INVALID", "from no puede ser posterior a to")
    page_size = min(max(limit, 1), _MAX_LIMIT)
    assignee_id = _scoped_assignee(db, current_user, organization_id, assignee_id)

    query = (
        db.query(RouteRevision, DailyRoute)
        .join(DailyRoute, DailyRoute.id == RouteRevision.route_id)
        .filter(
            RouteRevision.organization_id == organization_id,
            RouteRevision.status == "published",
        )
    )
    if date_from is not None:
        query = query.filter(DailyRoute.service_date >= date_from)
    if date_to is not None:
        query = query.filter(DailyRoute.service_date <= date_to)
    if zone_id is not None:
        query = query.filter(DailyRoute.zone_id == zone_id)
    if assignee_id is not None:
        query = query.filter(DailyRoute.assignee_id == assignee_id)
    if patient_ref:
        query = query.filter(
            RouteRevision.constraints_json.contains(
                {"snapshot": {"order": [{"external_ref": patient_ref}]}}
            )
        )
    if cursor:
        published_at, revision_id = _decode_cursor(cursor)
        query = query.filter(
            tuple_(RouteRevision.published_at, RouteRevision.id) < (published_at, revision_id)
        )

    rows = (
        query.order_by(RouteRevision.published_at.desc(), RouteRevision.id.desc())
        .limit(page_size + 1)
        .all()
    )
    page = rows[:page_size]
    next_cursor = None
    if len(rows) > page_size:
        last_revision, _route = page[-1]
        next_cursor = _encode_cursor(last_revision.published_at, last_revision.id)

    items = [_to_out(revision, route) for revision, route in page]
    return HistoryRoutesPage(items=items, next_cursor=next_cursor)


def _scoped_assignee(
    db: Session,
    current_user: User,
    organization_id: uuid.UUID,
    assignee_id: uuid.UUID | None,
) -> uuid.UUID | None:
    membership = (
        db.query(UserMembership)
        .filter(
            UserMembership.user_id == current_user.id,
            UserMembership.organization_id == organization_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    if membership.role != _FIELD_ROLE:
        return assignee_id
    if assignee_id is not None and assignee_id != current_user.id:
        raise DomainError(403, "FORBIDDEN_ROLE", "El rol de campo solo ve sus propias rutas")
    return current_user.id


def _encode_cursor(published_at: datetime, revision_id: uuid.UUID) -> str:
    raw = f"{published_at.isoformat()}|{revision_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        stamp, ident = raw.split("|", 1)
        return datetime.fromisoformat(stamp), uuid.UUID(ident)
    except (ValueError, OSError) as exc:
        raise DomainError(422, "CURSOR_INVALID", "Cursor de paginación no válido") from exc


def _to_out(revision: RouteRevision, route: DailyRoute) -> HistoryRouteOut:
    snapshot = (revision.constraints_json or {}).get("snapshot") or {}
    stops: list[HistoryStopOut] = []
    for item in snapshot.get("order") or []:
        try:
            patient_id = uuid.UUID(str(item["patient_id"]))
        except (KeyError, ValueError, TypeError):
            continue
        stops.append(
            HistoryStopOut(
                sequence=int(item.get("sequence") or 0),
                patient_id=patient_id,
                external_ref=item.get("external_ref") or None,
                lat=item.get("lat"),
                lon=item.get("lon"),
            )
        )
    if revision.published_at is None:
        raise DomainError(409, "REVISION_NOT_PUBLISHED", "La revisión no tiene fecha de publicación")
    return HistoryRouteOut(
        route_id=route.id,
        revision_id=revision.id,
        revision=revision.revision,
        published_at=revision.published_at,
        service_date=route.service_date,
        zone_id=route.zone_id,
        assignee_id=route.assignee_id,
        objective=snapshot.get("objective") or revision.objective,
        stops=stops,
    )
