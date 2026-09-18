"""E2E de GET /history/routes: filtros combinados y paginación sobre snapshots.

Ref: 4.BE.1, RF-23, RF-24. El listado usa constraints_json.snapshot, no el paciente vivo.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

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
from app.modules.imports.deps import get_field_cipher
from app.modules.imports.models import Patient
from app.modules.planning.models import DailyRoute
from app.modules.routing.models import RouteRevision
from app.modules.zoning.deps import get_router
from app.modules.zoning.models import Zone
from tests.test_routing_order_e2e import _auth_headers
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


def _history(
    client: TestClient,
    *,
    org_id: uuid.UUID,
    headers: dict[str, str],
    **params: object,
):
    query = {"organization_id": str(org_id)}
    for key, value in params.items():
        if value is not None:
            query[key] = str(value)
    return client.get("/api/v1/history/routes", params=query, headers=headers)


def test_combined_filters_return_snapshot_not_live_patient(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, planner, patients, _revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="hist-ok"
    )
    org_id = route.organization_id
    published = _publish(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=headers,
        version=route.version,
        idempotency_key="pub-hist",
    )
    assert published.status_code == 200
    snapshot_ref = patients[0].external_ref

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    other_zone = Zone(organization_id=org_id, name="Otra zona", kind="rural")
    db_session.add(other_zone)
    db_session.flush()
    other_route = DailyRoute(
        organization_id=org_id,
        plan_id=route.plan_id,
        zone_id=other_zone.id,
        service_date=date(2026, 10, 1),
        assignee_id=planner.id,
        status="published",
    )
    db_session.add(other_route)
    db_session.flush()
    db_session.add(
        RouteRevision(
            organization_id=org_id,
            route_id=other_route.id,
            revision=1,
            status="published",
            published_at=datetime.now(UTC),
            created_by=planner.id,
            constraints_json={
                "snapshot": {
                    "objective": "time",
                    "order": [
                        {
                            "patient_id": str(patients[0].id),
                            "external_ref": "OPT-OTHER-1",
                            "sequence": 1,
                            "lat": 43.3,
                            "lon": -2.9,
                        }
                    ],
                }
            },
        )
    )
    live = db_session.get(Patient, patients[0].id)
    assert live is not None
    live.external_ref = "CHANGED-AFTER-PUBLISH"
    db_session.commit()

    hit = _history(
        client,
        org_id=org_id,
        headers=headers,
        **{
            "from": "2026-09-01",
            "to": "2026-09-30",
            "zone": route.zone_id,
            "assignee": planner.id,
            "patient_ref": snapshot_ref,
        },
    )
    assert hit.status_code == 200, hit.text
    items = hit.json()["items"]
    assert len(items) == 1
    assert items[0]["route_id"] == str(route.id)
    refs = {stop["external_ref"] for stop in items[0]["stops"]}
    assert snapshot_ref in refs
    assert all(stop["lat"] is not None for stop in items[0]["stops"])

    miss_live = _history(
        client,
        org_id=org_id,
        headers=headers,
        patient_ref="CHANGED-AFTER-PUBLISH",
    )
    assert miss_live.status_code == 200
    assert miss_live.json()["items"] == []

    miss_zone = _history(
        client,
        org_id=org_id,
        headers=headers,
        zone=other_zone.id,
        patient_ref=snapshot_ref,
    )
    assert miss_zone.json()["items"] == []


def test_history_pagination_and_field_scope(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, planner, _patients, _revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="hist-page"
    )
    org_id = route.organization_id
    first = _publish(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=headers,
        version=route.version,
        idempotency_key="pub-page-1",
    )
    assert first.status_code == 200

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    extra = DailyRoute(
        organization_id=org_id,
        plan_id=route.plan_id,
        zone_id=route.zone_id,
        service_date=date(2026, 9, 9),
        assignee_id=planner.id,
        status="published",
    )
    db_session.add(extra)
    db_session.flush()
    db_session.add(
        RouteRevision(
            organization_id=org_id,
            route_id=extra.id,
            revision=1,
            status="published",
            published_at=datetime.now(UTC) + timedelta(seconds=1),
            created_by=planner.id,
            constraints_json={"snapshot": {"order": []}},
        )
    )
    db_session.commit()

    page1 = _history(client, org_id=org_id, headers=headers, limit=1)
    assert page1.status_code == 200
    assert len(page1.json()["items"]) == 1
    cursor = page1.json()["next_cursor"]
    assert cursor
    page2 = _history(client, org_id=org_id, headers=headers, limit=1, cursor=cursor)
    assert page2.status_code == 200
    assert len(page2.json()["items"]) == 1
    assert page2.json()["items"][0]["route_id"] != page1.json()["items"][0]["route_id"]

    field_headers = _auth_headers(client, db_session, org_id=org_id, role="field")
    scoped = _history(client, org_id=org_id, headers=field_headers)
    assert scoped.status_code == 200
    assert scoped.json()["items"] == []

    forbidden = _history(
        client, org_id=org_id, headers=field_headers, assignee=planner.id
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ROLE"

    inverted = _history(
        client, org_id=org_id, headers=headers, **{"from": "2026-10-01", "to": "2026-09-01"}
    )
    assert inverted.status_code == 422
    assert inverted.json()["code"] == "DATE_RANGE_INVALID"
