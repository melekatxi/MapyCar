"""E2E de PATCH /routes/{id}/stops/{stopId}: ejecución, If-Match y 409.

Ref: 4.BE.2, RF-25, diseño 7.6 / 8.5. If-Match = route_stops.version.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.router.fake import FakeRouter
from app.core.crypto import FieldCipher, KeyProvider
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization
from app.modules.imports.deps import get_field_cipher
from app.modules.planning.models import DailyRoute
from app.modules.routing.models import RouteRevision, RouteStop
from app.modules.zoning.deps import get_router
from tests.test_plans_e2e import _create_user, _login
from tests.test_routing_optimize_e2e import _get_route
from tests.test_routing_order_e2e import (
    _auth_headers,
    _planner_headers_for_assignee,
    _seed_draft_route,
)
from tests.test_routing_publish_e2e import _prepare_optimized_route, _publish


class _StaticKeyProvider(KeyProvider):
    def __init__(self, active: str, keys: dict[str, bytes]) -> None:
        self._active = active
        self._keys = keys

    def active_key_id(self) -> str:
        return self._active

    def get_key(self, key_id: str) -> bytes:
        return self._keys[key_id]


@pytest.fixture()
def queue() -> JobQueue:
    return JobQueue(fakeredis.FakeStrictRedis())


@pytest.fixture()
def cipher() -> FieldCipher:
    return FieldCipher(_StaticKeyProvider("k1", {"k1": os.urandom(32)}))


@pytest.fixture()
def client(db_session: Session, queue: JobQueue, cipher: FieldCipher) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    app.dependency_overrides[get_router] = lambda: FakeRouter()
    app.dependency_overrides[get_field_cipher] = lambda: cipher
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _stops(db: Session, revision_id: uuid.UUID) -> list[RouteStop]:
    return (
        db.query(RouteStop)
        .filter(RouteStop.revision_id == revision_id)
        .order_by(RouteStop.sequence)
        .all()
    )


def _report(
    client: TestClient,
    *,
    route_id: uuid.UUID,
    org_id: uuid.UUID,
    stop_id: uuid.UUID,
    headers: dict[str, str],
    version: int,
    body: dict,
    if_match: str | None = None,
):
    request_headers = dict(headers)
    request_headers["If-Match"] = if_match if if_match is not None else f'"{version}"'
    return client.patch(
        f"/api/v1/routes/{route_id}/stops/{stop_id}",
        params={"organization_id": str(org_id)},
        json=body,
        headers=request_headers,
    )


def _publish_ready(
    client: TestClient, db: Session, cipher: FieldCipher, *, org_name: str
) -> tuple[DailyRoute, uuid.UUID, list[RouteStop], dict[str, str], dict]:
    route, _planner, _patients, revision, headers = _prepare_optimized_route(
        client, db, cipher, org_name=org_name
    )
    org_id = route.organization_id
    published = _publish(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=headers,
        version=route.version,
        idempotency_key=f"pub-{org_name}",
    )
    assert published.status_code == 200
    identity_service.set_current_organization_context(db, organization_id=org_id)
    db.expire_all()
    persisted = db.get(DailyRoute, route.id)
    assert persisted is not None
    stops = _stops(db, revision.id)
    snapshot_row = db.get(RouteRevision, revision.id)
    assert snapshot_row is not None
    frozen_snapshot = dict(snapshot_row.constraints_json["snapshot"])
    return persisted, org_id, stops, headers, frozen_snapshot


def test_report_completed_advances_route_and_keeps_snapshot(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, stops, headers, frozen_snapshot = _publish_ready(
        client, db_session, cipher, org_name="exec-ok"
    )
    route_version = route.version
    first, second, third = stops
    first_version = first.version
    second_version = second.version
    third_version = third.version

    first_report = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=first.id,
        headers=headers,
        version=first_version,
        body={"status": "completed"},
    )
    assert first_report.status_code == 200
    body = first_report.json()
    assert body["status"] == "completed"
    assert body["version"] == first_version + 1
    assert body["route_status"] == "in_progress"
    assert body["completed_at"]
    assert body["failure_reason"] is None
    assert first_report.headers["etag"] == f'"{first_version + 1}"'

    replay = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=first.id,
        headers=headers,
        version=body["version"],
        body={"status": "completed"},
    )
    assert replay.status_code == 200
    assert replay.json()["version"] == body["version"]

    skipped = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=second.id,
        headers=headers,
        version=second_version,
        body={"status": "skipped", "failure_reason": "ausente"},
    )
    assert skipped.status_code == 200
    last = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=third.id,
        headers=headers,
        version=third_version,
        body={"status": "failed", "failure_reason": "no abre"},
    )
    assert last.status_code == 200
    assert last.json()["route_status"] == "completed"
    assert last.json()["failure_reason"] == "no abre"

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    db_session.expire_all()
    persisted_route = db_session.get(DailyRoute, route.id)
    persisted_revision = db_session.get(RouteRevision, first.revision_id)
    assert persisted_route is not None
    assert persisted_revision is not None
    assert persisted_route.status == "completed"
    assert persisted_route.version == route_version
    assert persisted_revision.constraints_json["snapshot"] == frozen_snapshot
    persisted_stops = _stops(db_session, first.revision_id)
    assert [stop.status for stop in persisted_stops] == ["completed", "skipped", "failed"]
    assert persisted_stops[0].address_snapshot_ciphertext


def test_stale_if_match_returns_409_with_latest_state(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, stops, headers, _snapshot = _publish_ready(
        client, db_session, cipher, org_name="exec-409"
    )
    stop = stops[0]
    version_before = stop.version
    reported = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=stop.id,
        headers=headers,
        version=version_before,
        body={"status": "completed"},
    )
    assert reported.status_code == 200
    latest = reported.json()

    stale = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=stop.id,
        headers=headers,
        version=version_before,
        body={"status": "failed", "failure_reason": "duplicado"},
    )
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "STOP_VERSION_CONFLICT"
    assert body["errors"]
    state = body["errors"][0]
    assert state["code"] == "LATEST_STATE"
    assert state["id"] == str(stop.id)
    assert state["status"] == "completed"
    assert state["version"] == latest["version"]
    assert datetime.fromisoformat(state["completed_at"]) == datetime.fromisoformat(
        latest["completed_at"]
    )
    assert state["failure_reason"] is None
    assert state["route_status"] == "in_progress"


def test_field_assignee_can_report_other_field_forbidden(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, stops, _planner_headers, _snapshot = _publish_ready(
        client, db_session, cipher, org_name="exec-field"
    )
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    field_user = _create_user(db_session, organization=org, role="field", suffix="asg")
    other_field = _create_user(db_session, organization=org, role="field", suffix="oth")
    persisted = db_session.get(DailyRoute, route.id)
    assert persisted is not None
    persisted.assignee_id = field_user.id
    db_session.commit()

    stop = stops[0]
    stop_version = stop.version
    allowed = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=stop.id,
        headers={"Authorization": f"Bearer {_login(client, field_user)}"},
        version=stop_version,
        body={"status": "completed"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "completed"

    denied = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=stops[1].id,
        headers={"Authorization": f"Bearer {_login(client, other_field)}"},
        version=stops[1].version,
        body={"status": "completed"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN_ROLE"


def test_field_assignee_can_get_route_execution_fields(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, stops, _planner_headers, _snapshot = _publish_ready(
        client, db_session, cipher, org_name="exec-get"
    )
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    org = db_session.get(Organization, org_id)
    assert org is not None
    field_user = _create_user(db_session, organization=org, role="field", suffix="get")
    persisted = db_session.get(DailyRoute, route.id)
    assert persisted is not None
    persisted.assignee_id = field_user.id
    db_session.commit()

    headers = {"Authorization": f"Bearer {_login(client, field_user)}"}
    detail = _get_route(client, route_id=route.id, org_id=org_id, headers=headers)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "published"
    assert len(payload["stops"]) == 3
    first = payload["stops"][0]
    assert first["id"] == str(stops[0].id)
    assert first["status"] == "pending"
    assert first["version"] == 1
    assert first["external_ref"]
    assert first["lat"] is not None
    assert first["lon"] is not None

    other = _auth_headers(client, db_session, org_id=org_id, role="field")
    forbidden = _get_route(client, route_id=route.id, org_id=org_id, headers=other)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ROLE"


def test_unpublished_route_rejected(client: TestClient, db_session: Session) -> None:
    route, revision, stops, _metric = _seed_draft_route(db_session, org_name="exec-draft")
    headers = _planner_headers_for_assignee(client, db_session, route)
    response = _report(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        stop_id=stops[0].id,
        headers=headers,
        version=stops[0].version,
        body={"status": "completed"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ROUTE_NOT_EXECUTABLE"
    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    persisted = db_session.get(RouteStop, stops[0].id)
    assert persisted is not None
    assert persisted.status == "pending"
    assert revision.status == "draft"


def test_failed_requires_reason(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, stops, headers, _snapshot = _publish_ready(
        client, db_session, cipher, org_name="exec-reason"
    )
    response = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=stops[0].id,
        headers=headers,
        version=stops[0].version,
        body={"status": "failed"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_supervisor_cannot_report(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, stops, _headers, _snapshot = _publish_ready(
        client, db_session, cipher, org_name="exec-sup"
    )
    supervisor = _auth_headers(client, db_session, org_id=org_id, role="supervisor")
    response = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=stops[0].id,
        headers=supervisor,
        version=stops[0].version,
        body={"status": "completed"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ROLE"


def test_completed_at_from_payload(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, stops, headers, _snapshot = _publish_ready(
        client, db_session, cipher, org_name="exec-hora"
    )
    stamp = datetime(2026, 9, 18, 8, 30, tzinfo=UTC)
    response = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=stops[0].id,
        headers=headers,
        version=stops[0].version,
        body={"status": "completed", "completed_at": stamp.isoformat()},
    )
    assert response.status_code == 200
    assert response.json()["completed_at"].startswith("2026-09-18T08:30:00")
