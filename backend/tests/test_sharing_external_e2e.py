"""E2E de enlace externo y POST /public-shares/exchange.

Ref: 4.BE.7, RF-28, diseño 7.7 / 8.6.
Token ≥256 bit, solo hash en BD. Vencido/revocado → 410. Vista minimizada.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.sharing.models import ShareGrant
from app.modules.sharing.tokens import COOKIE_NAME, hash_share_token
from tests.test_routing_order_e2e import _planner_headers_for_assignee, _seed_draft_route


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _create_external(
    client: TestClient,
    *,
    route_id: uuid.UUID,
    org_id: uuid.UUID,
    headers: dict[str, str],
    expires_at: datetime,
    idempotency_key: str,
):
    request_headers = dict(headers)
    request_headers["Idempotency-Key"] = idempotency_key
    return client.post(
        f"/api/v1/routes/{route_id}/shares",
        params={"organization_id": str(org_id)},
        json={"permission": "view", "expires_at": expires_at.isoformat()},
        headers=request_headers,
    )


def _exchange(client: TestClient, token: str):
    return client.post("/api/v1/public-shares/exchange", json={"token": token})


def test_external_token_once_hashed_and_view_is_minimized(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, stops, _metric = _seed_draft_route(db_session, org_name="share-ext-ok")
    headers = _planner_headers_for_assignee(client, db_session, route)
    expires = datetime.now(UTC) + timedelta(days=2)
    created = _create_external(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        expires_at=expires,
        idempotency_key="ext-1",
    )
    assert created.status_code == 201
    body = created.json()
    token = body["token"]
    assert token
    padding = "=" * (-len(token) % 4)
    raw = base64.urlsafe_b64decode(token + padding)
    assert len(raw) >= 32
    assert body["kind"] == "external"
    assert body["subject_user_id"] is None
    assert "token_hash" not in body

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    stored = db_session.get(ShareGrant, uuid.UUID(body["id"]))
    assert stored is not None
    assert stored.token_hash == hash_share_token(token)
    assert stored.token_hash != token
    assert stored.subject_user_id is None
    assert stored.expires_at is not None

    listed = client.get(
        f"/api/v1/routes/{route.id}/shares",
        params={"organization_id": str(route.organization_id)},
        headers=headers,
    )
    assert listed.status_code == 200
    listed_grant = listed.json()["grants"][0]
    assert listed_grant.get("token") is None
    assert "token_hash" not in listed_grant

    exchanged = _exchange(client, token)
    assert exchanged.status_code == 200
    assert exchanged.headers.get("referrer-policy") == "no-referrer"
    assert COOKIE_NAME in exchanged.headers.get("set-cookie", "").lower()
    view = exchanged.json()
    assert view["route_id"] == str(route.id)
    assert view["stop_count"] == len(stops)
    assert [item["sequence"] for item in view["stops"]] == [1, 2, 3]
    dumped = str(view)
    assert "patient_id" not in dumped
    assert "external_ref" not in dumped
    assert "failure_reason" not in dumped
    assert "lat" not in dumped
    assert "lon" not in dumped
    assert set(view["stops"][0]) == {"sequence"}


def test_expired_and_revoked_tokens_return_410(client: TestClient, db_session: Session) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="share-ext-410")
    headers = _planner_headers_for_assignee(client, db_session, route)
    expires = datetime.now(UTC) + timedelta(days=1)
    created = _create_external(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        expires_at=expires,
        idempotency_key="ext-410",
    )
    assert created.status_code == 201
    token = created.json()["token"]
    grant_id = uuid.UUID(created.json()["id"])

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    grant = db_session.get(ShareGrant, grant_id)
    assert grant is not None
    grant.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    expired = _exchange(client, token)
    assert expired.status_code == 410
    assert expired.json()["code"] == "SHARE_EXPIRED"

    grant = db_session.get(ShareGrant, grant_id)
    assert grant is not None
    grant.expires_at = datetime.now(UTC) + timedelta(days=1)
    grant.revoked_at = datetime.now(UTC)
    db_session.commit()

    revoked = _exchange(client, token)
    assert revoked.status_code == 410
    assert revoked.json()["code"] == "SHARE_REVOKED"


def test_unknown_token_returns_401_and_external_requires_expiry(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="share-ext-401")
    headers = _planner_headers_for_assignee(client, db_session, route)
    missing = client.post(
        f"/api/v1/routes/{route.id}/shares",
        params={"organization_id": str(route.organization_id)},
        json={"permission": "view"},
        headers={**headers, "Idempotency-Key": "ext-no-exp"},
    )
    assert missing.status_code == 422

    unknown = _exchange(client, "A" * 43)
    assert unknown.status_code == 401
    assert unknown.json()["code"] == "SHARE_TOKEN_INVALID"


def test_external_share_idempotent_replay(client: TestClient, db_session: Session) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="share-ext-id")
    headers = _planner_headers_for_assignee(client, db_session, route)
    expires = datetime.now(UTC) + timedelta(days=3)
    first = _create_external(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        expires_at=expires,
        idempotency_key="ext-replay",
    )
    replay = _create_external(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        expires_at=expires,
        idempotency_key="ext-replay",
    )
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["token"] == first.json()["token"]
