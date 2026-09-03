"""E2E de propuestas de zona: POST 202 job, worker, GET clusters/outliers/métricas.

Ref: 2.BE.5, RF-09, diseño sección 8.4. Sin Nominatim: direcciones confirmadas en BD.
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
from app.jobs.worker import HANDLERS
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization, User, UserMembership
from app.modules.imports.models import Address, Patient
from app.modules.zoning import service as zoning_service

_BILBAO_LON = -2.9348
_BILBAO_LAT = 43.2630
_KARRANTZA = (-3.3630, 43.2210)


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
        email_normalized=f"planner-{suffix}{uuid.uuid4().hex[:8]}@example.com",
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


def test_worker_registers_zoning_handler() -> None:
    assert "zoning" in HANDLERS


def test_post_then_worker_then_get_respects_max_visits(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org = Organization(name="Org zoning e2e")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}
    max_visits = 5

    for index, (lon, lat) in enumerate(_urban_coords(12)):
        _seed_address(
            db_session,
            organization=org,
            external_ref=f"ZN-U-{index:02d}",
            lon=lon,
            lat=lat,
            geocode_status="matched" if index % 2 == 0 else "manual",
        )
    _seed_address(
        db_session,
        organization=org,
        external_ref="ZN-R-KARRANTZA",
        lon=_KARRANTZA[0],
        lat=_KARRANTZA[1],
        geocode_status="matched",
        municipality="Karrantza Harana",
        postal_code="48891",
    )
    _seed_address(
        db_session,
        organization=org,
        external_ref="ZN-PENDING",
        lon=_BILBAO_LON,
        lat=_BILBAO_LAT,
        geocode_status="pending",
    )

    created = client.post(
        "/api/v1/zone-proposals",
        json={"organization_id": str(org.id), "max_visits": max_visits, "target_zones": 4},
        headers=headers,
    )
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "queued"
    assert body["job_id"]
    proposal_id = body["id"]

    pending = client.get(
        f"/api/v1/zone-proposals/{proposal_id}",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert pending.status_code == 409
    assert pending.json()["code"] == "ZONE_PROPOSAL_NOT_READY"

    result = queue.run_once(queue="zoning", handler=_handler_for(db_session))
    assert result is not None
    assert result.status == "succeeded"

    fetched = client.get(
        f"/api/v1/zone-proposals/{proposal_id}",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["status"] == "succeeded"
    assert payload["clusters"]
    assert payload["metrics"]["max_visits"] == max_visits
    assert payload["metrics"]["n_points"] == 13
    assert payload["metrics"]["n_outliers"] >= 1
    for cluster in payload["clusters"]:
        assert len(cluster["member_ids"]) <= max_visits
    assigned = {item["patient_id"] for item in payload["assignments"]}
    clustered = {member for cluster in payload["clusters"] for member in cluster["member_ids"]}
    assert assigned == clustered
    assert not assigned.intersection({str(oid) for oid in payload["outliers"]})
    assert payload["metrics"]["n_clusters"] == len(payload["clusters"])
    assert payload["metrics"]["max_cluster_size"] == max(
        len(cluster["member_ids"]) for cluster in payload["clusters"]
    )


def test_post_rejects_insufficient_confirmed_geocodes(
    client: TestClient, db_session: Session
) -> None:
    org = Organization(name="Org zoning 422")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}

    _seed_address(
        db_session,
        organization=org,
        external_ref="ZN-ONLY-ONE",
        lon=_BILBAO_LON,
        lat=_BILBAO_LAT,
        geocode_status="matched",
    )
    _seed_address(
        db_session,
        organization=org,
        external_ref="ZN-AMBIGUOUS",
        lon=_BILBAO_LON + 0.001,
        lat=_BILBAO_LAT,
        geocode_status="ambiguous",
    )

    response = client.post(
        "/api/v1/zone-proposals",
        json={"organization_id": str(org.id), "max_visits": 8},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "INSUFFICIENT_GEOCODES"


def test_post_rejects_invalid_capacity(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org zoning capacity")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)

    response = client.post(
        "/api/v1/zone-proposals",
        json={"organization_id": str(org.id), "max_visits": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_get_isolates_organizations(client: TestClient, db_session: Session) -> None:
    org_a = Organization(name="Org zoning A")
    org_b = Organization(name="Org zoning B")
    db_session.add_all([org_a, org_b])
    db_session.commit()
    user_a = _create_planner(db_session, organization=org_a, suffix="a")
    user_b = _create_planner(db_session, organization=org_b, suffix="b")
    token_a = _login(client, user_a)
    token_b = _login(client, user_b)

    for index, (lon, lat) in enumerate(_urban_coords(3)):
        _seed_address(
            db_session,
            organization=org_a,
            external_ref=f"ZN-A-{index}",
            lon=lon,
            lat=lat,
            geocode_status="matched",
        )

    created = client.post(
        "/api/v1/zone-proposals",
        json={"organization_id": str(org_a.id), "max_visits": 8},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert created.status_code == 202
    proposal_id = created.json()["id"]

    forbidden = client.get(
        f"/api/v1/zone-proposals/{proposal_id}",
        params={"organization_id": str(org_a.id)},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ORGANIZATION"

    missing = client.get(
        f"/api/v1/zone-proposals/{proposal_id}",
        params={"organization_id": str(org_b.id)},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "ZONE_PROPOSAL_NOT_FOUND"

    unknown = client.get(
        f"/api/v1/zone-proposals/{uuid.uuid4()}",
        params={"organization_id": str(org_a.id)},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert unknown.status_code == 404


def test_worker_failure_is_readable_on_get(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org = Organization(name="Org zoning failed")
    db_session.add(org)
    db_session.commit()
    user = _create_planner(db_session, organization=org)
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}

    patients = [
        _seed_address(
            db_session,
            organization=org,
            external_ref=f"ZN-FAIL-{index}",
            lon=_BILBAO_LON + index * 0.0006,
            lat=_BILBAO_LAT,
            geocode_status="matched",
        )
        for index in range(2)
    ]

    created = client.post(
        "/api/v1/zone-proposals",
        json={"organization_id": str(org.id), "max_visits": 8},
        headers=headers,
    )
    assert created.status_code == 202
    proposal_id = created.json()["id"]

    identity_service.set_current_organization_context(db_session, organization_id=org.id)
    address = db_session.query(Address).filter(Address.patient_id == patients[0].id).one()
    address.geocode_status = "pending"
    db_session.commit()

    result = queue.run_once(queue="zoning", handler=_handler_for(db_session))
    assert result is not None
    assert result.status == "succeeded"

    fetched = client.get(
        f"/api/v1/zone-proposals/{proposal_id}",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["status"] == "failed"
    assert payload["error_code"] == "INSUFFICIENT_GEOCODES"
    assert payload["clusters"] == []
