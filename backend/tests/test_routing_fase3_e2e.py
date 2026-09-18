"""3.QA.2 — E2E HTTP: modificar paradas → reoptimizar → publicar → exportar.

Ref: RF-20, RF-21, RF-22. Une 3.BE.9 + 3.BE.11 + 3.BE.13 en un solo escenario.
Sin Playwright: pytest + testcontainers, FakeRouter.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.object_store.fake import InMemoryObjectStore
from app.adapters.router.fake import FakeRouter
from app.core.crypto import FieldCipher, KeyProvider
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.imports.deps import get_field_cipher, get_object_store
from app.modules.jobs.models import Job
from app.modules.planning.models import DailyRoute
from app.modules.routing.export import export_route_job
from app.modules.routing.models import RouteRevision, RouteStop
from app.modules.zoning.deps import get_router
from tests.test_routing_optimize_e2e import _body, _get_comparison, _post_optimize, _run_job
from tests.test_routing_publish_e2e import _prepare_optimized_route, _publish
from tests.test_routing_recalc_e2e import _put_stops


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
def object_store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture()
def client(
    db_session: Session, queue: JobQueue, cipher: FieldCipher, object_store: InMemoryObjectStore
) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    app.dependency_overrides[get_router] = lambda: FakeRouter()
    app.dependency_overrides[get_field_cipher] = lambda: cipher
    app.dependency_overrides[get_object_store] = lambda: object_store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_recalc_publish_and_export_three_formats(
    client: TestClient, db_session: Session, cipher: FieldCipher, object_store: InMemoryObjectStore
) -> None:
    route, planner, patients, first_revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="fase3-qa"
    )
    org_id = route.organization_id
    kept = [patients[0].id, patients[1].id]
    body = _body()

    replaced = _put_stops(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=headers,
        patient_ids=kept,
        version=route.version,
    )
    assert replaced.status_code == 200
    assert replaced.json()["metrics_pending"] is True

    stale_key = _post_optimize(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=headers,
        body=body,
        idempotency_key="opt-fase3-qa",
    )
    assert stale_key.status_code == 409
    assert stale_key.json()["code"] == "IDEMPOTENCY_KEY_REUSE"

    queued = _post_optimize(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=headers,
        body=body,
        idempotency_key="opt-fase3-qa-v2",
    )
    assert queued.status_code == 202
    second = _run_job(db_session, route, planner, body)
    assert second is not None
    assert second.id != first_revision.id
    assert second.status == "draft"
    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    db_session.expire_all()
    stops = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == second.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert {stop.patient_id for stop in stops} == set(kept)

    comparison = _get_comparison(client, route_id=route.id, org_id=org_id, headers=headers)
    assert comparison.status_code == 200
    savings = comparison.json()["savings"]
    assert "distance_m" in savings
    assert "travel_seconds" in savings

    refreshed = db_session.get(DailyRoute, route.id)
    assert refreshed is not None
    published = _publish(
        client,
        route_id=route.id,
        org_id=org_id,
        headers=headers,
        version=refreshed.version,
        idempotency_key="pub-fase3-qa",
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    published_revision_id = uuid.UUID(published.json()["revision_id"])
    frozen = db_session.get(RouteRevision, published_revision_id)
    assert frozen is not None
    assert frozen.status == "published"
    assert frozen.constraints_json["snapshot"]["geometry"]["type"] == "LineString"

    formats = ("navigation_link", "pdf", "png")
    for fmt in formats:
        posted = client.post(
            f"/api/v1/routes/{route.id}/exports",
            params={"organization_id": str(org_id)},
            json={"format": fmt},
            headers={**headers, "Idempotency-Key": f"exp-fase3-{fmt}"},
        )
        assert posted.status_code == 202, posted.text
        export_route_job(
            db_session,
            object_store,
            route_id=route.id,
            organization_id=org_id,
            revision_id=published_revision_id,
            format=fmt,
            job_id=uuid.UUID(posted.json()["job_id"]),
        )
        job = db_session.get(Job, uuid.UUID(posted.json()["job_id"]))
        assert job is not None
        assert job.status == "succeeded"
        if fmt == "navigation_link":
            url = job.result_json["navigation_url"]
            assert url.startswith("https://www.google.com/maps/dir/")
            for patient in patients:
                assert patient.display_ref not in url
                assert str(patient.id) not in url
            assert "Calle" not in url
            assert "Bilbao" not in url
        else:
            blob = object_store.get(key=job.result_json["object_key"])
            if fmt == "pdf":
                assert blob.startswith(b"%PDF")
                assert b"Calle Mayor" not in blob
            else:
                assert blob[:8] == b"\x89PNG\r\n\x1a\n"
            artifact = client.get(
                f"/api/v1/jobs/{job.id}/artifact",
                params={"organization_id": str(org_id)},
                headers=headers,
            )
            assert artifact.status_code == 200
            assert artifact.content[:4] == blob[:4]
