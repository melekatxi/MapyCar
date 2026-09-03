"""E2E de publicación de plan y asignación de visitador.

Ref: 2.BE.13, 2.BE.14, RF-15. Publicar responde 200 (transacción única, sin worker).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import UserMembership
from app.modules.notifications.models import EVENT_PLAN_PUBLISHED, OutboxEvent
from app.modules.planning.models import DailyRoute, MonthlyPlan
from tests.test_plans_e2e import (
    _create_user,
    _get_plan,
    _login,
    _seed_generated_plan,
    _seed_org_team,
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


def _publish(
    client: TestClient,
    *,
    plan_id: str,
    org_id: uuid.UUID,
    headers: dict[str, str],
    version: int = 1,
    body: dict | None = None,
    if_match: str | None = None,
) -> object:
    request_headers = dict(headers)
    request_headers["If-Match"] = if_match if if_match is not None else f'"{version}"'
    return client.post(
        f"/api/v1/plans/{plan_id}/publish",
        params={"organization_id": str(org_id)},
        json=body if body is not None else {},
        headers=request_headers,
    )


def _list_routes(
    client: TestClient, *, plan_id: str, org_id: uuid.UUID, headers: dict[str, str]
) -> object:
    return client.get(
        f"/api/v1/plans/{plan_id}/routes",
        params={"organization_id": str(org_id)},
        headers=headers,
    )


def _assign(
    client: TestClient,
    *,
    plan_id: str,
    route_id: str,
    org_id: uuid.UUID,
    headers: dict[str, str],
    assignee_id: str,
    version: int,
    if_match: str | None = None,
) -> object:
    request_headers = dict(headers)
    request_headers["If-Match"] = if_match if if_match is not None else f'"{version}"'
    return client.put(
        f"/api/v1/plans/{plan_id}/routes/{route_id}/assignee",
        params={"organization_id": str(org_id)},
        json={"assignee_id": assignee_id},
        headers=request_headers,
    )


def _route_count(db: Session, *, org_id: uuid.UUID, plan_id: str) -> int:
    identity_service.set_current_organization_context(db, organization_id=org_id)
    return (
        db.query(DailyRoute)
        .filter(DailyRoute.plan_id == uuid.UUID(plan_id), DailyRoute.organization_id == org_id)
        .count()
    )


def _outbox_rows(db: Session, *, org_id: uuid.UUID, plan_id: str) -> list[OutboxEvent]:
    identity_service.set_current_organization_context(db, organization_id=org_id)
    return (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.organization_id == org_id,
            OutboxEvent.resource_id == uuid.UUID(plan_id),
            OutboxEvent.event_type == EVENT_PLAN_PUBLISHED,
        )
        .all()
    )


def test_publish_creates_draft_routes_and_outbox(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, _zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org publish default"
    )
    before = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    expected_groups = {(item["date"], item["zone_id"]) for item in before["assignments"]}

    published = _publish(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert published.status_code == 200
    body = published.json()
    assert body["id"] == plan_id
    assert body["status"] == "published"
    assert body["routes_created"] == len(expected_groups)
    assert body["outbox_id"]

    listed = _list_routes(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert listed.status_code == 200
    routes = listed.json()["routes"]
    assert len(routes) == len(expected_groups)
    assert {route["assignee_id"] for route in routes} == {before["created_by"]}
    assert all(route["status"] == "draft" for route in routes)
    assert all(route["current_revision"] is None for route in routes)
    assert all(route["version"] == 1 for route in routes)
    assert {(route["service_date"], route["zone_id"]) for route in routes} == expected_groups

    fetched = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert fetched["status"] == "published"
    assert fetched["version"] == 1

    events = _outbox_rows(db_session, org_id=org.id, plan_id=plan_id)
    assert len(events) == 1
    assert str(events[0].id) == body["outbox_id"]
    assert events[0].processed_at is None
    payload = events[0].payload_json
    assert payload["routes_created"] == len(expected_groups)
    assert payload["plan_id"] == plan_id
    for forbidden in ("email", "display_name", "address", "patient_id", "patients"):
        assert forbidden not in payload
        assert forbidden not in payload.get("assignee_ids", [])

    identity_service.set_current_organization_context(db_session, organization_id=org.id)
    plan = db_session.get(MonthlyPlan, uuid.UUID(plan_id))
    assert plan is not None
    assert plan.published_at is not None


def test_publish_with_field_assignee(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org publish field"
    )
    field_user = _create_user(db_session, organization=org, role="field")

    published = _publish(
        client,
        plan_id=plan_id,
        org_id=org.id,
        headers=headers,
        body={"assignees": [{"zone_id": str(zone.id), "assignee_id": str(field_user.id)}]},
    )
    assert published.status_code == 200
    listed = _list_routes(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert {route["assignee_id"] for route in listed.json()["routes"]} == {str(field_user.id)}


def test_second_publish_returns_409_without_new_rows(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, _zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org publish twice"
    )
    first = _publish(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert first.status_code == 200
    routes_after = _route_count(db_session, org_id=org.id, plan_id=plan_id)
    outbox_after = len(_outbox_rows(db_session, org_id=org.id, plan_id=plan_id))

    second = _publish(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert second.status_code == 409
    assert second.json()["code"] == "PLAN_PUBLISHED"
    assert _route_count(db_session, org_id=org.id, plan_id=plan_id) == routes_after
    assert len(_outbox_rows(db_session, org_id=org.id, plan_id=plan_id)) == outbox_after


def test_publish_without_assignments_409(client: TestClient, db_session: Session) -> None:
    org, team = _seed_org_team(db_session, name="Org publish empty")
    user = _create_user(db_session, organization=org, role="planner")
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org.id),
            "team_id": str(team.id),
            "period": "2026-09",
            "constraints": {},
        },
        headers=headers,
    )
    assert created.status_code == 201
    plan_id = created.json()["id"]

    published = _publish(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert published.status_code == 409
    assert published.json()["code"] == "PLAN_NO_ASSIGNMENTS"
    assert _route_count(db_session, org_id=org.id, plan_id=plan_id) == 0
    assert _outbox_rows(db_session, org_id=org.id, plan_id=plan_id) == []


def test_publish_if_match_required_and_stale(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, _zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org publish if-match"
    )
    missing = client.post(
        f"/api/v1/plans/{plan_id}/publish",
        params={"organization_id": str(org.id)},
        json={},
        headers=headers,
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "IF_MATCH_REQUIRED"

    stale = _publish(client, plan_id=plan_id, org_id=org.id, headers=headers, if_match='"0"')
    assert stale.status_code == 409
    assert stale.json()["code"] == "PLAN_VERSION_CONFLICT"
    fetched = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert fetched["status"] == "draft"


def test_field_cannot_publish(client: TestClient, db_session: Session, queue: JobQueue) -> None:
    org, plan_id, _planner_headers, _patients, _zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org publish field forbidden"
    )
    field_user = _create_user(db_session, organization=org, role="field")
    token = _login(client, field_user)
    response = _publish(
        client,
        plan_id=plan_id,
        org_id=org.id,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ROLE"


def test_publish_foreign_assignee_404(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org publish foreign"
    )
    org_id, zone_id = org.id, str(zone.id)
    other_org, _other_team = _seed_org_team(db_session, name="Org publish foreign other")
    foreign = _create_user(db_session, organization=other_org, role="field")
    foreign_id = str(foreign.id)

    published = _publish(
        client,
        plan_id=plan_id,
        org_id=org_id,
        headers=headers,
        body={"assignees": [{"zone_id": zone_id, "assignee_id": foreign_id}]},
    )
    assert published.status_code == 404
    assert published.json()["code"] == "ASSIGNEE_NOT_FOUND"
    fetched = _get_plan(client, plan_id=plan_id, org_id=org_id, headers=headers)
    assert fetched["status"] == "draft"


def test_publish_assignee_required_when_creator_has_no_membership(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org publish required"
    )
    org_id, zone_id = org.id, str(zone.id)
    before = _get_plan(client, plan_id=plan_id, org_id=org_id, headers=headers)
    creator_id = uuid.UUID(before["created_by"])
    other = _create_user(db_session, organization=org, role="planner")
    other_id = str(other.id)
    other_token = _login(client, other)
    other_headers = {"Authorization": f"Bearer {other_token}"}

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    db_session.query(UserMembership).filter(
        UserMembership.user_id == creator_id,
        UserMembership.organization_id == org_id,
    ).delete()
    db_session.commit()

    missing = _publish(client, plan_id=plan_id, org_id=org_id, headers=other_headers)
    assert missing.status_code == 422
    assert missing.json()["code"] == "ASSIGNEE_REQUIRED"

    published = _publish(
        client,
        plan_id=plan_id,
        org_id=org_id,
        headers=other_headers,
        body={"assignees": [{"zone_id": zone_id, "assignee_id": other_id}]},
    )
    assert published.status_code == 200


def test_assign_field_user_and_foreign_404(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, _zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org assign field"
    )
    org_id = org.id
    field_user = _create_user(db_session, organization=org, role="field")
    field_id = str(field_user.id)
    other_org, _other_team = _seed_org_team(db_session, name="Org assign foreign")
    foreign = _create_user(db_session, organization=other_org, role="field")
    foreign_id = str(foreign.id)

    published = _publish(client, plan_id=plan_id, org_id=org_id, headers=headers)
    assert published.status_code == 200
    routes = _list_routes(client, plan_id=plan_id, org_id=org_id, headers=headers).json()["routes"]
    route = routes[0]

    assigned = _assign(
        client,
        plan_id=plan_id,
        route_id=route["id"],
        org_id=org_id,
        headers=headers,
        assignee_id=field_id,
        version=route["version"],
    )
    assert assigned.status_code == 200
    assert assigned.json()["assignee_id"] == field_id
    assert assigned.json()["version"] == route["version"] + 1
    assert assigned.headers["etag"] == f'"{route["version"] + 1}"'

    forbidden = _assign(
        client,
        plan_id=plan_id,
        route_id=route["id"],
        org_id=org_id,
        headers=headers,
        assignee_id=foreign_id,
        version=route["version"] + 1,
    )
    assert forbidden.status_code == 404
    assert forbidden.json()["code"] == "ASSIGNEE_NOT_FOUND"

    listed = _list_routes(client, plan_id=plan_id, org_id=org_id, headers=headers)
    current = next(item for item in listed.json()["routes"] if item["id"] == route["id"])
    assert current["assignee_id"] == str(field_user.id)


def test_assign_unique_clash_409(client: TestClient, db_session: Session, queue: JobQueue) -> None:
    org, plan_id, headers, _patients, _zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org assign clash"
    )
    other = _create_user(db_session, organization=org, role="field")
    published = _publish(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert published.status_code == 200

    listed = _list_routes(client, plan_id=plan_id, org_id=org.id, headers=headers)
    first = listed.json()["routes"][0]
    identity_service.set_current_organization_context(db_session, organization_id=org.id)
    db_session.add(
        DailyRoute(
            organization_id=org.id,
            plan_id=uuid.UUID(plan_id),
            zone_id=uuid.UUID(first["zone_id"]),
            service_date=date.fromisoformat(first["service_date"]),
            assignee_id=other.id,
            status="draft",
        )
    )
    db_session.commit()

    clash = _assign(
        client,
        plan_id=plan_id,
        route_id=first["id"],
        org_id=org.id,
        headers=headers,
        assignee_id=str(other.id),
        version=first["version"],
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "ROUTE_ASSIGNEE_CONFLICT"


def test_assign_if_match_and_unpublished(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, _zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org assign if-match"
    )
    field_user = _create_user(db_session, organization=org, role="field")
    unpublished = _assign(
        client,
        plan_id=plan_id,
        route_id=str(uuid.uuid4()),
        org_id=org.id,
        headers=headers,
        assignee_id=str(field_user.id),
        version=1,
    )
    assert unpublished.status_code == 409
    assert unpublished.json()["code"] == "PLAN_NOT_PUBLISHED"

    published = _publish(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert published.status_code == 200
    route = _list_routes(client, plan_id=plan_id, org_id=org.id, headers=headers).json()["routes"][
        0
    ]

    missing = client.put(
        f"/api/v1/plans/{plan_id}/routes/{route['id']}/assignee",
        params={"organization_id": str(org.id)},
        json={"assignee_id": str(field_user.id)},
        headers=headers,
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "IF_MATCH_REQUIRED"

    stale = _assign(
        client,
        plan_id=plan_id,
        route_id=route["id"],
        org_id=org.id,
        headers=headers,
        assignee_id=str(field_user.id),
        version=1,
        if_match='"0"',
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "ROUTE_VERSION_CONFLICT"


def test_field_cannot_assign_or_list_routes(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, _zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org assign field forbidden"
    )
    field_user = _create_user(db_session, organization=org, role="field")
    published = _publish(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert published.status_code == 200
    route = _list_routes(client, plan_id=plan_id, org_id=org.id, headers=headers).json()["routes"][
        0
    ]
    token = _login(client, field_user)
    field_headers = {"Authorization": f"Bearer {token}"}

    listed = _list_routes(client, plan_id=plan_id, org_id=org.id, headers=field_headers)
    assert listed.status_code == 403
    assert listed.json()["code"] == "FORBIDDEN_ROLE"

    assigned = _assign(
        client,
        plan_id=plan_id,
        route_id=route["id"],
        org_id=org.id,
        headers=field_headers,
        assignee_id=str(field_user.id),
        version=1,
    )
    assert assigned.status_code == 403
    assert assigned.json()["code"] == "FORBIDDEN_ROLE"
