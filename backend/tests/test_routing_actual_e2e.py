"""E2E de GET /routes/{id}/comparison con variant=actual y desviación.

Ref: 4.BE.3, RF-25, diseño 6.1 / 7.6. Plan = métricas optimized publicadas.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

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
from app.modules.planning.models import DailyRoute
from app.modules.routing.models import RouteMetric, RouteRevision
from app.modules.zoning.deps import get_router
from tests.test_routing_execution_e2e import _publish_ready, _report
from tests.test_routing_optimize_e2e import _get_comparison


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


def test_comparison_without_execution_has_no_actual(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, _stops, headers, _snapshot = _publish_ready(
        client, db_session, cipher, org_name="act-empty"
    )
    response = _get_comparison(client, route_id=route.id, org_id=org_id, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["actual"] is None
    assert body["deviation"] is None
    assert body["execution_counts"] is None
    assert body["optimized"]["travel_seconds"] > 0


def test_comparison_returns_actual_deviation_after_reports(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, stops, headers, frozen_snapshot = _publish_ready(
        client, db_session, cipher, org_name="act-ok"
    )
    before = _get_comparison(client, route_id=route.id, org_id=org_id, headers=headers)
    assert before.status_code == 200
    planned = before.json()["optimized"]

    t0 = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    stamps = [t0, t0 + timedelta(hours=1, minutes=30), t0 + timedelta(hours=3)]
    versions = [stop.version for stop in stops]
    for stop, stamp, version in zip(stops, stamps, versions, strict=True):
        reported = _report(
            client,
            route_id=route.id,
            org_id=org_id,
            stop_id=stop.id,
            headers=headers,
            version=version,
            body={"status": "completed", "completed_at": stamp.isoformat()},
        )
        assert reported.status_code == 200

    response = _get_comparison(client, route_id=route.id, org_id=org_id, headers=headers)
    assert response.status_code == 200
    body = response.json()
    service_seconds = sum(int(stop.service_minutes or 0) * 60 for stop in stops)
    elapsed = int((stamps[-1] - stamps[0]).total_seconds())
    travel_seconds = max(0, elapsed - service_seconds)
    assert body["actual"]["service_seconds"] == service_seconds
    assert body["actual"]["travel_seconds"] == travel_seconds
    assert body["actual"]["distance_m"] == 0
    assert body["execution_counts"] == {
        "planned": 3,
        "completed": 3,
        "failed": 0,
        "skipped": 0,
        "pending": 0,
    }
    deviation = body["deviation"]
    assert deviation["distance_m"] == 0
    assert deviation["travel_seconds"] == travel_seconds - planned["travel_seconds"]
    assert deviation["estimated_cost"] == pytest.approx(
        body["actual"]["estimated_cost"] - planned["estimated_cost"]
    )
    if planned["travel_seconds"] == 0:
        assert deviation["travel_seconds_pct"] == 0.0
    else:
        expected_pct = round(
            (travel_seconds - planned["travel_seconds"]) / planned["travel_seconds"] * 100, 2
        )
        assert deviation["travel_seconds_pct"] == pytest.approx(expected_pct)

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    db_session.expire_all()
    actual_row = (
        db_session.query(RouteMetric)
        .filter(RouteMetric.revision_id == stops[0].revision_id, RouteMetric.variant == "actual")
        .one()
    )
    assert actual_row.calculation_json["source"] == "reported"
    assert actual_row.calculation_json["distance_source"] == "unavailable"
    revision = db_session.get(RouteRevision, stops[0].revision_id)
    assert revision is not None
    assert revision.constraints_json["snapshot"] == frozen_snapshot
    persisted = db_session.get(DailyRoute, route.id)
    assert persisted is not None
    assert persisted.status == "completed"


def test_partial_execution_counts_pending(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, org_id, stops, headers, _snapshot = _publish_ready(
        client, db_session, cipher, org_name="act-part"
    )
    first = stops[0]
    stamp = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    reported = _report(
        client,
        route_id=route.id,
        org_id=org_id,
        stop_id=first.id,
        headers=headers,
        version=first.version,
        body={"status": "failed", "failure_reason": "no abre", "completed_at": stamp.isoformat()},
    )
    assert reported.status_code == 200
    response = _get_comparison(client, route_id=route.id, org_id=org_id, headers=headers)
    assert response.status_code == 200
    counts = response.json()["execution_counts"]
    assert counts["completed"] == 0
    assert counts["failed"] == 1
    assert counts["pending"] == 2
    assert counts["planned"] == 3
    assert response.json()["actual"]["service_seconds"] == 0
    assert response.json()["actual"]["travel_seconds"] == 0
