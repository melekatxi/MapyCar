"""GET /patients: listado de pacientes con dirección activa para el mapa operativo (1.FE.4)."""
from __future__ import annotations

import base64
import os
import uuid
from collections.abc import Iterator

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.object_store.fake import InMemoryObjectStore
from app.core.config import get_settings
from app.core.crypto import EnvKeyProvider, FieldCipher
from app.core.security import hash_password
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization, User, UserMembership
from app.modules.imports import service as imports_service
from app.modules.imports.deps import get_field_cipher, get_object_store

CSV_VALID = (
    b"id_paciente;nombre_referencia;direccion;codigo_postal;municipio;provincia\n"
    b"PAC-301;Paciente 301;Calle Mayor 1;48001;Bilbao;Bizkaia\n"
)


@pytest.fixture()
def cipher(monkeypatch: pytest.MonkeyPatch) -> Iterator[FieldCipher]:
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_ACTIVE_KEY_ID", "k1")
    monkeypatch.setenv("SOFIA_FIELD_ENCRYPTION_KEYS", f"k1:{key}")
    get_settings.cache_clear()
    try:
        yield FieldCipher(EnvKeyProvider())
    finally:
        get_settings.cache_clear()


@pytest.fixture()
def object_store() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture()
def queue() -> JobQueue:
    return JobQueue(fakeredis.FakeStrictRedis())


@pytest.fixture()
def client(
    db_session: Session, cipher: FieldCipher, object_store: InMemoryObjectStore, queue: JobQueue
) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_field_cipher] = lambda: cipher
    app.dependency_overrides[get_object_store] = lambda: object_store
    app.dependency_overrides[get_job_queue] = lambda: queue
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


def test_list_patients_returns_committed_patient_with_address_summary(
    client: TestClient, db_session: Session, cipher: FieldCipher, object_store: InMemoryObjectStore
) -> None:
    org = Organization(name="Org mapa")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}

    upload = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-11"},
        files={"file": ("dataset.csv", CSV_VALID, "text/csv")},
        headers={**headers, "Idempotency-Key": "patients-key-1"},
    )
    batch_id = upload.json()["batch_id"]
    imports_service.validate_import(
        db_session, object_store, cipher, batch_id=uuid.UUID(batch_id), organization_id=org.id
    )
    client.post(
        f"/api/v1/imports/{batch_id}/commit",
        params={"organization_id": str(org.id)},
        json={"accepted_row_numbers": [1]},
        headers={**headers, "Idempotency-Key": "patients-key-2"},
    )

    response = client.get("/api/v1/patients", params={"organization_id": str(org.id)}, headers=headers)

    assert response.status_code == 200
    patients = response.json()["patients"]
    assert len(patients) == 1
    assert patients[0]["external_ref"] == "PAC-301"
    assert patients[0]["geocode_status"] == "pending"
    assert patients[0]["latitude"] is None  # aún no geocodificada
    # RF-07 honest MVP: visit_status siempre pending hasta DailyRoute (Fase 2).
    assert patients[0]["visit_status"] == "pending"
    assert patients[0]["assigned_day"] is None
    assert patients[0]["assigned_zone"] is None
    assert patients[0]["zone_id"] is None


def test_list_patients_requires_organization_membership(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org ajena")
    other_org = Organization(name="Otra org")
    db_session.add_all([org, other_org])
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)

    response = client.get(
        "/api/v1/patients", params={"organization_id": str(other_org.id)}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403
