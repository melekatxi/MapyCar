"""Dependencias FastAPI del módulo de rutas: organización, rol planner/admin e If-Match."""

from __future__ import annotations

import uuid
from functools import lru_cache

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.adapters.optimizer.interface import Optimizer
from app.adapters.optimizer.ortools_tsp import OrToolsTspOptimizer
from app.core.errors import DomainError
from app.db.session import get_db
from app.modules.identity import service as identity_service
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User, UserMembership
from app.modules.planning.models import DailyRoute

# Misma política que plan creators (planning.deps.PLAN_CREATOR_ROLES).
ROUTE_EDITOR_ROLES = ("admin", "planner")


@lru_cache
def get_optimizer() -> Optimizer:
    return OrToolsTspOptimizer()


def _membership(db: Session, *, user_id: uuid.UUID, organization_id: uuid.UUID) -> UserMembership:
    membership = (
        db.query(UserMembership)
        .filter(
            UserMembership.user_id == user_id,
            UserMembership.organization_id == organization_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    return membership


def get_route_for_member(
    route_id: uuid.UUID,
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DailyRoute:
    # organization_id explícito: RLS necesita app.current_organization_id ANTES de leer la fila.
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if not identity_service.is_member_of_organization(
        db, user_id=current_user.id, organization_id=organization_id
    ):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    route = db.get(DailyRoute, route_id)
    if route is None or route.organization_id != organization_id:
        raise DomainError(404, "ROUTE_NOT_FOUND", "Ruta no encontrada")
    return route


def get_route_for_editor(
    route: DailyRoute = Depends(get_route_for_member),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DailyRoute:
    membership = _membership(db, user_id=current_user.id, organization_id=route.organization_id)
    if membership.role not in ROUTE_EDITOR_ROLES:
        raise DomainError(403, "FORBIDDEN_ROLE", "Rol sin permiso para planificar")
    return route


def parse_if_match(if_match: str | None) -> int:
    """ETag de ruta: entero o comillas RFC (`1`, `"1"`). Token = daily_routes.version."""
    if if_match is None or not if_match.strip():
        raise DomainError(422, "IF_MATCH_REQUIRED", "Falta la cabecera If-Match")
    raw = if_match.strip()
    if raw[:2].lower() == "w/":
        raw = raw[2:].strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    raw = raw.strip()
    if not raw.isdigit():
        raise DomainError(422, "IF_MATCH_INVALID", "If-Match debe ser la versión entera")
    return int(raw)


def require_if_match(if_match: str | None = Header(default=None, alias="If-Match")) -> int:
    return parse_if_match(if_match)
