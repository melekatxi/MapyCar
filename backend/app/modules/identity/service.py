from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.modules.identity.models import Team, User, UserMembership


def set_current_user_context(db: Session, *, user_id: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_user_id', :uid, false)"), {"uid": str(user_id)})


def set_current_organization_context(db: Session, *, organization_id: uuid.UUID) -> None:
    db.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
        {"org_id": str(organization_id)},
    )


def authenticate(db: Session, *, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email_normalized == email.lower()).one_or_none()
    if user is None or user.password_hash is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_memberships(db: Session, *, user_id: uuid.UUID) -> list[UserMembership]:
    return db.query(UserMembership).filter(UserMembership.user_id == user_id).all()


def is_member_of_organization(db: Session, *, user_id: uuid.UUID, organization_id: uuid.UUID) -> bool:
    return (
        db.query(UserMembership)
        .filter(
            UserMembership.user_id == user_id,
            UserMembership.organization_id == organization_id,
        )
        .one_or_none()
        is not None
    )


def list_teams(db: Session, *, organization_id: uuid.UUID) -> list[Team]:
    """Equipos de la organización. RLS exige el contexto de tenant antes de leer."""
    set_current_organization_context(db, organization_id=organization_id)
    return (
        db.query(Team)
        .filter(Team.organization_id == organization_id)
        .order_by(Team.name)
        .all()
    )
