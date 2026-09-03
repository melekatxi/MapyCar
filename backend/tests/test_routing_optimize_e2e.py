"""E2E de POST /routes/{id}/optimize, worker e inviabilidad.

Ref: 3.BE.7, 3.BE.12, RF-16, RF-19, diseño sección 8.5.
Misma Idempotency-Key + payload → mismo job; payload distinto → 409.
El worker se invoca con FakeRouter (sin OSRM real).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.optimizer.interface import INCOMPATIBLE_WINDOWS, ISOLATED_STOP
from app.adapters.optimizer.ortools_tsp import OrToolsTspOptimizer
from app.adapters.router.fake import FakeRouter
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.jobs.worker import HANDLERS
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import User
from app.modules.imports.models import Address, Patient
from app.modules.planning.models import DailyRoute, MonthlyPlan
from app.modules.routing.matrix import OsrmTableCache
from app.modules.routing.models import RouteMetric, RouteRevision, RouteStop
from app.modules.routing.schemas import OptimizeRouteRequest
from app.modules.routing.service import optimize_route_job
from app.modules.zoning.models import Zone, ZoneAssignment
from tests.test_plans_e2e import _create_user, _point, _seed_org_team
from tests.test_routing_order_e2e import _auth_headers, _planner_headers_for_assignee

_ORIGIN = {"lat": 43.2630, "lon": -2.9350}
_SERVICE_DATE = date(2026, 9, 8)


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


def _seed_published_route(
    db: Session,
    *,
    org_name: str,
    n_stops: int = 3,
) -> tuple[DailyRoute, User, list[Patient]]:
    org, team = _seed_org_team(db, name=org_name)
    planner = _create_user(db, organization=org, role="planner")
    identity_service.set_current_organization_context(db, organization_id=org.id)
    zone = Zone(organization_id=org.id, name=f"Zona {org_name}", kind="urban")
    db.add(zone)
    db.flush()
    patients: list[Patient] = []
    for index in range(1, n_stops + 1):
        patient = Patient(
            organization_id=org.id,
            external_ref=f"OPT-{org_name}-{index}",
            display_ref=f"Paciente {index}",
        )
        db.add(patient)
        db.flush()
        db.add(
            Address(
                organization_id=org.id,
                patient_id=patient.id,
                address_ciphertext="enc",
                postal_code="48001",
                municipality="Bilbao",
                province="Bizkaia",
                location=_point(-2.9350 + index * 0.001, 43.2630 + index * 0.001),
                geocode_status="matched",
                is_active=True,
            )
        )
        db.add(
            ZoneAssignment(
                organization_id=org.id,
                zone_id=zone.id,
                patient_id=patient.id,
                source="manual",
            )
        )
        patients.append(patient)
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period="2026-09",
        status="published",
        created_by=planner.id,
        result_json={
            "assignments": [
                {
                    "patient_id": str(patient.id),
                    "date": _SERVICE_DATE.isoformat(),
                    "zone_id": str(zone.id),
                }
                for patient in patients
            ]
        },
    )
    db.add(plan)
    db.flush()
    route = DailyRoute(
        organization_id=org.id,
        plan_id=plan.id,
        zone_id=zone.id,
        service_date=_SERVICE_DATE,
        assignee_id=planner.id,
        status="draft",
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    return route, planner, patients


def _body(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "objective": "time",
        "origin": _ORIGIN,
        "destination": _ORIGIN,
        "vehicle_count": 1,
        "cost_per_km": 0.32,
        "cost_per_hour": 21.0,
        "service_minutes": 0,
    }
    payload.update(overrides)
    return payload


def _post_optimize(
    client: TestClient,
    *,
    route_id: uuid.UUID,
    org_id: uuid.UUID,
    headers: dict[str, str],
    body: dict,
    idempotency_key: str | None = "opt-key-1",
) -> object:
    request_headers = dict(headers)
    if idempotency_key is not None:
        request_headers["Idempotency-Key"] = idempotency_key
    return client.post(
        f"/api/v1/routes/{route_id}/optimize",
        params={"organization_id": str(org_id)},
        json=body,
        headers=request_headers,
    )


def _get_route(
    client: TestClient,
    *,
    route_id: uuid.UUID,
    org_id: uuid.UUID,
    headers: dict[str, str],
) -> object:
    return client.get(
        f"/api/v1/routes/{route_id}",
        params={"organization_id": str(org_id)},
        headers=headers,
    )


def _get_comparison(
    client: TestClient,
    *,
    route_id: uuid.UUID,
    org_id: uuid.UUID,
    headers: dict[str, str],
) -> object:
    return client.get(
        f"/api/v1/routes/{route_id}/comparison",
        params={"organization_id": str(org_id)},
        headers=headers,
    )


def _run_job(
    db: Session,
    route: DailyRoute,
    planner: User,
    body: dict,
) -> RouteRevision | None:
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    return optimize_route_job(
        db,
        route_id=route.id,
        organization_id=route.organization_id,
        created_by=planner.id,
        request=OptimizeRouteRequest.model_validate(body),
        router=FakeRouter(),
        cache=OsrmTableCache(fakeredis.FakeStrictRedis()),
        optimizer=OrToolsTspOptimizer(time_limit_seconds=1.0),
    )


def test_worker_registers_optimization_handler() -> None:
    assert "optimization" in HANDLERS


def test_optimize_idempotency_replays_same_key_and_rejects_payload_reuse(
    client: TestClient, db_session: Session
) -> None:
    route, _planner, _patients = _seed_published_route(db_session, org_name="opt-idem")
    headers = _planner_headers_for_assignee(client, db_session, route)
    body = _body()

    first = _post_optimize(
        client, route_id=route.id, org_id=route.organization_id, headers=headers, body=body
    )
    assert first.status_code == 202
    first_body = first.json()
    assert first_body["status"] == "queued"
    assert first_body["job_id"]

    replay = _post_optimize(
        client, route_id=route.id, org_id=route.organization_id, headers=headers, body=body
    )
    assert replay.status_code == 202
    assert replay.json()["job_id"] == first_body["job_id"]
    assert replay.json() == first_body

    conflict = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        body=_body(objective="cost"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSE"


def test_optimize_requires_idempotency_key_and_planner_role(
    client: TestClient, db_session: Session
) -> None:
    route, _planner, _patients = _seed_published_route(db_session, org_name="opt-auth")
    headers = _planner_headers_for_assignee(client, db_session, route)

    missing = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        body=_body(),
        idempotency_key=None,
    )
    assert missing.status_code == 400
    assert missing.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    field_headers = _auth_headers(client, db_session, org_id=route.organization_id, role="field")
    forbidden = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=field_headers,
        body=_body(),
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ROLE"


def test_optimize_happy_path_creates_revision_and_comparison(
    client: TestClient, db_session: Session
) -> None:
    route, planner, patients = _seed_published_route(db_session, org_name="opt-ok", n_stops=3)
    headers = _planner_headers_for_assignee(client, db_session, route)
    body = _body()
    posted = _post_optimize(
        client, route_id=route.id, org_id=route.organization_id, headers=headers, body=body
    )
    assert posted.status_code == 202

    revision = _run_job(db_session, route, planner, body)
    assert revision is not None
    assert revision.status == "draft"
    assert revision.solver_status == "feasible"
    assert revision.revision == 1

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    persisted = db_session.get(DailyRoute, route.id)
    assert persisted is not None
    assert persisted.current_revision == revision.id
    stops = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == revision.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert len(stops) == 3
    assert {stop.patient_id for stop in stops} == {patient.id for patient in patients}
    metrics = db_session.query(RouteMetric).filter(RouteMetric.revision_id == revision.id).all()
    by_variant = {metric.variant: metric for metric in metrics}
    assert set(by_variant) == {"original", "optimized"}
    assert by_variant["original"].calculation_json.get("stale") is False
    assert by_variant["optimized"].calculation_json.get("stale") is False

    comparison = _get_comparison(
        client, route_id=route.id, org_id=route.organization_id, headers=headers
    )
    assert comparison.status_code == 200
    payload = comparison.json()
    assert payload["solver_status"] == "feasible"
    assert payload["revision_id"] == str(revision.id)
    assert payload["original"]["travel_seconds"] >= 0
    assert payload["optimized"]["travel_seconds"] >= 0
    assert "travel_seconds_pct" in payload["savings"]

    detail = _get_route(client, route_id=route.id, org_id=route.organization_id, headers=headers)
    assert detail.status_code == 200
    body_detail = detail.json()
    assert body_detail["solver_status"] == "feasible"
    assert body_detail["diagnostics"] == []
    assert [item["sequence"] for item in body_detail["stops"]] == [1, 2, 3]


def test_incompatible_windows_surface_diagnostics_without_a_tour(
    client: TestClient, db_session: Session
) -> None:
    route, planner, patients = _seed_published_route(db_session, org_name="opt-win", n_stops=2)
    headers = _planner_headers_for_assignee(client, db_session, route)
    body = _body(
        windows=[
            {"patient_id": str(patients[0].id), "start_seconds": 0, "end_seconds": 100},
            {"patient_id": str(patients[1].id), "start_seconds": 0, "end_seconds": 100},
        ]
    )
    revision = _run_job(db_session, route, planner, body)
    assert revision is not None
    assert revision.solver_status == "infeasible"
    codes = {item["code"] for item in revision.constraints_json.get("diagnostics") or []}
    assert INCOMPATIBLE_WINDOWS in codes

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    stops = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == revision.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert [stop.patient_id for stop in stops] == [patient.id for patient in patients]
    metrics = db_session.query(RouteMetric).filter(RouteMetric.revision_id == revision.id).all()
    assert metrics == []

    detail = _get_route(client, route_id=route.id, org_id=route.organization_id, headers=headers)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["solver_status"] == "infeasible"
    diag_codes = {item["code"] for item in payload["diagnostics"]}
    assert INCOMPATIBLE_WINDOWS in diag_codes
    pair = next(item for item in payload["diagnostics"] if item["code"] == INCOMPATIBLE_WINDOWS)
    assert pair["detail"]
    assert "widen window" in pair["suggested_actions"]
    assert "split route" in pair["suggested_actions"]
    assert "drop stop" in pair["suggested_actions"]
    assert "edit order" in pair["suggested_actions"]
    assert [item["patient_id"] for item in payload["stops"]] == [str(p.id) for p in patients]


def test_isolated_stop_surfaces_diagnostics_without_a_tour(
    client: TestClient, db_session: Session
) -> None:
    route, planner, patients = _seed_published_route(db_session, org_name="opt-iso", n_stops=1)
    headers = _planner_headers_for_assignee(client, db_session, route)
    body = _body(
        windows=[{"patient_id": str(patients[0].id), "start_seconds": 0, "end_seconds": 5}]
    )
    revision = _run_job(db_session, route, planner, body)
    assert revision is not None
    assert revision.solver_status == "infeasible"
    codes = {item["code"] for item in revision.constraints_json.get("diagnostics") or []}
    assert ISOLATED_STOP in codes

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    assert db_session.query(RouteMetric).filter(RouteMetric.revision_id == revision.id).all() == []

    detail = _get_route(client, route_id=route.id, org_id=route.organization_id, headers=headers)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["solver_status"] == "infeasible"
    isolated = next(item for item in payload["diagnostics"] if item["code"] == ISOLATED_STOP)
    assert isolated["detail"]
    assert isolated["node_indices"] == [1]
    assert "widen window" in isolated["suggested_actions"]
    assert "drop stop" in isolated["suggested_actions"]
