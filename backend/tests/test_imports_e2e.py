"""E2E de importación: subir, validar (worker), listar filas, corregir y confirmar.

Ref: 1.BE.1 a 1.BE.7, diseño sección 7.1/8.3.
"""
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
from app.core.crypto import EnvKeyProvider, FieldCipher
from app.core.security import hash_password
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization, User, UserMembership
from app.modules.imports import service as imports_service
from app.modules.imports.deps import get_field_cipher, get_object_store
from tests.xls_fixture import build_xls

CSV_VALID = (
    "id_paciente;nombre_referencia;direccion;codigo_postal;municipio;provincia\n"
    "PAC-001;Paciente 001;Calle Mayor 1;48001;Bilbao;Bizkaia\n"
    "PAC-002;Paciente 002;Calle Mayor 2, 3º;48009;Bilbao;Bizkaia\n"
).encode()


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


def _run_worker_once(queue: JobQueue, db: Session, object_store: InMemoryObjectStore, cipher: FieldCipher) -> None:
    def handler(payload: dict) -> None:
        imports_service.validate_import(
            db,
            object_store,
            cipher,
            batch_id=uuid.UUID(payload["batch_id"]),
            organization_id=uuid.UUID(payload["organization_id"]),
        )

    result = queue.run_once(queue="imports", handler=handler)
    assert result is not None
    assert result.status == "succeeded"


def test_upload_valid_file_returns_202_with_job_id(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org importadora")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)

    response = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-08"},
        files={"file": ("dataset.csv", CSV_VALID, "text/csv")},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "key-1"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["batch_id"]
    assert body["job_id"]


def _xls_bytes() -> bytes:
    return build_xls(
        [
            [
                "id_paciente",
                "nombre_referencia",
                "direccion",
                "codigo_postal",
                "municipio",
                "provincia",
            ],
            ["PAC-004", "Paciente 004", "Calle Mayor 4", "48001", "Bilbao", "Bizkaia"],
        ]
    )


def test_upload_with_fake_xlsx_signature_returns_415(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org importadora 2")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)

    response = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-08"},
        files={"file": ("dataset.xlsx", b"no es un xlsx real", "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "key-2"},
    )

    assert response.status_code == 415
    assert response.json()["code"] == "INVALID_FILE_SIGNATURE"


def test_upload_with_fake_xls_signature_returns_415(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org importadora xls firma")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)

    response = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-08"},
        files={"file": ("dataset.xls", b"no es un xls real", "application/vnd.ms-excel")},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "key-xls-fake"},
    )

    assert response.status_code == 415
    assert response.json()["code"] == "INVALID_FILE_SIGNATURE"


def test_upload_valid_xls_returns_202(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org importadora xls")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)

    response = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-08"},
        files={"file": ("dataset.xls", _xls_bytes(), "application/vnd.ms-excel")},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "key-xls-ok"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "uploaded"
    assert response.json()["batch_id"]


def test_reuploading_same_file_and_period_returns_409(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org importadora 3")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}

    first = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-08"},
        files={"file": ("dataset.csv", CSV_VALID, "text/csv")},
        headers={**headers, "Idempotency-Key": "key-3"},
    )
    assert first.status_code == 202

    second = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-08"},
        files={"file": ("dataset.csv", CSV_VALID, "text/csv")},
        headers={**headers, "Idempotency-Key": "key-4"},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "IMPORT_DUPLICATE"


def test_missing_idempotency_key_returns_400(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org importadora 4")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)

    response = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-08"},
        files={"file": ("dataset.csv", CSV_VALID, "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_full_flow_validate_correct_and_commit(
    client: TestClient,
    db_session: Session,
    cipher: FieldCipher,
    object_store: InMemoryObjectStore,
    queue: JobQueue,
) -> None:
    org = Organization(name="Org importadora 5")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}

    csv_with_one_bad_row = (
        b"id_paciente;nombre_referencia;direccion;codigo_postal;municipio;provincia\n"
        b"PAC-101;Paciente 101;Calle Mayor 1;48001;Bilbao;Bizkaia\n"
        b"PAC-102;Paciente 102;Calle Mayor 2;BADCP;Bilbao;Bizkaia\n"
    )

    upload = client.post(
        "/api/v1/imports",
        data={"organization_id": str(org.id), "period": "2026-09"},
        files={"file": ("dataset.csv", csv_with_one_bad_row, "text/csv")},
        headers={**headers, "Idempotency-Key": "key-5"},
    )
    assert upload.status_code == 202
    batch_id = upload.json()["batch_id"]

    _run_worker_once(queue, db_session, object_store, cipher)

    get_response = client.get(
        f"/api/v1/imports/{batch_id}", params={"organization_id": str(org.id)}, headers=headers
    )
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "requires_correction"
    assert get_response.json()["counts_json"] == {"total": 2, "valid": 1, "invalid": 1}

    rows_response = client.get(
        f"/api/v1/imports/{batch_id}/rows", params={"organization_id": str(org.id)}, headers=headers
    )
    assert rows_response.status_code == 200
    rows = rows_response.json()["rows"]
    invalid_row = next(r for r in rows if r["validation_status"] == "invalid")
    assert invalid_row["errors"][0]["field"] == "codigo_postal"

    correction = client.patch(
        f"/api/v1/imports/{batch_id}/rows/{invalid_row['row_number']}",
        params={"organization_id": str(org.id)},
        json={"fields": {"codigo_postal": "48009"}},
        headers=headers,
    )
    assert correction.status_code == 200
    assert correction.json()["validation_status"] == "corrected"

    commit = client.post(
        f"/api/v1/imports/{batch_id}/commit",
        params={"organization_id": str(org.id)},
        json={"accepted_row_numbers": [1, 2]},
        headers={**headers, "Idempotency-Key": "key-6"},
    )
    assert commit.status_code == 200
    assert commit.json() == {"committed_patients": 2, "skipped_rows": 0}
