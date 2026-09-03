"""E2E de geocodificación vía API: encolar, listar candidatos y confirmar selección.

Ref: 1.BE.11, 1.BE.12, diseño sección 8.3.
"""
from __future__ import annotations

import asyncio
import base64
import os
import uuid
from collections.abc import Iterator

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.geocoder.fake import FakeGeocoder
from app.adapters.geocoder.interface import GeocodeCandidate
from app.adapters.object_store.fake import InMemoryObjectStore
from app.core.crypto import EnvKeyProvider, FieldCipher
from app.core.security import hash_password
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.geocoding import service as geocoding_service
from app.modules.geocoding.cache import GeocodeCache
from app.modules.geocoding.deps import get_geocode_cache, get_geocoder
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization, User, UserMembership
from app.modules.imports import service as imports_service
from app.modules.imports.deps import get_field_cipher, get_object_store
from app.modules.imports.models import Address

CSV_ONE_ROW = (
    "id_paciente;nombre_referencia;direccion;codigo_postal;municipio;provincia\n"
    "PAC-201;Paciente 201;Calle Mayor 1, 3º;48001;Bilbao;Bizkaia\n"
).encode()

MATCHED_CANDIDATE = GeocodeCandidate(
    latitude=43.263,
    longitude=-2.935,
    display_label="Calle Mayor 1, Bilbao",
    score=0.8,
    place_class="building",
    postal_code="48001",
    municipality="Bilbao",
    house_number="1",
)


@pytest.fixture()
def cipher(monkeypatch: pytest.MonkeyPatch) -> FieldCipher:
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_ACTIVE_KEY_ID", "k1")
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_KEYS", f"k1:{key}")
    return FieldCipher(EnvKeyProvider())


@pytest.fixture()
def object_store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture()
def queue() -> JobQueue:
    return JobQueue(fakeredis.FakeStrictRedis())


@pytest.fixture()
def geocoder() -> FakeGeocoder:
    return FakeGeocoder([MATCHED_CANDIDATE])


@pytest.fixture()
def geocode_cache() -> GeocodeCache:
    return GeocodeCache(fakeredis.FakeStrictRedis())


@pytest.fixture()
def client(
    db_session: Session,
    cipher: FieldCipher,
    object_store: InMemoryObjectStore,
    queue: JobQueue,
    geocoder: FakeGeocoder,
    geocode_cache: GeocodeCache,
) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_field_cipher] = lambda: cipher
    app.dependency_overrides[get_object_store] = lambda: object_store
    app.dependency_overrides[get_job_queue] = lambda: queue
    app.dependency_overrides[get_geocoder] = lambda: geocoder
    app.dependency_overrides[get_geocode_cache] = lambda: geocode_cache
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _create_planner(db: Session, *, organization: Organization) -> User:
    user = User(
        email_normalized=f"planner-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Planificadora",
        password_hash=hash_password("Sup3rSecreta!"),
    )
    db.add(user)
    db.flush()
    identity_service.set_current_organization_context(db, organization_id=organization.id)
    db.add(UserMembership(organization_id=organization.id, user_id=user.id, role="planner"))
    db.commit()
    return user


def _login(client: TestClient, user: User) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email_normalized, "password": "Sup3rSecreta!"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_geocode_batch_then_confirm_selection(
    client: TestClient,
    db_session: Session,
    cipher: FieldCipher,
    object_store: InMemoryObjectStore,
    queue: JobQueue,
    geocoder: FakeGeocoder,
    geocode_cache: GeocodeCache,
) -> None:
    org = Organization(name="Org geocoding e2e")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}

    upload = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-10"},
        files={"file": ("dataset.csv", CSV_ONE_ROW, "text/csv")},
        headers={**headers, "Idempotency-Key": "geo-key-1"},
    )
    assert upload.status_code == 202
    batch_id = upload.json()["batch_id"]

    imports_service.validate_import(
        db_session, object_store, cipher, batch_id=uuid.UUID(batch_id), organization_id=org.id
    )
    commit = client.post(
        f"/api/v1/imports/{batch_id}/commit",
        params={"organization_id": str(org.id)},
        json={"accepted_row_numbers": [1]},
        headers={**headers, "Idempotency-Key": "geo-key-2"},
    )
    assert commit.status_code == 200

    geocode_response = client.post(
        f"/api/v1/imports/{batch_id}/geocode", params={"organization_id": str(org.id)}, headers=headers
    )
    assert geocode_response.status_code == 202

    counts = asyncio.run(
        geocoding_service.geocode_eligible_addresses_for_batch(
            db_session, geocoder, geocode_cache, cipher, batch_id=uuid.UUID(batch_id)
        )
    )
    assert counts == {"matched": 1, "ambiguous": 0, "not_found": 0}

    address = db_session.query(Address).one()

    candidates_response = client.get(
        f"/api/v1/addresses/{address.id}/candidates", params={"organization_id": str(org.id)}, headers=headers
    )
    assert candidates_response.status_code == 200
    body = candidates_response.json()
    assert body["geocode_status"] == "matched"
    assert len(body["candidates"]) == 1

    selection = client.post(
        f"/api/v1/addresses/{address.id}/geocode-selection",
        params={"organization_id": str(org.id)},
        json={"candidate_index": 0, "reason": "Confirmado por el planificador"},
        headers=headers,
    )
    assert selection.status_code == 200
    assert selection.json()["geocode_status"] == "manual"
