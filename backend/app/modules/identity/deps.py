from __future__ import annotations

import uuid

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.core.security import verify_session_token
from app.db.session import get_db
from app.modules.identity import service
from app.modules.identity.models import User


def get_current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise DomainError(401, "NOT_AUTHENTICATED", "Falta token de sesión")
    token = authorization.removeprefix("Bearer ")
    user_id = verify_session_token(token)
    if user_id is None:
        raise DomainError(401, "NOT_AUTHENTICATED", "Token inválido o caducado")
    user = db.get(User, uuid.UUID(user_id))
    if user is None:
        raise DomainError(401, "NOT_AUTHENTICATED", "Usuario no encontrado")
    service.set_current_user_context(db, user_id=user.id)
    return user


def require_organization_member(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    service.set_current_organization_context(db, organization_id=organization_id)
    if not service.is_member_of_organization(
        db, user_id=current_user.id, organization_id=organization_id
    ):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    return current_user
