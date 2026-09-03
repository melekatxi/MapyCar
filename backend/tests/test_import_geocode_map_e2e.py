"""1.QA.1 — E2E HTTP: importar → corregir → geocodificar → ver en mapa.

Recorre el camino de un miembro de la organización (rol planner):
POST /imports → worker validate → PATCH fila inválida → POST commit → POST geocode
→ worker geocode (Nominatim sustituido por FakeGeocoder) → GET /patients (payload del mapa).

Dataset: recorte de `docs/requisitos/direcciones-ejemplo-bizkaia.csv` (3 filas, PII ficticio).
No se suben las ~500 filas del fixture en CI.

Diferido (Fase 2/4): el criterio 1.FE.6 «un usuario `field` solo ve las rutas asignadas»
no es comprobable aquí — DailyRoute/ShareGrant no existen. RF-07 estados
planificada/completada tampoco. Este escenario cubre «un miembro de la org importa,
corrige, geocodifica y ve el punto en el payload del mapa operativo».
"""

from __future__ import annotations

import asyncio
import base64
import csv
import io
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.geocoder.fake import FakeGeocoder
from app.adapters.geocoder.interface import GeocodeCandidate, Geocoder
from app.adapters.object_store.fake import InMemoryObjectStore
from app.core.config import get_settings
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

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = REPO_ROOT / "docs" / "requisitos" / "direcciones-ejemplo-bizkaia.csv"
SLICE_SIZE = 3
CORRUPT_ROW_NUMBER = 2

# Coordenadas ficticias dentro de Bizkaia (bbox ADR-07); no son un geocode real.
BIZKAIA_COORDS: dict[str, tuple[float, float]] = {
    "Bilbao": (43.2630, -2.9349),
    "Erandio": (43.3074, -2.9732),
    "Getxo": (43.3438, -3.0078),
}


class QueryAwareFakeGeocoder(FakeGeocoder):
    """Doble de Nominatim: un candidato `building` alineado con CP/municipio de la consulta."""

    async def geocode(
        self, *, address_text: str, postal_code: str | None, municipality: str | None
    ) -> list[GeocodeCandidate]:
        self.calls.append(address_text)
        lat, lon = BIZKAIA_COORDS.get(municipality or "", (43.24, -2.92))
        return [
            GeocodeCandidate(
                latitude=lat,
                longitude=lon,
                display_label=f"{address_text}, {municipality}",
                score=0.92,
                place_class="building",
                postal_code=postal_code,
                municipality=municipality,
                house_number="1",
            )
        ]


def _load_bizkaia_slice(*, corrupt_row: int = CORRUPT_ROW_NUMBER) -> tuple[bytes, str, list[str]]:
    """Devuelve (csv_bytes, cp_original_de_la_fila_corrupta, refs_externas)."""
    text = DATASET_PATH.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    fieldnames = list(reader.fieldnames or [])
    rows = list(reader)[:SLICE_SIZE]
    assert len(rows) == SLICE_SIZE, f"El dataset de Bizkaia no tiene {SLICE_SIZE} filas"
    refs = [str(row["id_paciente"]) for row in rows]
    original_cp = str(rows[corrupt_row - 1]["codigo_postal"])
    rows[corrupt_row - 1]["codigo_postal"] = "XXXXX"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8"), original_cp, refs


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
def geocoder() -> Geocoder:
    return QueryAwareFakeGeocoder()


@pytest.fixture()
def geocode_cache() -> GeocodeCache:
    return GeocodeCache(fakeredis.FakeStrictRedis())


@pytest.fixture()
def client(
    db_session: Session,
    cipher: FieldCipher,
    object_store: InMemoryObjectStore,
    queue: JobQueue,
    geocoder: Geocoder,
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


def _create_org_member(db: Session, *, organization: Organization, role: str = "planner") -> User:
    user = User(
        email_normalized=f"{role}-{uuid.uuid4().hex[:8]}@bizkaia.example",
        display_name="Planificadora de prueba",
        password_hash=hash_password("Sup3rSecreta!"),
    )
    db.add(user)
    db.flush()
    identity_service.set_current_organization_context(db, organization_id=organization.id)
    db.add(UserMembership(organization_id=organization.id, user_id=user.id, role=role))
    db.commit()
    return user


def _login(client: TestClient, user: User) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"email": user.email_normalized, "password": "Sup3rSecreta!"}
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _run_validate_worker(
    queue: JobQueue, db: Session, object_store: InMemoryObjectStore, cipher: FieldCipher
) -> None:
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
    assert result.status == "succeeded", result.error_code


def _run_geocode_worker(
    queue: JobQueue,
    db: Session,
    geocoder: Geocoder,
    geocode_cache: GeocodeCache,
    cipher: FieldCipher,
) -> dict[str, int]:
    counts: dict[str, int] = {}

    def handler(payload: dict) -> None:
        identity_service.set_current_organization_context(
            db, organization_id=uuid.UUID(payload["organization_id"])
        )
        counts.update(
            asyncio.run(
                geocoding_service.geocode_eligible_addresses_for_batch(
                    db,
                    geocoder,
                    geocode_cache,
                    cipher,
                    batch_id=uuid.UUID(payload["batch_id"]),
                )
            )
        )

    result = queue.run_once(queue="geocoding", handler=handler)
    assert result is not None
    assert result.status == "succeeded"
    return counts


def test_org_member_imports_corrects_geocodes_and_sees_points_on_map_payload(
    client: TestClient,
    db_session: Session,
    cipher: FieldCipher,
    object_store: InMemoryObjectStore,
    queue: JobQueue,
    geocoder: Geocoder,
    geocode_cache: GeocodeCache,
) -> None:
    csv_bytes, original_cp, expected_refs = _load_bizkaia_slice()
    org = Organization(name="Org Bizkaia QA1")
    db_session.add(org)
    db_session.commit()
    user = _create_org_member(db_session, organization=org, role="planner")
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}
    org_id = str(org.id)

    upload = client.post(
        "/api/v1/imports",
        data={"organization_id": org_id, "period": "2026-08"},
        files={"file": ("direcciones-ejemplo-bizkaia.csv", csv_bytes, "text/csv")},
        headers={**headers, "Idempotency-Key": "qa1-import"},
    )
    assert upload.status_code == 202
    batch_id = upload.json()["batch_id"]

    _run_validate_worker(queue, db_session, object_store, cipher)

    batch = client.get(
        f"/api/v1/imports/{batch_id}", params={"organization_id": org_id}, headers=headers
    )
    assert batch.status_code == 200
    assert batch.json()["status"] == "requires_correction"
    assert batch.json()["counts_json"] == {"total": SLICE_SIZE, "valid": SLICE_SIZE - 1, "invalid": 1}

    rows = client.get(
        f"/api/v1/imports/{batch_id}/rows", params={"organization_id": org_id}, headers=headers
    )
    assert rows.status_code == 200
    invalid_row = next(r for r in rows.json()["rows"] if r["validation_status"] == "invalid")
    assert invalid_row["row_number"] == CORRUPT_ROW_NUMBER
    assert invalid_row["errors"][0]["field"] == "codigo_postal"

    correction = client.patch(
        f"/api/v1/imports/{batch_id}/rows/{invalid_row['row_number']}",
        params={"organization_id": org_id},
        json={"fields": {"codigo_postal": original_cp}},
        headers=headers,
    )
    assert correction.status_code == 200
    assert correction.json()["validation_status"] == "corrected"

    commit = client.post(
        f"/api/v1/imports/{batch_id}/commit",
        params={"organization_id": org_id},
        json={"accepted_row_numbers": list(range(1, SLICE_SIZE + 1))},
        headers={**headers, "Idempotency-Key": "qa1-commit"},
    )
    assert commit.status_code == 200
    assert commit.json() == {"committed_patients": SLICE_SIZE, "skipped_rows": 0}

    geocode = client.post(
        f"/api/v1/imports/{batch_id}/geocode",
        params={"organization_id": org_id},
        headers=headers,
    )
    assert geocode.status_code == 202
    assert geocode.json()["status"] == "queued"

    counts = _run_geocode_worker(queue, db_session, geocoder, geocode_cache, cipher)
    assert counts["matched"] == SLICE_SIZE
    assert counts.get("ambiguous", 0) == 0
    assert counts.get("not_found", 0) == 0

    map_payload = client.get("/api/v1/patients", params={"organization_id": org_id}, headers=headers)
    assert map_payload.status_code == 200
    patients = map_payload.json()["patients"]
    assert {p["external_ref"] for p in patients} == set(expected_refs)
    for patient in patients:
        assert patient["geocode_status"] == "matched"
        assert patient["visit_status"] == "pending"
        assert patient["assigned_day"] is None
        assert patient["assigned_zone"] is None
        assert patient["latitude"] is not None
        assert patient["longitude"] is not None
        assert patient["province"] == "Bizkaia"
        expected_lat, expected_lon = BIZKAIA_COORDS[patient["municipality"]]
        assert patient["latitude"] == pytest.approx(expected_lat, abs=1e-4)
        assert patient["longitude"] == pytest.approx(expected_lon, abs=1e-4)
        # Minimización ADR-09: la referencia operativa, nunca un nombre real.
        assert patient["display_ref"].startswith("Paciente ")
