"""E2E del consumidor de outbox: share/reasignar idempotente por event_id.

Ref: 4.BE.9, RF-29, diseño 11.1. No cubre GET/PATCH (4.BE.10).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.jobs.worker import HANDLERS
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization
from app.modules.notifications.models import (
    EVENT_PLAN_PUBLISHED,
    EVENT_ROUTE_REASSIGNED,
    EVENT_SHARE_CREATED,
    EVENT_SHARE_REVOKED,
    NOTIFICATION_PLAN_PUBLISHED,
    NOTIFICATION_ROUTE_REASSIGNED,
    NOTIFICATION_ROUTE_SHARED,
    Notification,
    OutboxEvent,
)
from app.modules.notifications.service import consume_outbox_event, consume_unprocessed
from tests.test_plan_publish_e2e import _assign, _list_routes, _publish
from tests.test_plans_e2e import _create_user, _seed_generated_plan
from tests.test_routing_order_e2e import _planner_headers_for_assignee, _seed_draft_route
from tests.test_sharing_external_e2e import _create_external
from tests.test_sharing_internal_e2e import _share
from tests.test_sharing_revoke_e2e import _revoke

_PII_KEYS = frozenset(
    {"email", "display_name", "address", "token", "token_hash", "patient_id", "password"}
)


@pytest.fixture()
def queue() -> JobQueue:
    return JobQueue(fakeredis.FakeStrictRedis())


@pytest.fixture()
def client(db_session: Session, queue: JobQueue) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _events(db: Session, *, org_id: uuid.UUID, event_type: str) -> list[OutboxEvent]:
    identity_service.set_current_organization_context(db, organization_id=org_id)
    db.expire_all()
    return (
        db.query(OutboxEvent)
        .filter(OutboxEvent.organization_id == org_id, OutboxEvent.event_type == event_type)
        .order_by(OutboxEvent.created_at)
        .all()
    )


def _assert_payload_clean(payload: dict) -> None:
    assert _PII_KEYS.isdisjoint(payload.keys())


def test_internal_share_consumed_once_by_event_id(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="notif-share")
    org_id = route.organization_id
    planner_headers = _planner_headers_for_assignee(client, db_session, route)
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    field_user = _create_user(db_session, organization=org, role="field", suffix="ns")

    created = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=field_user.id,
        permission="view",
        idempotency_key="notif-share-1",
    )
    assert created.status_code == 201

    events = _events(db_session, org_id=org_id, event_type=EVENT_SHARE_CREATED)
    assert len(events) == 1
    event = events[0]
    assert event.processed_at is None
    _assert_payload_clean(event.payload_json)
    assert event.payload_json["subject_user_id"] == str(field_user.id)
    assert event.payload_json["route_id"] == str(route.id)
    assert event.payload_json["kind"] == "internal"

    first = consume_outbox_event(
        db_session, event_id=event.id, organization_id=org_id
    )
    assert len(first) == 1
    assert first[0].recipient_id == field_user.id
    assert first[0].type == NOTIFICATION_ROUTE_SHARED
    assert first[0].resource_id == route.id
    assert first[0].event_id == event.id
    assert first[0].status == "unread"

    second = consume_outbox_event(
        db_session, event_id=event.id, organization_id=org_id
    )
    assert [row.id for row in second] == [first[0].id]
    rows = (
        db_session.query(Notification)
        .filter(Notification.event_id == event.id)
        .all()
    )
    assert len(rows) == 1
    db_session.refresh(event)
    assert event.processed_at is not None


def test_external_share_processed_without_in_app_row(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="notif-ext")
    headers = _planner_headers_for_assignee(client, db_session, route)
    created = _create_external(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        idempotency_key="notif-ext-1",
    )
    assert created.status_code == 201
    assert created.json()["token"]

    events = _events(
        db_session, org_id=route.organization_id, event_type=EVENT_SHARE_CREATED
    )
    assert len(events) == 1
    _assert_payload_clean(events[0].payload_json)
    assert "subject_user_id" not in events[0].payload_json
    assert "token" not in events[0].payload_json

    rows = consume_outbox_event(
        db_session,
        event_id=events[0].id,
        organization_id=route.organization_id,
    )
    assert rows == []
    db_session.refresh(events[0])
    assert events[0].processed_at is not None
    assert db_session.query(Notification).filter(
        Notification.event_id == events[0].id
    ).all() == []


def test_revoke_is_consumed_without_notification(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="notif-rev")
    org_id = route.organization_id
    planner_headers = _planner_headers_for_assignee(client, db_session, route)
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    field_user = _create_user(db_session, organization=org, role="field", suffix="nrv")
    created = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=field_user.id,
        permission="view",
        idempotency_key="notif-rev-1",
    )
    share_id = uuid.UUID(created.json()["id"])
    revoked = _revoke(client, share_id=share_id, org_id=org_id, headers=planner_headers)
    assert revoked.status_code == 204

    events = _events(db_session, org_id=org_id, event_type=EVENT_SHARE_REVOKED)
    assert len(events) == 1
    _assert_payload_clean(events[0].payload_json)
    rows = consume_outbox_event(
        db_session, event_id=events[0].id, organization_id=org_id
    )
    assert rows == []
    db_session.refresh(events[0])
    assert events[0].processed_at is not None


def test_reassign_notifies_new_assignee(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, _zone = _seed_generated_plan(
        client, db_session, queue, org_name="notif-reassign"
    )
    org_id = org.id
    field_user = _create_user(db_session, organization=org, role="field", suffix="ra")
    published = _publish(client, plan_id=plan_id, org_id=org_id, headers=headers)
    assert published.status_code == 200
    route = _list_routes(
        client, plan_id=plan_id, org_id=org_id, headers=headers
    ).json()["routes"][0]

    assigned = _assign(
        client,
        plan_id=plan_id,
        route_id=route["id"],
        org_id=org_id,
        headers=headers,
        assignee_id=str(field_user.id),
        version=route["version"],
    )
    assert assigned.status_code == 200

    events = _events(db_session, org_id=org_id, event_type=EVENT_ROUTE_REASSIGNED)
    assert len(events) == 1
    _assert_payload_clean(events[0].payload_json)
    assert events[0].payload_json["assignee_id"] == str(field_user.id)
    assert events[0].payload_json["route_id"] == route["id"]

    rows = consume_outbox_event(
        db_session, event_id=events[0].id, organization_id=org_id
    )
    assert len(rows) == 1
    assert rows[0].recipient_id == field_user.id
    assert rows[0].type == NOTIFICATION_ROUTE_REASSIGNED
    assert str(rows[0].resource_id) == route["id"]

    again = consume_outbox_event(
        db_session, event_id=events[0].id, organization_id=org_id
    )
    assert [row.id for row in again] == [rows[0].id]
    assert (
        db_session.query(Notification)
        .filter(Notification.event_id == events[0].id)
        .count()
        == 1
    )


def test_plan_published_notifies_assignees_idempotently(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="notif-publish"
    )
    field_user = _create_user(db_session, organization=org, role="field", suffix="pb")
    published = _publish(
        client,
        plan_id=plan_id,
        org_id=org.id,
        headers=headers,
        body={"assignees": [{"zone_id": str(zone.id), "assignee_id": str(field_user.id)}]},
    )
    assert published.status_code == 200
    outbox_id = uuid.UUID(published.json()["outbox_id"])

    events = _events(db_session, org_id=org.id, event_type=EVENT_PLAN_PUBLISHED)
    assert len(events) == 1
    assert events[0].id == outbox_id
    _assert_payload_clean(events[0].payload_json)

    first = consume_outbox_event(
        db_session, event_id=outbox_id, organization_id=org.id
    )
    assert {row.recipient_id for row in first} == {field_user.id}
    assert all(row.type == NOTIFICATION_PLAN_PUBLISHED for row in first)

    consume_outbox_event(db_session, event_id=outbox_id, organization_id=org.id)
    assert (
        db_session.query(Notification)
        .filter(Notification.event_id == outbox_id)
        .count()
        == len(first)
    )


def test_consume_unprocessed_drains_share_and_is_idempotent(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="notif-drain")
    org_id = route.organization_id
    planner_headers = _planner_headers_for_assignee(client, db_session, route)
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    field_user = _create_user(db_session, organization=org, role="field", suffix="dr")
    created = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=field_user.id,
        permission="edit",
        idempotency_key="notif-drain-1",
    )
    assert created.status_code == 201

    drained = consume_unprocessed(db_session, organization_id=org_id)
    assert drained >= 1
    again = consume_unprocessed(db_session, organization_id=org_id)
    assert again == 0
    events = _events(db_session, org_id=org_id, event_type=EVENT_SHARE_CREATED)
    assert all(event.processed_at is not None for event in events)
    assert (
        db_session.query(Notification)
        .filter(Notification.recipient_id == field_user.id)
        .count()
        == 1
    )


def test_notifications_handler_is_registered() -> None:
    assert "notifications" in HANDLERS
