"""E2E de POST /routes/{id}/exports: PDF, PNG y enlace sin PII. Ref: 3.BE.13, RF-22."""

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
from app.jobs.worker import HANDLERS
from app.main import app
from app.modules.imports.deps import get_field_cipher, get_object_store
from app.modules.jobs.models import Job
from app.modules.routing.export import export_route_job
from app.modules.zoning.deps import get_router
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
def object_store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture()
def client(
    db_session: Session, queue: JobQueue, cipher, object_store: InMemoryObjectStore
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


def _export(
    client: TestClient,
    *,
    route_id,
    org_id,
    headers: dict[str, str],
    fmt: str,
    idempotency_key: str,
):
    return client.post(
        f"/api/v1/routes/{route_id}/exports",
        params={"organization_id": str(org_id)},
        json={"format": fmt},
        headers={**headers, "Idempotency-Key": idempotency_key},
    )


def test_worker_registers_exports_handler() -> None:
    assert "exports" in HANDLERS


def test_three_formats_without_patient_data_in_navigation_link(
    client: TestClient, db_session: Session, cipher, object_store: InMemoryObjectStore, queue: JobQueue
) -> None:
    route, _planner, patients, revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="exp-ok"
    )
    published = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=route.version,
        idempotency_key="pub-exp",
    )
    assert published.status_code == 200

    nav = _export(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        fmt="navigation_link",
        idempotency_key="exp-nav",
    )
    assert nav.status_code == 202
    export_route_job(
        db_session,
        object_store,
        route_id=route.id,
        organization_id=route.organization_id,
        revision_id=revision.id,
        format="navigation_link",
        job_id=uuid.UUID(nav.json()["job_id"]),
    )
    job = db_session.get(Job, uuid.UUID(nav.json()["job_id"]))
    assert job is not None
    url = job.result_json["navigation_url"]
    assert url.startswith("https://www.google.com/maps/dir/")
    for patient in patients:
        assert patient.display_ref not in url
        assert str(patient.id) not in url
    assert "Calle" not in url
    assert "Bilbao" not in url

    pdf_res = _export(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        fmt="pdf",
        idempotency_key="exp-pdf",
    )
    assert pdf_res.status_code == 202
    export_route_job(
        db_session,
        object_store,
        route_id=route.id,
        organization_id=route.organization_id,
        revision_id=revision.id,
        format="pdf",
        job_id=uuid.UUID(pdf_res.json()["job_id"]),
    )
    pdf_job = db_session.get(Job, uuid.UUID(pdf_res.json()["job_id"]))
    assert pdf_job is not None
    pdf_bytes = object_store.get(key=pdf_job.result_json["object_key"])
    assert pdf_bytes.startswith(b"%PDF")
    assert b"Calle Mayor" not in pdf_bytes

    artifact = client.get(
        f"/api/v1/jobs/{pdf_res.json()['job_id']}/artifact",
        params={"organization_id": str(route.organization_id)},
        headers=headers,
    )
    assert artifact.status_code == 200
    assert artifact.content.startswith(b"%PDF")
    assert "attachment" in artifact.headers.get("content-disposition", "")

    png_res = _export(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        fmt="png",
        idempotency_key="exp-png",
    )
    assert png_res.status_code == 202
    export_route_job(
        db_session,
        object_store,
        route_id=route.id,
        organization_id=route.organization_id,
        revision_id=revision.id,
        format="png",
        job_id=uuid.UUID(png_res.json()["job_id"]),
    )
    png_job = db_session.get(Job, uuid.UUID(png_res.json()["job_id"]))
    assert png_job is not None
    png_bytes = object_store.get(key=png_job.result_json["object_key"])
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_export_unpublished_and_field_role_rejected(
    client: TestClient, db_session: Session, cipher
) -> None:
    route, _planner, _patients, _revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="exp-draft"
    )
    draft = _export(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        fmt="pdf",
        idempotency_key="exp-draft",
    )
    assert draft.status_code == 409
    assert draft.json()["code"] == "REVISION_NOT_PUBLISHED"

    published_route, _p, _pts, _rev, pub_headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="exp-field"
    )
    published = _publish(
        client,
        route_id=published_route.id,
        org_id=published_route.organization_id,
        headers=pub_headers,
        version=published_route.version,
        idempotency_key="pub-field-exp",
    )
    assert published.status_code == 200
    field_headers = _auth_headers(
        client, db_session, org_id=published_route.organization_id, role="field"
    )
    forbidden = _export(
        client,
        route_id=published_route.id,
        org_id=published_route.organization_id,
        headers=field_headers,
        fmt="png",
        idempotency_key="exp-field",
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ROLE"
