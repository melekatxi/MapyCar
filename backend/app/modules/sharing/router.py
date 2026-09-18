"""POST/GET shares interno y externo + canje público. Ref: 4.BE.6, 4.BE.7, diseño 8.6."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.session import get_db
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.planning.models import DailyRoute
from app.modules.routing.deps import get_route_for_editor
from app.modules.sharing import service
from app.modules.sharing.schemas import (
    CreateShareRequest,
    PublicShareExchangeRequest,
    PublicShareViewOut,
    ShareGrantListOut,
    ShareGrantOut,
)
from app.modules.sharing.tokens import COOKIE_NAME, sign_public_share_session

router = APIRouter(tags=["sharing"])


@router.post("/routes/{route_id}/shares", status_code=201, response_model=ShareGrantOut)
def create_route_share(
    payload: CreateShareRequest,
    route: DailyRoute = Depends(get_route_for_editor),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ShareGrantOut:
    if not idempotency_key:
        raise DomainError(400, "IDEMPOTENCY_KEY_REQUIRED", "Falta la cabecera Idempotency-Key")
    return service.create_share(
        db,
        route,
        payload,
        created_by=current_user.id,
        idempotency_key=idempotency_key,
    )


@router.get("/routes/{route_id}/shares", response_model=ShareGrantListOut)
def list_route_shares(
    route: DailyRoute = Depends(get_route_for_editor),
    db: Session = Depends(get_db),
) -> ShareGrantListOut:
    return service.list_shares(db, route)


@router.delete("/shares/{share_id}", status_code=204)
def revoke_route_share(
    share_id: uuid.UUID,
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    service.revoke_share(
        db,
        share_id=share_id,
        organization_id=organization_id,
        actor_id=current_user.id,
    )
    return Response(status_code=204)


@router.post("/public-shares/exchange", response_model=PublicShareViewOut)
def exchange_public_share(
    payload: PublicShareExchangeRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> PublicShareViewOut:
    view, ttl, grant = service.exchange_public_token(db, token=payload.token)
    response.headers["Referrer-Policy"] = "no-referrer"
    response.set_cookie(
        COOKIE_NAME,
        sign_public_share_session(
            grant_id=str(grant.id),
            organization_id=str(grant.organization_id),
            ttl=ttl,
        ),
        httponly=True,
        samesite="strict",
        max_age=ttl,
    )
    return view
