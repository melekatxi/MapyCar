"""2.QA.1 — E2E HTTP: proponer zonas → override manual → plan mensual → publicar.

Dataset ficticio de 200 pacientes (sin PII): blobs urbanos tipo Bilbao + hamlets
rurales de Bizkaia, geocodes confirmados `matched`. Sin Playwright: pytest +
testcontainers, el mismo patrón que `test_plans_e2e` / `test_zones_e2e`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from math import ceil

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization
from app.modules.imports.models import Address, Patient
from app.modules.notifications.models import EVENT_PLAN_PUBLISHED
from app.modules.planning.models import DailyRoute, MonthlyPlan
from app.modules.zoning.models import ZoneAssignment
from tests.test_plan_publish_e2e import _list_routes, _outbox_rows, _publish, _route_count
from tests.test_plans_e2e import (
    _create_user,
    _get_plan,
    _login,
    _patch_visit,
    _point,
    _seed_org_team,
)
from tests.test_plans_e2e import _handler_for as _planning_handler_for
from tests.test_zones_e2e import _assignment_for, _run_proposal

COHORT_SIZE = 200
ZONE_MAX_VISITS = 60
TARGET_ZONES = 6
_URBAN_STEP_DEG = 0.0006
_RURAL_STEP_DEG = 0.0008

# Blobs densos (~67 m) en municipios distintos → semillas urbanas separadas.
_URBAN_BLOBS: tuple[tuple[str, str, float, float, int], ...] = (
    ("Bilbao", "48001", -2.9348, 43.2630, 46),
    ("Getxo", "48991", -3.0078, 43.3438, 46),
    ("Durango", "48200", -2.6398, 43.1689, 45),
    ("Gernika-Lumo", "48300", -2.6833, 43.3169, 45),
)
# Hamlets de 3 puntos: densidad < umbral urbano; intra-grupo << 2.5 km (DBSCAN).
_RURAL_HAMLETS: tuple[tuple[str, str, float, float, int], ...] = (
    ("Karrantza Harana", "48891", -3.3630, 43.2210, 3),
    ("Orduña", "48460", -3.0095, 42.9947, 3),
    ("Lekeitio", "48280", -2.4961, 43.3625, 3),
    ("Bermeo", "48370", -2.7214, 43.4208, 3),
    ("Otxandio", "48210", -2.6547, 43.0394, 3),
    ("Balmaseda", "48800", -3.2000, 43.1958, 3),
)


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


def _grid(
    n: int, *, origin_lon: float, origin_lat: float, step_deg: float
) -> list[tuple[float, float]]:
    cols = max(1, ceil(n**0.5))
    return [
        (origin_lon + (index % cols) * step_deg, origin_lat + (index // cols) * step_deg)
        for index in range(n)
    ]


def _cohort_specs() -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for municipality, postal_code, lon, lat, count in _URBAN_BLOBS:
        for blob_lon, blob_lat in _grid(
            count, origin_lon=lon, origin_lat=lat, step_deg=_URBAN_STEP_DEG
        ):
            specs.append(
                {
                    "municipality": municipality,
                    "postal_code": postal_code,
                    "lon": blob_lon,
                    "lat": blob_lat,
                }
            )
    for municipality, postal_code, lon, lat, count in _RURAL_HAMLETS:
        for hamlet_lon, hamlet_lat in _grid(
            count, origin_lon=lon, origin_lat=lat, step_deg=_RURAL_STEP_DEG
        ):
            specs.append(
                {
                    "municipality": municipality,
                    "postal_code": postal_code,
                    "lon": hamlet_lon,
                    "lat": hamlet_lat,
                }
            )
    return specs


def _seed_fictional_cohort(db: Session, *, organization: Organization) -> list[Patient]:
    """200 filas en un commit: evita el cuello de botella de testcontainers por fila."""
    specs = _cohort_specs()
    assert len(specs) == COHORT_SIZE
    identity_service.set_current_organization_context(db, organization_id=organization.id)
    patients = [
        Patient(
            organization_id=organization.id,
            external_ref=f"F2-{index:03d}",
            display_ref=f"F2-{index:03d}",
        )
        for index in range(COHORT_SIZE)
    ]
    db.add_all(patients)
    db.flush()
    db.add_all(
        [
            Address(
                organization_id=organization.id,
                patient_id=patient.id,
                address_ciphertext="enc",
                postal_code=str(spec["postal_code"]),
                municipality=str(spec["municipality"]),
                province="Bizkaia",
                location=_point(float(spec["lon"]), float(spec["lat"])),
                geocode_status="matched",
                is_active=True,
            )
            for patient, spec in zip(patients, specs, strict=True)
        ]
    )
    db.commit()
    return patients


def test_propose_zones_manual_adjust_generate_monthly_plan_and_publish(
    client: TestClient, db_session: Session, queue: JobQueue
) -> None:
    org, team = _seed_org_team(db_session, name="Org fase2 e2e")
    planner = _create_user(db_session, organization=org, role="planner")
    field_user = _create_user(db_session, organization=org, role="field")
    token = _login(client, planner)
    headers = {"Authorization": f"Bearer {token}"}
    patients = _seed_fictional_cohort(db_session, organization=org)
    assert len(patients) == COHORT_SIZE

    proposal_id = _run_proposal(
        client,
        queue,
        db_session,
        org=org,
        headers=headers,
        max_visits=ZONE_MAX_VISITS,
        target_zones=TARGET_ZONES,
    )
    fetched_proposal = client.get(
        f"/api/v1/zone-proposals/{proposal_id}",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert fetched_proposal.status_code == 200
    proposal_body = fetched_proposal.json()
    assert proposal_body["status"] == "succeeded"
    assert proposal_body["metrics"]["n_points"] == COHORT_SIZE
    assert proposal_body["metrics"]["n_clusters"] >= 2
    assert proposal_body["outliers"] == []

    accepted = client.post(
        f"/api/v1/zone-proposals/{proposal_id}/accept",
        params={"organization_id": str(org.id)},
        headers=headers,
    )
    assert accepted.status_code == 200
    zones = accepted.json()["zones"]
    populated = [zone for zone in zones if zone["assignments"]]
    assert len(populated) >= 2
    source_zone = max(populated, key=lambda zone: len(zone["assignments"]))
    target_zone = min(
        (zone for zone in populated if zone["id"] != source_zone["id"]),
        key=lambda zone: len(zone["assignments"]),
    )
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

    created = client.post(
        "/api/v1/plans",
        json={
            "organization_id": str(org.id),
            "team_id": str(team.id),
            "period": "2026-09",
            "constraints": {
                "max_visits": 16,
                "workday_minutes": 480,
                "service_minutes": 30,
                "zone_kind": "urban",
            },
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
    result = queue.run_once(queue="planning", handler=_planning_handler_for(db_session))
    assert result is not None
    assert result.status == "succeeded"

    plan = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert plan["status"] == "draft"
    assert plan["metrics"]["n_assigned"] == COHORT_SIZE
    assert len(plan["assignments"]) == COHORT_SIZE
    assert plan["metrics"]["n_conflicts"] == 0
    overridden = next(item for item in plan["assignments"] if item["patient_id"] == patient_id)
    assert overridden["zone_id"] == target_zone["id"]

    version = plan["version"]
    assignment = next(item for item in plan["assignments"] if item["patient_id"] != patient_id)
    working_days = [day["date"] for day in plan["calendar"]["working_days"]]
    target_date = next(day for day in working_days if day != assignment["date"])
    preview = _patch_visit(
        client,
        plan_id=plan_id,
        org_id=org.id,
        patient_id=assignment["patient_id"],
        headers=headers,
        date=target_date,
        zone_id=assignment["zone_id"],
        version=version,
        confirm=False,
    )
    assert preview.status_code == 200
    assert preview.json()["would_apply"] is False
    if preview.json()["conflicts"] == []:
        applied = _patch_visit(
            client,
            plan_id=plan_id,
            org_id=org.id,
            patient_id=assignment["patient_id"],
            headers=headers,
            date=target_date,
            zone_id=assignment["zone_id"],
            version=version,
            confirm=True,
        )
        assert applied.status_code == 200
        assert applied.json()["would_apply"] is True
        version = applied.json()["version"]

    published = _publish(
        client,
        plan_id=plan_id,
        org_id=org.id,
        headers=headers,
        version=version,
        body={"assignees": [{"zone_id": target_zone["id"], "assignee_id": str(field_user.id)}]},
    )
    assert published.status_code == 200
    body = published.json()
    assert body["status"] == "published"
    assert body["routes_created"] >= 1
    assert body["outbox_id"]

    listed = _list_routes(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert listed.status_code == 200
    routes = listed.json()["routes"]
    assert len(routes) == body["routes_created"]
    assert _route_count(db_session, org_id=org.id, plan_id=plan_id) == len(routes)
    target_routes = [route for route in routes if route["zone_id"] == target_zone["id"]]
    assert target_routes
    assert {route["assignee_id"] for route in target_routes} == {str(field_user.id)}

    events = _outbox_rows(db_session, org_id=org.id, plan_id=plan_id)
    assert len(events) == 1
    assert events[0].event_type == EVENT_PLAN_PUBLISHED
    assert str(events[0].id) == body["outbox_id"]
    assert events[0].processed_at is None

    fetched = _get_plan(client, plan_id=plan_id, org_id=org.id, headers=headers)
    assert fetched["status"] == "published"
    identity_service.set_current_organization_context(db_session, organization_id=org.id)
    persisted_plan = db_session.get(MonthlyPlan, uuid.UUID(plan_id))
    assert persisted_plan is not None
    assert persisted_plan.status == "published"
    assert persisted_plan.published_at is not None
    assert (
        db_session.query(DailyRoute)
        .filter(DailyRoute.plan_id == uuid.UUID(plan_id), DailyRoute.organization_id == org.id)
        .count()
        >= 1
    )

    persisted = (
        db_session.query(ZoneAssignment)
        .filter(
            ZoneAssignment.patient_id == uuid.UUID(patient_id),
            ZoneAssignment.valid_to.is_(None),
        )
        .one()
    )
    assert persisted.source == "manual"
    assert persisted.zone_id == uuid.UUID(target_zone["id"])
    assert persisted.override_reason
    still_manual = _assignment_for(
        client, org_id=org.id, zone_id=target_zone["id"], patient_id=patient_id, headers=headers
    )
    assert still_manual is not None
    assert still_manual["source"] == "manual"
