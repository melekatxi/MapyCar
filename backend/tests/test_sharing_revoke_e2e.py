"""E2E de DELETE /shares/{id}: revocación inmediata. Ref: 4.BE.8, RF-27, RF-28."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization
from app.modules.notifications.models import OutboxEvent
from app.modules.sharing.models import ShareGrant
from tests.test_plans_e2e import _create_user, _login
from tests.test_routing_optimize_e2e import _get_route
from tests.test_routing_order_e2e import _planner_headers_for_assignee, _seed_draft_route
from tests.test_sharing_external_e2e import _create_external, _exchange
from tests.test_sharing_internal_e2e import _headers_for, _list_shares, _share


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _revoke(client: TestClient, *, share_id: uuid.UUID, org_id: uuid.UUID, headers: dict[str, str]):
    return client.delete(
        f"/api/v1/shares/{share_id}",
        params={"organization_id": str(org_id)},
        headers=headers,
    )


def test_revoke_internal_share_blocks_get_immediately(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="share-rev-int")
    org_id = route.organization_id
    planner_headers = _planner_headers_for_assignee(client, db_session, route)
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    field_user = _create_user(db_session, organization=org, role="field", suffix="rv")

    created = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=field_user.id,
        permission="view",
        idempotency_key="rev-int-1",
    )
    assert created.status_code == 201
    share_id = uuid.UUID(created.json()["id"])
    field_headers = _headers_for(client, field_user)
    assert _get_route(client, route_id=route.id, org_id=org_id, headers=field_headers).status_code == 200

    revoked = _revoke(client, share_id=share_id, org_id=org_id, headers=planner_headers)
    assert revoked.status_code == 204

    denied = _get_route(client, route_id=route.id, org_id=org_id, headers=field_headers)
    assert denied.status_code == 403
    listed = _list_shares(client, route_id=route.id, org_id=org_id, headers=planner_headers)
    assert listed.json()["grants"] == []

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    db_session.expire_all()
    grant = db_session.get(ShareGrant, share_id)
    assert grant is not None
    assert grant.revoked_at is not None
    events = (
        db_session.query(OutboxEvent)
        .filter(OutboxEvent.event_type == "share.revoked", OutboxEvent.resource_id == share_id)
        .all()
    )
    assert len(events) == 1
    assert events[0].payload_json["kind"] == "internal"

    again = _revoke(client, share_id=share_id, org_id=org_id, headers=planner_headers)
    assert again.status_code == 409
    assert again.json()["code"] == "SHARE_ALREADY_REVOKED"


def test_revoke_external_token_blocks_exchange_immediately(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="share-rev-ext")
    headers = _planner_headers_for_assignee(client, db_session, route)
    created = _create_external(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        idempotency_key="rev-ext-1",
    )
    assert created.status_code == 201
    token = created.json()["token"]
    share_id = uuid.UUID(created.json()["id"])
    assert _exchange(client, token).status_code == 200

    revoked = _revoke(
        client, share_id=share_id, org_id=route.organization_id, headers=headers
    )
    assert revoked.status_code == 204
    blocked = _exchange(client, token)
    assert blocked.status_code == 410
    assert blocked.json()["code"] == "SHARE_REVOKED"


def test_field_cannot_revoke_and_unknown_share_404(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="share-rev-403")
    org_id = route.organization_id
    planner_headers = _planner_headers_for_assignee(client, db_session, route)
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    field_user = _create_user(db_session, organization=org, role="field", suffix="nr")
    created = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=field_user.id,
        permission="view",
        idempotency_key="rev-403",
    )
    share_id = uuid.UUID(created.json()["id"])
    field_headers = {"Authorization": f"Bearer {_login(client, field_user)}"}
    denied = _revoke(client, share_id=share_id, org_id=org_id, headers=field_headers)
    assert denied.status_code == 403

    missing = _revoke(client, share_id=uuid.uuid4(), org_id=org_id, headers=planner_headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "SHARE_NOT_FOUND"
