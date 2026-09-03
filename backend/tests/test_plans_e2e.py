"""E2E de planes: POST 201 borrador, generate, GET, PATCH visita (If-Match).

Ref: 2.BE.11–12, RF-13, RF-14, diseño sección 8.4.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.jobs.worker import HANDLERS
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization, Team, User, UserMembership
from app.modules.imports.models import Address, Patient
from app.modules.planning import service as planning_service
from app.modules.planning.models import MonthlyPlan
from app.modules.zoning.models import Zone, ZoneAssignment

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


def _create_user(db: Session, *, organization: Organization, role: str, suffix: str = "") -> User:
    user = User(
        email_normalized=f"{role}-{suffix}{uuid.uuid4().hex[:8]}@example.com",
        display_name=role,
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


def _point(lon: float, lat: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


def _seed_org_team(db: Session, *, name: str) -> tuple[Organization, Team]:
    org = Organization(name=name)
    db.add(org)
    db.flush()
    identity_service.set_current_organization_context(db, organization_id=org.id)
    team = Team(organization_id=org.id, name=f"Equipo {name}")
    db.add(team)
    db.commit()
    return org, team


def _seed_zone(db: Session, *, organization: Organization, name: str = "Zona urbana") -> Zone:
    identity_service.set_current_organization_context(db, organization_id=organization.id)
    zone = Zone(organization_id=organization.id, name=name, kind="urban")
    db.add(zone)
    db.commit()
    return zone


def _seed_patient(
    db: Session,
    *,
    organization: Organization,
    external_ref: str,
    geocode_status: str,
    zone: Zone | None,
    lon: float = _BILBAO_LON,
    lat: float = _BILBAO_LAT,
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
            postal_code="48001",
            municipality="Bilbao",
            province="Bizkaia",
            location=_point(lon, lat),
            geocode_status=geocode_status,
            is_active=True,
        )
    )
    if zone is not None:
        db.add(
            ZoneAssignment(
                organization_id=organization.id,
                zone_id=zone.id,
                patient_id=patient.id,
                source="manual",
            )
        )
    db.commit()
    return patient


def _handler_for(db: Session) -> Callable[[dict], None]:
    def handler(payload: dict) -> None:
        planning_service.generate_plan(
            db,
            plan_id=uuid.UUID(payload["plan_id"]),
            organization_id=uuid.UUID(payload["organization_id"]),
        )

    return handler


def test_worker_registers_planning_handler() -> None:
    assert "planning" in HANDLERS


def test_create_generate_get_shows_calendar_days(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, team = _seed_org_team(db_session, name="Org plans e2e")
    user = _create_user(db_session, organization=org, role="planner")
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}
    zone = _seed_zone(db_session, organization=org)
    _seed_patient(
        db_session, organization=org, external_ref="PL-001", geocode_status="matched", zone=zone
    )
    _seed_patient(
        db_session,
        organization=org,
        external_ref="PL-002",
        geocode_status="manual",
        zone=zone,
        lon=_BILBAO_LON + 0.001,
    )

    created = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org.id),
            "team_id": str(team.id),
            "period": "2026-09",
            "constraints": {"max_visits": 8, "zone_kind": "urban"},
        },
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "draft"
    assert body["version"] == 1
    assert body["period"] == "2026-09"
    assert body["created_by"] == str(user.id)
    plan_id = body["id"]

    generated = client.post(
        f"/api/v1/plans/{plan_id}/generate",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert generated.status_code == 202
    assert generated.json()["job_id"]
    assert generated.json()["status"] == "draft"

    result = queue.run_once(queue="planning", handler=_handler_for(db_session))
    assert result is not None
    assert result.status == "succeeded"

    fetched = client.get(
        f"/api/v1/plans/{plan_id}",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["status"] == "draft"
    assert payload["version"] == 1
    working_days = payload["calendar"]["working_days"]
    assert len(working_days) > 0
    assert all(day["date"].startswith("2026-09-") for day in working_days)
    assert payload["metrics"]["n_assigned"] == 2
    assert payload["metrics"]["n_conflicts"] == 0
    assert len(payload["assignments"]) == 2
    assigned_dates = {item["date"] for item in payload["assignments"]}
    calendar_dates = {day["date"] for day in working_days}
    assert assigned_dates <= calendar_dates


def test_unconfirmed_address_reports_address_not_confirmed(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, team = _seed_org_team(db_session, name="Org plans unconfirmed")
    user = _create_user(db_session, organization=org, role="planner")
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}
    zone = _seed_zone(db_session, organization=org)
    unconfirmed = _seed_patient(
        db_session,
        organization=org,
        external_ref="PL-PENDING",
        geocode_status="pending",
        zone=zone,
    )
    _seed_patient(
        db_session,
        organization=org,
        external_ref="PL-OK",
        geocode_status="matched",
        zone=zone,
        lon=_BILBAO_LON + 0.002,
    )

    created = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org.id),
            "team_id": str(team.id),
            "period": "2026-09",
            "constraints": {},
        },
        headers=headers,
    )
    assert created.status_code == 201
    plan_id = created.json()["id"]

    generated = client.post(
        f"/api/v1/plans/{plan_id}/generate",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert generated.status_code == 202
    result = queue.run_once(queue="planning", handler=_handler_for(db_session))
    assert result is not None
    assert result.status == "succeeded"

    fetched = client.get(
        f"/api/v1/plans/{plan_id}",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert fetched.status_code == 200
    payload = fetched.json()
    codes = {item["code"] for item in payload["conflicts"]}
    assert "ADDRESS_NOT_CONFIRMED" in codes
    assert str(unconfirmed.id) in {item["patient_id"] for item in payload["conflicts"]}
    assert payload["metrics"]["n_conflicts"] >= 1
    assert payload["metrics"]["n_assigned"] == 1

    validated = client.post(
        f"/api/v1/plans/{plan_id}/validate",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert validated.status_code == 200
    assert validated.json()["warnings"] == []
    assert isinstance(validated.json()["conflicts"], list)


def test_field_cannot_post_plan(client: TestClient, db_session: Session) -> None:
    org, team = _seed_org_team(db_session, name="Org plans field")
    user = _create_user(db_session, organization=org, role="field")
    token = _login(client, user)

    response = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org.id),
            "team_id": str(team.id),
            "period": "2026-09",
            "constraints": {},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ROLE"


def test_duplicate_plan_returns_409(client: TestClient, db_session: Session) -> None:
    org, team = _seed_org_team(db_session, name="Org plans dup")
    user = _create_user(db_session, organization=org, role="admin")
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "organization_id": str(org.id),
        "team_id": str(team.id),
        "period": "2026-09",
        "constraints": {},
    }

    first = client.post("/api/v1/plans", json=payload, headers=headers)
    assert first.status_code == 201
    second = client.post("/api/v1/plans", json=payload, headers=headers)
    assert second.status_code == 409
    assert second.json()["code"] == "PLAN_ALREADY_EXISTS"


def test_get_isolates_organizations(client: TestClient, db_session: Session) -> None:
    org_a, team_a = _seed_org_team(db_session, name="Org plans A")
    org_a_id, team_a_id = org_a.id, team_a.id
    org_b, _team_b = _seed_org_team(db_session, name="Org plans B")
    org_b_id = org_b.id
    user_a = _create_user(db_session, organization=org_a, role="planner", suffix="a")
    user_b = _create_user(db_session, organization=org_b, role="planner", suffix="b")
    token_a = _login(client, user_a)
    token_b = _login(client, user_b)

    created = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org_a_id),
            "team_id": str(team_a_id),
            "period": "2026-09",
            "constraints": {},
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert created.status_code == 201
    plan_id = created.json()["id"]

    forbidden = client.get(
        f"/api/v1/plans/{plan_id}",
        params={"organization_id": str(org_a_id)},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ORGANIZATION"

    missing = client.get(
        f"/api/v1/plans/{plan_id}",
        params={"organization_id": str(org_b_id)},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "PLAN_NOT_FOUND"


def test_validate_published_plan_returns_409(client: TestClient, db_session: Session) -> None:
    org, team = _seed_org_team(db_session, name="Org plans published")
    user = _create_user(db_session, organization=org, role="planner")
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org.id),
            "team_id": str(team.id),
            "period": "2026-09",
            "constraints": {},
        },
        headers=headers,
    )
    assert created.status_code == 201
    plan_id = created.json()["id"]

    identity_service.set_current_organization_context(db_session, organization_id=org.id)
    plan = db_session.get(MonthlyPlan, uuid.UUID(plan_id))
    assert plan is not None
    plan.status = "published"
    db_session.commit()

    validated = client.post(
        f"/api/v1/plans/{plan_id}/validate",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert validated.status_code == 409
    assert validated.json()["code"] == "PLAN_PUBLISHED"

    generated = client.post(
        f"/api/v1/plans/{plan_id}/generate",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert generated.status_code == 409
    assert generated.json()["code"] == "PLAN_PUBLISHED"


def _seed_generated_plan(
    client: TestClient,
    db: Session,
    queue: JobQueue,
    *,
    org_name: str,
    max_visits: int = 8,
    n_patients: int = 2,
) -> tuple[Organization, str, dict[str, str], list[Patient], Zone]:
    org, team = _seed_org_team(db, name=org_name)
    user = _create_user(db, organization=org, role="planner")
    token = _login(client, user)
    headers = {"Authorization": f"Bearer {token}"}
    zone = _seed_zone(db, organization=org)
    patients = [
        _seed_patient(
            db,
            organization=org,
            external_ref=f"MV-{index:03d}",
            geocode_status="matched",
            zone=zone,
            lon=_BILBAO_LON + 0.001 * index,
        )
        for index in range(n_patients)
    ]
    created = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org.id),
            "team_id": str(team.id),
            "period": "2026-09",
            "constraints": {"max_visits": max_visits, "zone_kind": "urban"},
        },
        headers=headers,
    )
    assert created.status_code == 201
    plan_id = created.json()["id"]
    generated = client.post(
        f"/api/v1/plans/{plan_id}/generate",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert generated.status_code == 202
    result = queue.run_once(queue="planning", handler=_handler_for(db))
    assert result is not None
    assert result.status == "succeeded"
    return org, plan_id, headers, patients, zone


def _get_plan(
    client: TestClient, *, plan_id: str, org_id: uuid.UUID, headers: dict[str, str]
) -> dict:
    fetched = client.get(
        f"/api/v1/plans/{plan_id}",
        params={"organization_id": str(org_id)},
        headers=headers,
    )
    assert fetched.status_code == 200
    return fetched.json()


def _patch_visit(
    client: TestClient,
    *,
    plan_id: str,
    org_id: uuid.UUID,
    patient_id: str,
    headers: dict[str, str],
    date: str,
    zone_id: str,
    version: int,
    confirm: bool | None = None,
    if_match: str | None = None,
) -> object:
    payload: dict[str, object] = {"date": date, "zone_id": zone_id}
    if confirm is not None:
        payload["confirm"] = confirm
    request_headers = dict(headers)
    if if_match is None:
        request_headers["If-Match"] = f'"{version}"'
    else:
        request_headers["If-Match"] = if_match
    return client.patch(
        f"/api/v1/plans/{plan_id}/visits/{patient_id}",
        params={"organization_id": str(org_id)},
        json=payload,
        headers=request_headers,
    )


def test_move_visit_dry_run_weekend_returns_conflicts_without_mutating(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org move weekend"
    )
    before = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert before["version"] == 1
    assignment = before["assignments"][0]
    assignments_before = before["assignments"]

    preview = _patch_visit(
        client,
        plan_id=plan_id,
        org_id=org.id,
        patient_id=assignment["patient_id"],
        headers=headers,
        date="2026-09-05",
        zone_id=str(zone.id),
        version=1,
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["would_apply"] is False
    assert body["version"] == 1
    assert body["plan"] is None
    assert any(item["code"] == "WINDOW_OUTSIDE_WORKDAY" for item in body["conflicts"])

    after = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert after["version"] == 1
    assert after["assignments"] == assignments_before


def test_move_visit_dry_run_capacity_exceeded_without_mutating(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org move capacity", max_visits=1
    )
    before = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert before["metrics"]["n_assigned"] == 2
    first, second = before["assignments"]
    assert first["date"] != second["date"]

    preview = _patch_visit(
        client,
        plan_id=plan_id,
        org_id=org.id,
        patient_id=second["patient_id"],
        headers=headers,
        date=first["date"],
        zone_id=str(zone.id),
        version=1,
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["would_apply"] is False
    assert body["version"] == 1
    assert any(item["code"] == "CAPACITY_EXCEEDED" for item in body["conflicts"])

    after = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert after["version"] == 1
    assert after["assignments"] == before["assignments"]


def test_move_visit_confirm_applies_and_bumps_version(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org move confirm"
    )
    before = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assignment = before["assignments"][0]
    working_days = [day["date"] for day in before["calendar"]["working_days"]]
    target = next(day for day in working_days if day != assignment["date"])

    preview = _patch_visit(
        client,
        plan_id=plan_id,
        org_id=org.id,
        patient_id=assignment["patient_id"],
        headers=headers,
        date=target,
        zone_id=str(zone.id),
        version=1,
        confirm=False,
    )
    assert preview.status_code == 200
    assert preview.json()["conflicts"] == []
    assert preview.json()["would_apply"] is False
    still = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert still["version"] == 1
    assert still["assignments"] == before["assignments"]

    applied = _patch_visit(
        client,
        plan_id=plan_id,
        org_id=org.id,
        patient_id=assignment["patient_id"],
        headers=headers,
        date=target,
        zone_id=str(zone.id),
        version=1,
        confirm=True,
        if_match="1",
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["would_apply"] is True
    assert body["conflicts"] == []
    assert body["version"] == 2
    assert body["plan"]["version"] == 2
    moved = next(
        item
        for item in body["plan"]["assignments"]
        if item["patient_id"] == assignment["patient_id"]
    )
    assert moved["date"] == target
    assert moved["zone_id"] == str(zone.id)
    assert applied.headers["etag"] == '"2"'

    fetched = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert fetched["version"] == 2
    fetched_moved = next(
        item for item in fetched["assignments"] if item["patient_id"] == assignment["patient_id"]
    )
    assert fetched_moved["date"] == target


def test_move_visit_confirm_with_conflicts_does_not_mutate(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org move confirm conflict"
    )
    before = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assignment = before["assignments"][0]

    blocked = _patch_visit(
        client,
        plan_id=plan_id,
        org_id=org.id,
        patient_id=assignment["patient_id"],
        headers=headers,
        date="2026-09-06",
        zone_id=str(zone.id),
        version=1,
        confirm=True,
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "PLAN_MOVE_CONFLICT"

    after = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert after["version"] == 1
    assert after["assignments"] == before["assignments"]


def test_move_visit_if_match_mismatch_409(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org move if-match"
    )
    before = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assignment = before["assignments"][0]
    working_days = [day["date"] for day in before["calendar"]["working_days"]]
    target = next(day for day in working_days if day != assignment["date"])

    missing = client.patch(
        f"/api/v1/plans/{plan_id}/visits/{assignment['patient_id']}",
        params={"organization_id": str(org.id)},
        json={"date": target, "zone_id": str(zone.id), "confirm": True},
        headers=headers,
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "IF_MATCH_REQUIRED"

    stale = _patch_visit(
        client,
        plan_id=plan_id,
        org_id=org.id,
        patient_id=assignment["patient_id"],
        headers=headers,
        date=target,
        zone_id=str(zone.id),
        version=1,
        confirm=True,
        if_match='"0"',
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "PLAN_VERSION_CONFLICT"

    after = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert after["version"] == 1
    assert after["assignments"] == before["assignments"]


def test_field_cannot_patch_visit(client: TestClient, db_session: Session, queue: JobQueue) -> None:
    org, plan_id, planner_headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org move field"
    )
    before = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=planner_headers)
    assignment = before["assignments"][0]
    field_user = _create_user(db_session, organization=org, role="field")
    token = _login(client, field_user)

    response = client.patch(
        f"/api/v1/plans/{plan_id}/visits/{assignment['patient_id']}",
        params={"organization_id": str(org.id)},
        json={"date": assignment["date"], "zone_id": str(zone.id), "confirm": True},
        headers={"Authorization": f"Bearer {token}", "If-Match": '"1"'},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN_ROLE"


def test_move_visit_published_plan_409(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org move published"
    )
    before = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assignment = before["assignments"][0]
    identity_service.set_current_organization_context(db_session, organization_id=org.id)
    plan = db_session.get(MonthlyPlan, uuid.UUID(plan_id))
    assert plan is not None
    plan.status = "published"
    db_session.commit()

    response = _patch_visit(
        client,
        plan_id=plan_id,
        org_id=org.id,
        patient_id=assignment["patient_id"],
        headers=headers,
        date=assignment["date"],
        zone_id=str(zone.id),
        version=1,
        confirm=True,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PLAN_PUBLISHED"


def test_list_plans_returns_drafts_for_own_organization(
    client: TestClient, db_session: Session
) -> None:
    org_a, team_a = _seed_org_team(db_session, name="Org list A")
    org_a_id, team_a_id = org_a.id, team_a.id
    org_b, team_b = _seed_org_team(db_session, name="Org list B")
    org_b_id, team_b_id = org_b.id, team_b.id
    user_a = _create_user(db_session, organization=org_a, role="planner", suffix="la")
    user_b = _create_user(db_session, organization=org_b, role="planner", suffix="lb")
    token_a = _login(client, user_a)
    token_b = _login(client, user_b)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    created = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org_a_id),
            "team_id": str(team_a_id),
            "period": "2026-09",
            "constraints": {},
        },
        headers=headers_a,
    )
    assert created.status_code == 201
    plan_id = created.json()["id"]

    other = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org_b_id),
            "team_id": str(team_b_id),
            "period": "2026-10",
            "constraints": {},
        },
        headers=headers_b,
    )
    assert other.status_code == 201

    listed = client.get(
        "/api/v1/plans",
        params={"organization_id": str(org_a_id)},
        headers=headers_a,
    )
    assert listed.status_code == 200
    plans = listed.json()["plans"]
    assert [item["id"] for item in plans] == [plan_id]
    assert plans[0]["period"] == "2026-09"
    assert plans[0]["status"] == "draft"
    assert plans[0]["team_id"] == str(team_a_id)

    forbidden = client.get(
        "/api/v1/plans",
        params={"organization_id": str(org_a_id)},
        headers=headers_b,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ORGANIZATION"

    isolated = client.get(
        "/api/v1/plans",
        params={"organization_id": str(org_b_id)},
        headers=headers_b,
    )
    assert isolated.status_code == 200
    assert [item["id"] for item in isolated.json()["plans"]] == [other.json()["id"]]


def test_move_visit_unknown_patient_404(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, plan_id, headers, _patients, zone = _seed_generated_plan(
        client, db_session, queue, org_name="Org move unknown"
    )
    missing = _patch_visit(
        client,
        plan_id=plan_id,
        org_id=org.id,
        patient_id=str(uuid.uuid4()),
        headers=headers,
        date="2026-09-02",
        zone_id=str(zone.id),
        version=1,
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "PATIENT_NOT_IN_PLAN"
