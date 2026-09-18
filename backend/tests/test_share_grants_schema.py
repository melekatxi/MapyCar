"""Esquema de share_grants: CHECK sujeto XOR token y expiración externa.

Ref: 4.BE.5, diseño 6.1 / 7.7.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.sharing.models import ShareGrant
from tests.test_routing_schema import _seed_route, _set_org


def _hash(label: str) -> str:
    return (label * 32)[:64]


def test_internal_grant_without_token_is_valid(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "share-int")
    db_session.add(
        ShareGrant(
            organization_id=org.id,
            route_id=route.id,
            subject_user_id=user.id,
            permission="view",
            created_by=user.id,
        )
    )
    db_session.commit()


def test_external_grant_with_hash_and_expiry_is_valid(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "share-ext")
    db_session.add(
        ShareGrant(
            organization_id=org.id,
            route_id=route.id,
            permission="edit",
            token_hash=_hash("ext"),
            expires_at=datetime.now(UTC) + timedelta(days=7),
            created_by=user.id,
        )
    )
    db_session.commit()


def test_grant_with_subject_and_token_fails_xor(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "share-both")
    db_session.add(
        ShareGrant(
            organization_id=org.id,
            route_id=route.id,
            subject_user_id=user.id,
            permission="view",
            token_hash=_hash("both"),
            expires_at=datetime.now(UTC) + timedelta(days=1),
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_grant_without_subject_or_token_fails_xor(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "share-none")
    db_session.add(
        ShareGrant(
            organization_id=org.id,
            route_id=route.id,
            permission="view",
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_external_grant_without_expiry_fails(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "share-exp")
    db_session.add(
        ShareGrant(
            organization_id=org.id,
            route_id=route.id,
            permission="view",
            token_hash=_hash("exp"),
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_permission_check_rejects_invalid(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "share-perm")
    db_session.add(
        ShareGrant(
            organization_id=org.id,
            route_id=route.id,
            subject_user_id=user.id,
            permission="admin",
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_duplicate_token_hash_fails(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "share-dup")
    expires = datetime.now(UTC) + timedelta(days=2)
    token_hash = _hash("dup")
    db_session.add(
        ShareGrant(
            organization_id=org.id,
            route_id=route.id,
            permission="view",
            token_hash=token_hash,
            expires_at=expires,
            created_by=user.id,
        )
    )
    db_session.commit()
    _set_org(db_session, org.id)
    db_session.add(
        ShareGrant(
            organization_id=org.id,
            route_id=route.id,
            permission="view",
            token_hash=token_hash,
            expires_at=expires,
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
