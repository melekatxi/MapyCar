"""Esquema de notifications: UNIQUE event_id+recipient, CHECK y RLS.

Ref: 4.BE.9, diseño 6.1 / 11.1.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.identity.models import User, UserMembership
from app.modules.notifications.models import (
    NOTIFICATION_ROUTE_SHARED,
    NOTIFICATION_STATUS_UNREAD,
    Notification,
    OutboxEvent,
)
from tests.test_routing_schema import _seed_route, _set_org


def _add_member(db: Session, *, org_id: uuid.UUID, suffix: str) -> User:
    user = User(
        email_normalized=f"notif-{suffix}-{uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Receptor {suffix}",
    )
    db.add(user)
    db.flush()
    db.add(UserMembership(organization_id=org_id, user_id=user.id, role="field"))
    db.flush()
    return user


def _outbox(db: Session, *, org_id: uuid.UUID, resource_id: uuid.UUID) -> OutboxEvent:
    event = OutboxEvent(
        organization_id=org_id,
        event_type="share.created",
        resource_type="share_grant",
        resource_id=resource_id,
        payload_json={"route_id": str(resource_id)},
    )
    db.add(event)
    db.flush()
    return event


def test_notification_insert_is_valid(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "n-ok")
    event = _outbox(db_session, org_id=org.id, resource_id=route.id)
    db_session.add(
        Notification(
            organization_id=org.id,
            recipient_id=user.id,
            type=NOTIFICATION_ROUTE_SHARED,
            resource_id=route.id,
            event_id=event.id,
            status=NOTIFICATION_STATUS_UNREAD,
        )
    )
    db_session.commit()


def test_duplicate_event_recipient_fails(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "n-dup")
    event = _outbox(db_session, org_id=org.id, resource_id=route.id)
    db_session.add(
        Notification(
            organization_id=org.id,
            recipient_id=user.id,
            type=NOTIFICATION_ROUTE_SHARED,
            resource_id=route.id,
            event_id=event.id,
        )
    )
    db_session.commit()
    db_session.add(
        Notification(
            organization_id=org.id,
            recipient_id=user.id,
            type=NOTIFICATION_ROUTE_SHARED,
            resource_id=route.id,
            event_id=event.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_same_event_two_recipients_ok(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "n-two")
    other = _add_member(db_session, org_id=org.id, suffix="two")
    event = _outbox(db_session, org_id=org.id, resource_id=route.id)
    db_session.add_all(
        [
            Notification(
                organization_id=org.id,
                recipient_id=user.id,
                type=NOTIFICATION_ROUTE_SHARED,
                resource_id=route.id,
                event_id=event.id,
            ),
            Notification(
                organization_id=org.id,
                recipient_id=other.id,
                type=NOTIFICATION_ROUTE_SHARED,
                resource_id=route.id,
                event_id=event.id,
            ),
        ]
    )
    db_session.commit()


def test_invalid_type_fails_check(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "n-type")
    event = _outbox(db_session, org_id=org.id, resource_id=route.id)
    db_session.add(
        Notification(
            organization_id=org.id,
            recipient_id=user.id,
            type="email.blast",
            resource_id=route.id,
            event_id=event.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_notifications_has_force_rls(db_session: Session) -> None:
    row = db_session.execute(
        text(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = 'notifications'
            """
        )
    ).one()
    assert row == (True, True)


def test_organization_a_cannot_read_notifications_of_b(db_session: Session) -> None:
    org_a, user_a, route_a, _patient_a = _seed_route(db_session, "n-A")
    event_a = _outbox(db_session, org_id=org_a.id, resource_id=route_a.id)
    db_session.add(
        Notification(
            organization_id=org_a.id,
            recipient_id=user_a.id,
            type=NOTIFICATION_ROUTE_SHARED,
            resource_id=route_a.id,
            event_id=event_a.id,
        )
    )
    db_session.commit()

    org_b, user_b, route_b, _patient_b = _seed_route(db_session, "n-B")
    event_b = _outbox(db_session, org_id=org_b.id, resource_id=route_b.id)
    db_session.add(
        Notification(
            organization_id=org_b.id,
            recipient_id=user_b.id,
            type=NOTIFICATION_ROUTE_SHARED,
            resource_id=route_b.id,
            event_id=event_b.id,
        )
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible = {row.organization_id for row in db_session.query(Notification).all()}
    assert visible == {org_a.id}

    _set_org(db_session, org_b.id)
    visible = {row.organization_id for row in db_session.query(Notification).all()}
    assert visible == {org_b.id}


def test_notifications_hidden_without_org_context(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "n-empty")
    event = _outbox(db_session, org_id=org.id, resource_id=route.id)
    db_session.add(
        Notification(
            organization_id=org.id,
            recipient_id=user.id,
            type=NOTIFICATION_ROUTE_SHARED,
            resource_id=route.id,
            event_id=event.id,
        )
    )
    db_session.commit()

    db_session.execute(text("RESET app.current_organization_id"))
    assert db_session.query(Notification).all() == []
    assert db_session.query(OutboxEvent).all() == []
