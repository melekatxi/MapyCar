"""E2E de zonas persistidas: CRUD, If-Match y override manual que sobrevive a accept.

Ref: 2.BE.6, RF-10, diseño sección 8.4.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from math import ceil

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.router.fake import FakeRouter
from app.core.security import hash_password
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization, User, UserMembership
from app.modules.imports.models import Address, Patient
from app.modules.zoning import service as zoning_service
from app.modules.zoning.models import ZoneAssignment

_BILBAO_LON = -2.9348
_BILBAO_LAT = 43.2630


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


def _create_planner(db: Session, *, organization: Organization, suffix: str = "") -> User:
    user = User(
        email_normalized=f"planner-z-{suffix}{uuid.uuid4().hex[:8]}@example.com",
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


def _point(lon: float, lat: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


def _urban_coords(n: int) -> list[tuple[float, float]]:
    step = 0.0006
    cols = max(1, ceil(n**0.5))
    return [
        (_BILBAO_LON + (index % cols) * step, _BILBAO_LAT + (index // cols) * step)
        for index in range(n)
    ]


def _seed_address(
    db: Session,
    *,
    organization: Organization,
    external_ref: str,
    lon: float | None,
    lat: float | None,
    geocode_status: str,
    municipality: str = "Bilbao",
    postal_code: str = "48001",
) -> Patient:
    identity_service.set_current_organization_context(db, organization_id=organization.id)
    patient = Patient(
        organization_id=organization.id,
        external_ref=external_ref,
        display_ref=external_ref,
    )
    db.add(patient)
    db.flush()
    db.add(
        Address(
            organization_id=organization.id,
            patient_id=patient.id,
            address_ciphertext="enc",
            postal_code=postal_code,
            municipality=municipality,
            province="Bizkaia",
            location=_point(lon, lat) if lon is not None and lat is not None else None,
            geocode_status=geocode_status,
            is_active=True,
        )
    )
    db.commit()
    return patient


def _handler_for(db: Session) -> Callable[[dict], None]:
    def handler(payload: dict) -> None:
        zoning_service.run_zone_proposal(
            db,
            proposal_id=uuid.UUID(payload["proposal_id"]),
            organization_id=uuid.UUID(payload["organization_id"]),
            router=FakeRouter(),
        )

    return handler


def _auth(client: TestClient, db: Session) -> tuple[Organization, dict[str, str]]:
    org = Organization(name=f"Org zones {uuid.uuid4().hex[:8]}")
    db.add(org)
    db.commit()
    user = _create_planner(db, organization=org)
    token = _login(client, user)
    return org, {"Authorization": f"Bearer {token}"}


def _run_proposal(
    client: TestClient,
    queue: JobQueue,
    db: Session,
    *,
    org: Organization,
    headers: dict[str, str],
    max_visits: int = 5,
    target_zones: int = 4,
) -> str:
    created = client.post(
        "/api/v1/zone-proposals",
        json={
            "organization_id": str(org.id),
            "max_visits": max_visits,
            "target_zones": target_zones,
        },
        headers=headers,
    )
    assert created.status_code == 202
    proposal_id = created.json()["id"]
    result = queue.run_once(queue="zoning", handler=_handler_for(db))
    assert result is not None
    assert result.status == "succeeded"
    fetched = client.get(
        f"/api/v1/zone-proposals/{proposal_id}",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "succeeded"
    return proposal_id


def _assignment_for(
    client: TestClient, *, org_id: uuid.UUID, zone_id: str, patient_id: str, headers: dict[str, str]
) -> dict | None:
    fetched = client.get(
        f"/api/v1/zones/{zone_id}",
        params={"organization_id": str(org_id)},
        headers=headers,
    )
    assert fetched.status_code == 200
    for item in fetched.json()["assignments"]:
        if item["patient_id"] == patient_id:
            return item
    return None


def test_post_zone_patch_if_match_and_stale_409(client: TestClient, db_session: Session) -> None:
    org, headers = _auth(client, db_session)
    created = client.post(
        "/api/v1/zones",
        json={
            "organization_id": str(org.id),
            "name": "Norte",
            "kind": "urban",
            "max_visits": 8,
            "centroid": {"lon": _BILBAO_LON, "lat": _BILBAO_LAT},
        },
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Norte"
    assert body["version"] == 1
    assert body["assignments"] == []
    assert created.headers["etag"] == '"1"'
    zone_id = body["id"]

    missing = client.patch(
        f"/api/v1/zones/{zone_id}",
        params={"organization_id": str(org.id)},
        json={"name": "Norte 2"},
        headers=headers,
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "IF_MATCH_REQUIRED"

    stale = client.patch(
        f"/api/v1/zones/{zone_id}",
        params={"organization_id": str(org.id)},
        json={"name": "Norte 2"},
        headers={**headers, "If-Match": '"0"'},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "ZONE_VERSION_CONFLICT"

    patched = client.patch(
        f"/api/v1/zones/{zone_id}",
        params={"organization_id": str(org.id)},
        json={"name": "Norte actualizada", "kind": "mixed"},
        headers={**headers, "If-Match": "1"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Norte actualizada"
    assert patched.json()["kind"] == "mixed"
    assert patched.json()["version"] == 2
    assert patched.headers["etag"] == '"2"'


def test_post_zone_duplicate_name_409(client: TestClient, db_session: Session) -> None:
    org, headers = _auth(client, db_session)
    payload = {
        "organization_id": str(org.id),
        "name": "Duplicada",
        "kind": "rural",
        "max_visits": 4,
    }
    first = client.post("/api/v1/zones", json=payload, headers=headers)
    assert first.status_code == 201
    second = client.post("/api/v1/zones", json=payload, headers=headers)
    assert second.status_code == 409
    assert second.json()["code"] == "ZONE_NAME_CONFLICT"


def test_put_override_if_match_and_capacity(client: TestClient, db_session: Session) -> None:
    org, headers = _auth(client, db_session)
    patient_a = _seed_address(
        db_session,
        organization=org,
        external_ref="ZN-OV-A",
        lon=_BILBAO_LON,
        lat=_BILBAO_LAT,
        geocode_status="matched",
    )
    patient_b = _seed_address(
        db_session,
        organization=org,
        external_ref="ZN-OV-B",
        lon=_BILBAO_LON + 0.001,
        lat=_BILBAO_LAT,
        geocode_status="matched",
    )
    created = client.post(
        "/api/v1/zones",
        json={
            "organization_id": str(org.id),
            "name": "Corta",
            "kind": "urban",
            "max_visits": 1,
        },
        headers=headers,
    )
    assert created.status_code == 201
    zone_id = created.json()["id"]

    assigned = client.put(
        f"/api/v1/zones/{zone_id}/patients/{patient_a.id}",
        params={"organization_id": str(org.id)},
        json={"reason": "paciente habitual de esta zona"},
        headers={**headers, "If-Match": '"1"'},
    )
    assert assigned.status_code == 204
    assert assigned.headers["etag"] == '"2"'

    fetched = client.get(
        f"/api/v1/zones/{zone_id}",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["assignments"] == [
        {
            "patient_id": str(patient_a.id),
            "source": "manual",
            "override_reason": "paciente habitual de esta zona",
        }
    ]

    over = client.put(
        f"/api/v1/zones/{zone_id}/patients/{patient_b.id}",
        params={"organization_id": str(org.id)},
        json={"reason": "no cabe"},
        headers={**headers, "If-Match": '"2"'},
    )
    assert over.status_code == 409
    assert over.json()["code"] == "ZONE_CAPACITY_EXCEEDED"

    stale = client.put(
        f"/api/v1/zones/{zone_id}/patients/{patient_a.id}",
        params={"organization_id": str(org.id)},
        json={"reason": "otra vez"},
        headers={**headers, "If-Match": '"1"'},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "ZONE_VERSION_CONFLICT"


def test_manual_override_survives_regenerated_proposal_unless_reset(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, headers = _auth(client, db_session)
    for index, (lon, lat) in enumerate(_urban_coords(12)):
        _seed_address(
            db_session,
            organization=org,
            external_ref=f"ZN-P-{index:02d}",
            lon=lon,
            lat=lat,
            geocode_status="matched" if index % 2 == 0 else "manual",
        )

    first_id = _run_proposal(client, queue, db_session, org=org, headers=headers)
    accepted = client.post(
        f"/api/v1/zone-proposals/{first_id}/accept",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert accepted.status_code == 200
    zones = accepted.json()["zones"]
    assert len(zones) >= 2
    source_zone = next(zone for zone in zones if zone["assignments"])
    target_zone = next(zone for zone in zones if zone["id"] != source_zone["id"])
    patient_id = source_zone["assignments"][0]["patient_id"]
    assert source_zone["assignments"][0]["source"] == "cluster"

    moved = client.put(
        f"/api/v1/zones/{target_zone['id']}/patients/{patient_id}",
        params={"organization_id": str(org.id)},
        json={"reason": "caserío más cercano al depósito de la zona destino"},
        headers={**headers, "If-Match": f'"{target_zone["version"]}"'},
    )
    assert moved.status_code == 204

    after_move = _assignment_for(
        client, org_id=org.id, zone_id=target_zone["id"], patient_id=patient_id, headers=headers
    )
    assert after_move is not None
    assert after_move["source"] == "manual"
    assert after_move["override_reason"]

    second_id = _run_proposal(client, queue, db_session, org=org, headers=headers)
    reaccepted = client.post(
        f"/api/v1/zone-proposals/{second_id}/accept",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert reaccepted.status_code == 200
    assert reaccepted.json()["preserved_override_count"] >= 1
    persisted = _assignment_for(
        client, org_id=org.id, zone_id=target_zone["id"], patient_id=patient_id, headers=headers
    )
    assert persisted is not None
    assert persisted["source"] == "manual"
    assert persisted["override_reason"]

    identity_service.set_current_organization_context(db_session, organization_id=org.id)
    current = (
        db_session.query(ZoneAssignment)
        .filter(
            ZoneAssignment.patient_id == uuid.UUID(patient_id), ZoneAssignment.valid_to.is_(None)
        )
        .one()
    )
    assert current.source == "manual"
    assert current.zone_id == uuid.UUID(target_zone["id"])

    reset = client.post(
        f"/api/v1/zone-proposals/{second_id}/accept",
        params={"organization_id": str(org.id), "reset_overrides": True},
        headers=headers,
    )
    assert reset.status_code == 200
    assert reset.json()["preserved_override_count"] == 0
    found = None
    for zone in reset.json()["zones"]:
        for item in zone["assignments"]:
            if item["patient_id"] == patient_id:
                found = item
                break
    assert found is not None
    assert found["source"] == "cluster"


def test_get_zone_isolates_organizations(client: TestClient, db_session: Session) -> None:
    org_a, headers_a = _auth(client, db_session)
    org_b, headers_b = _auth(client, db_session)
    created = client.post(
        "/api/v1/zones",
        json={"organization_id": str(org_a.id), "name": "Privada", "kind": "mixed"},
        headers=headers_a,
    )
    assert created.status_code == 201
    zone_id = created.json()["id"]

    forbidden = client.get(
        f"/api/v1/zones/{zone_id}",
        params={"organization_id": str(org_a.id)},
        headers=headers_b,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ORGANIZATION"

    missing = client.get(
        f"/api/v1/zones/{zone_id}",
        params={"organization_id": str(org_b.id)},
        headers=headers_b,
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "ZONE_NOT_FOUND"


def test_list_zones_and_patients_include_current_assignment(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, headers = _auth(client, db_session)
    for index, (lon, lat) in enumerate(_urban_coords(8)):
        _seed_address(
            db_session,
            organization=org,
            external_ref=f"ZN-L-{index:02d}",
            lon=lon,
            lat=lat,
            geocode_status="matched",
        )

    empty = client.get("/api/v1/zones", params={"organization_id": str(org.id)}, headers=headers)
    assert empty.status_code == 200
    assert empty.json()["zones"] == []

    proposal_id = _run_proposal(
        client, queue, db_session, org=org, headers=headers, max_visits=4, target_zones=2
    )
    accepted = client.post(
        f"/api/v1/zone-proposals/{proposal_id}/accept",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert accepted.status_code == 200

    listed = client.get("/api/v1/zones", params={"organization_id": str(org.id)}, headers=headers)
    assert listed.status_code == 200
    zones = listed.json()["zones"]
    assert len(zones) >= 2
    for zone in zones:
        assert zone["kind"] in ("urban", "rural", "mixed")
        assert zone["version"] >= 1
        assert zone["patient_count"] >= 0
        assert "max_visits" in zone
        assert zone["patient_count"] == len(
            next(item for item in accepted.json()["zones"] if item["id"] == zone["id"])["assignments"]
        )

    patients = client.get(
        "/api/v1/patients", params={"organization_id": str(org.id)}, headers=headers
    )
    assert patients.status_code == 200
    body = patients.json()["patients"]
    assigned = [patient for patient in body if patient["zone_id"]]
    assert assigned
    zone_by_id = {zone["id"]: zone for zone in zones}
    for patient in assigned:
        zone = zone_by_id[patient["zone_id"]]
        assert patient["assigned_zone"] == zone["name"]
        assert "street" not in patient
        assert patient.get("address_ciphertext") is None

    other_org, other_headers = _auth(client, db_session)
    forbidden = client.get(
        "/api/v1/zones",
        params={"organization_id": str(org.id)},
        headers=other_headers,
    )
    assert forbidden.status_code == 403
    isolated = client.get(
        "/api/v1/zones",
        params={"organization_id": str(other_org.id)},
        headers=other_headers,
    )
    assert isolated.status_code == 200
    assert isolated.json()["zones"] == []
