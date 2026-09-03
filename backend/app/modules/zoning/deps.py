"""Dependencias FastAPI del módulo de zonificación: autorización por organización."""

from __future__ import annotations

import uuid
from functools import lru_cache

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.adapters.router.interface import Router
from app.adapters.router.osrm import OsrmRouter
from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import get_db
from app.modules.identity import service as identity_service
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.zoning.models import Zone, ZoneProposal


@lru_cache
def get_router() -> Router:
    return OsrmRouter(get_settings().osrm_base_url)


def get_proposal_for_member(
    proposal_id: uuid.UUID,
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ZoneProposal:
    # organization_id explícito: RLS necesita app.current_organization_id ANTES de leer la fila.
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if not identity_service.is_member_of_organization(
        db, user_id=current_user.id, organization_id=organization_id
    ):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    proposal = db.get(ZoneProposal, proposal_id)
    if proposal is None or proposal.organization_id != organization_id:
        raise DomainError(404, "ZONE_PROPOSAL_NOT_FOUND", "Propuesta no encontrada")
    return proposal


def get_zone_for_member(
    zone_id: uuid.UUID,
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Zone:
    # organization_id explícito: RLS necesita app.current_organization_id ANTES de leer la fila.
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if not identity_service.is_member_of_organization(
        db, user_id=current_user.id, organization_id=organization_id
    ):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    zone = db.get(Zone, zone_id)
    if zone is None or zone.organization_id != organization_id:
        raise DomainError(404, "ZONE_NOT_FOUND", "Zona no encontrada")
    return zone


def parse_if_match(if_match: str | None) -> int:
    """ETag de zona: entero o comillas RFC (`1`, `"1"`). No hay If-Match previo en el API."""
    if if_match is None or not if_match.strip():
        raise DomainError(422, "IF_MATCH_REQUIRED", "Falta la cabecera If-Match")
    raw = if_match.strip()
    if raw[:2].lower() == "w/":
        raw = raw[2:].strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    raw = raw.strip()
    if not raw.isdigit():
        raise DomainError(422, "IF_MATCH_INVALID", "If-Match debe ser la versión entera de la zona")
    return int(raw)


def require_if_match(if_match: str | None = Header(default=None, alias="If-Match")) -> int:
    return parse_if_match(if_match)
