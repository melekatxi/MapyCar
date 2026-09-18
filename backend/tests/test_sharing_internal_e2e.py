"""E2E de POST/GET /routes/{id}/shares interno. Ref: 4.BE.6, RF-27, diseño 7.7.

view no modifica; edit sí solo si el rol es planner/admin.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization
from app.modules.planning.models import DailyRoute
from tests.test_plans_e2e import _create_user, _login
from tests.test_routing_optimize_e2e import _get_route
from tests.test_routing_order_e2e import _planner_headers_for_assignee, _reorder, _seed_draft_route


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _headers_for(client: TestClient, user) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, user)}"}


def _share(
    client: TestClient,
    *,
    route_id,
    org_id,
    headers: dict[str, str],
    subject_user_id,
    permission: str,
    idempotency_key: str,
):
    request_headers = dict(headers)
    request_headers["Idempotency-Key"] = idempotency_key
    return client.post(
        f"/api/v1/routes/{route_id}/shares",
        params={"organization_id": str(org_id)},
        json={"subject_user_id": str(subject_user_id), "permission": permission},
        headers=request_headers,
    )


def _list_shares(client: TestClient, *, route_id, org_id, headers: dict[str, str]):
    return client.get(
        f"/api/v1/routes/{route_id}/shares",
        params={"organization_id": str(org_id)},
        headers=headers,
    )


def test_internal_share_view_cannot_edit_edit_can_if_role_allows(
    client: TestClient, db_session: Session
) -> None:
    route, revision, stops, _metric = _seed_draft_route(db_session, org_name="share-acl")
    org_id = route.organization_id
    planner_headers = _planner_headers_for_assignee(client, db_session, route)
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    field_user = _create_user(db_session, organization=org, role="field", suffix="vw")
    field_editor = _create_user(db_session, organization=org, role="field", suffix="edf")
    other_planner = _create_user(db_session, organization=org, role="planner", suffix="ed")

    view_share = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=field_user.id,
        permission="view",
        idempotency_key="share-view-1",
    )
    assert view_share.status_code == 201
    body = view_share.json()
    assert body["permission"] == "view"
    assert body["kind"] == "internal"
    assert body["subject_user_id"] == str(field_user.id)
    assert "token_hash" not in body
    assert body.get("token") is None

    listed = _list_shares(client, route_id=route.id, org_id=org_id, headers=planner_headers)
    assert listed.status_code == 200
    grants = listed.json()["grants"]
    assert len(grants) == 1
    assert "token_hash" not in grants[0]

    field_headers = _headers_for(client, field_user)
    viewed = _get_route(client, route_id=route.id, org_id=org_id, headers=field_headers)
    assert viewed.status_code == 200

    blocked = _reorder(
        client,
        route_id=route.id,
        org_id=org_id,
        revision_id=revision.id,
        ordered_stop_ids=list(reversed([stop.id for stop in stops])),
        headers=field_headers,
        version=route.version,
    )
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "FORBIDDEN_ROLE"

    field_edit = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=field_user.id,
        permission="edit",
        idempotency_key="share-field-dup",
    )
    assert field_edit.status_code == 409
    assert field_edit.json()["code"] == "SHARE_ALREADY_EXISTS"

    field_as_editor = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=field_editor.id,
        permission="edit",
        idempotency_key="share-field-edit",
    )
    assert field_as_editor.status_code == 201
    field_editor_headers = _headers_for(client, field_editor)
    role_blocked = _reorder(
        client,
        route_id=route.id,
        org_id=org_id,
        revision_id=revision.id,
        ordered_stop_ids=list(reversed([stop.id for stop in stops])),
        headers=field_editor_headers,
        version=route.version,
    )
    assert role_blocked.status_code == 403
    assert role_blocked.json()["code"] == "FORBIDDEN_ROLE"

    edit_share = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=other_planner.id,
        permission="edit",
        idempotency_key="share-edit-1",
    )
    assert edit_share.status_code == 201
    assert edit_share.json()["permission"] == "edit"

    planner_b = _headers_for(client, other_planner)
    allowed = _reorder(
        client,
        route_id=route.id,
        org_id=org_id,
        revision_id=revision.id,
        ordered_stop_ids=list(reversed([stop.id for stop in stops])),
        headers=planner_b,
        version=route.version,
    )
    assert allowed.status_code == 200


def test_share_idempotent_replay_and_requires_key(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="share-idem")
    org_id = route.organization_id
    planner_headers = _planner_headers_for_assignee(client, db_session, route)
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    viewer = _create_user(db_session, organization=org, role="supervisor", suffix="sup")

    missing = client.post(
        f"/api/v1/routes/{route.id}/shares",
        params={"organization_id": str(org_id)},
        json={"subject_user_id": str(viewer.id), "permission": "view"},
        headers=planner_headers,
    )
    assert missing.status_code == 400
    assert missing.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    first = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=viewer.id,
        permission="view",
        idempotency_key="same-key",
    )
    assert first.status_code == 201
    replay = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=viewer.id,
        permission="view",
        idempotency_key="same-key",
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    reused = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=viewer.id,
        permission="edit",
        idempotency_key="same-key",
    )
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSE"

    supervisor_headers = _headers_for(client, viewer)
    viewed = _get_route(client, route_id=route.id, org_id=org_id, headers=supervisor_headers)
    assert viewed.status_code == 200


def test_field_cannot_create_share_and_unknown_subject_404(
    client: TestClient, db_session: Session
) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="share-403")
    org_id = route.organization_id
    planner_headers = _planner_headers_for_assignee(client, db_session, route)
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    field_user = _create_user(db_session, organization=org, role="field", suffix="no")
    field_headers = _headers_for(client, field_user)

    denied = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=field_headers,
        subject_user_id=field_user.id,
        permission="view",
        idempotency_key="field-share",
    )
    assert denied.status_code == 403

    missing = _share(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=planner_headers,
        subject_user_id=route.id,
        permission="view",
        idempotency_key="ghost-user",
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "SHARE_SUBJECT_NOT_FOUND"


def test_share_self_rejected(client: TestClient, db_session: Session) -> None:
    route, _revision, _stops, _metric = _seed_draft_route(db_session, org_name="share-self")
    persisted = db_session.get(DailyRoute, route.id)
    assert persisted is not None
    planner_headers = _planner_headers_for_assignee(client, db_session, route)
    response = _share(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=planner_headers,
        subject_user_id=persisted.assignee_id,
        permission="view",
        idempotency_key="self-share",
    )
    assert response.status_code == 422
    assert response.json()["code"] == "SHARE_SELF_NOT_ALLOWED"
