from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.core.security import sign_session_token
from app.db.session import get_db
from app.modules.identity import service
from app.modules.identity.deps import get_current_user, require_organization_member
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    LoginRequest,
    LoginResponse,
    MembershipOut,
    MeResponse,
    TeamOut,
    TeamsPage,
)

router = APIRouter(tags=["identity"])


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = service.authenticate(db, email=payload.email, password=payload.password)
    if user is None:
        raise DomainError(401, "INVALID_CREDENTIALS", "Email o contraseña incorrectos")
    return LoginResponse(access_token=sign_session_token(user_id=str(user.id)))


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    memberships = service.get_memberships(db, user_id=current_user.id)
    return MeResponse(
        id=current_user.id,
        email=current_user.email_normalized,
        display_name=current_user.display_name,
        memberships=[MembershipOut(organization_id=m.organization_id, role=m.role) for m in memberships],
    )


@router.get("/organizations/{organization_id}/ping")
def ping_organization(
    organization_id: uuid.UUID, current_user: User = Depends(require_organization_member)
) -> dict[str, str]:
    return {"status": "ok", "organization_id": str(organization_id)}


@router.get("/teams", response_model=TeamsPage)
def list_teams(
    organization_id: uuid.UUID,
    current_user: User = Depends(require_organization_member),
    db: Session = Depends(get_db),
) -> TeamsPage:
    teams = service.list_teams(db, organization_id=organization_id)
    return TeamsPage(
        teams=[
            TeamOut(
                id=team.id,
                organization_id=team.organization_id,
                name=team.name,
                active=team.active,
            )
            for team in teams
        ]
    )
