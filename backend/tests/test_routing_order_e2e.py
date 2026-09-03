"""E2E de PATCH /routes/{id}/stops/order: reordenar draft, If-Match y métricas stale.

Ref: 3.BE.10, RF-20, diseño sección 8.5. If-Match = daily_routes.version.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.identity.models import Organization, User
from app.modules.imports.models import Patient
from app.modules.planning.models import DailyRoute, MonthlyPlan
from app.modules.routing.models import RouteMetric, RouteRevision, RouteStop
from app.modules.zoning.models import Zone
from tests.test_plans_e2e import _create_user, _login, _seed_org_team


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed_draft_route(
    db: Session,
    *,
    org_name: str,
    n_stops: int = 3,
    published: bool = False,
) -> tuple[DailyRoute, RouteRevision, list[RouteStop], RouteMetric]:
    org, team = _seed_org_team(db, name=org_name)
    planner = _create_user(db, organization=org, role="planner")
    identity_service.set_current_organization_context(db, organization_id=org.id)
    zone = Zone(organization_id=org.id, name=f"Zona {org_name}", kind="urban")
    patients = [
        Patient(
            organization_id=org.id,
            external_ref=f"RO-{org_name}-{index}",
            display_ref=f"Paciente {index}",
        )
        for index in range(1, n_stops + 1)
    ]
    db.add_all([zone, *patients])
    db.flush()
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period="2026-09",
        created_by=planner.id,
    )
    db.add(plan)
    db.flush()
    route = DailyRoute(
        organization_id=org.id,
        plan_id=plan.id,
        zone_id=zone.id,
        service_date=date(2026, 9, 8),
        assignee_id=planner.id,
    )
    db.add(route)
    db.flush()
    revision = RouteRevision(
        organization_id=org.id,
        route_id=route.id,
        revision=1,
        status="published" if published else "draft",
        published_at=datetime.now(UTC) if published else None,
        created_by=planner.id,
    )
    db.add(revision)
    db.flush()
    route.current_revision = revision.id
    stops = [
        RouteStop(
            revision_id=revision.id,
            organization_id=org.id,
            patient_id=patient.id,
            sequence=index,
        )
        for index, patient in enumerate(patients, start=1)
    ]
    db.add_all(stops)
    metric = RouteMetric(
        revision_id=revision.id,
        organization_id=org.id,
        variant="optimized",
        distance_m=4200,
        travel_seconds=780,
        service_seconds=120,
        estimated_cost=3.5,
        calculation_json={"source": "osrm"},
    )
    db.add(metric)
    db.commit()
    return route, revision, stops, metric


def _auth_headers(
    client: TestClient, db: Session, *, org_id: uuid.UUID, role: str
) -> dict[str, str]:
    identity_service.set_current_organization_context(db, organization_id=org_id)
    org = db.get(Organization, org_id)
    assert org is not None
    user = _create_user(db, organization=org, role=role)
    token = _login(client, user)
    return {"Authorization": f"Bearer {token}"}


def _planner_headers_for_assignee(
    client: TestClient, db: Session, route: DailyRoute
) -> dict[str, str]:
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    planner = db.get(User, route.assignee_id)
    assert planner is not None
    token = _login(client, planner)
    return {"Authorization": f"Bearer {token}"}


def _reorder(
    client: TestClient,
    *,
    route_id: uuid.UUID,
    org_id: uuid.UUID,
    revision_id: uuid.UUID,
    ordered_stop_ids: list[uuid.UUID],
    headers: dict[str, str],
    version: int = 1,
    if_match: str | None = None,
) -> object:
    request_headers = dict(headers)
    request_headers["If-Match"] = if_match if if_match is not None else f'"{version}"'
    return client.patch(
        f"/api/v1/routes/{route_id}/stops/order",
        params={"organization_id": str(org_id)},
        json={
            "revision_id": str(revision_id),
            "ordered_stop_ids": [str(stop_id) for stop_id in ordered_stop_ids],
        },
        headers=request_headers,
    )


def test_reorder_stops_changes_sequences_and_marks_metrics_stale(
    client: TestClient, db_session: Session
) -> None:
    route, revision, stops, _metric = _seed_draft_route(db_session, org_name="reorder-ok")
    org_id = route.organization_id
    route_id = route.id
    revision_id = revision.id
    original_ids = [stop.id for stop in stops]
    reversed_ids = list(reversed(original_ids))
    headers = _planner_headers_for_assignee(client, db_session, route)

    response = _reorder(
        client,
        route_id=route_id,
        org_id=org_id,
        revision_id=revision_id,
        ordered_stop_ids=reversed_ids,
        headers=headers,
        version=1,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route_id"] == str(route_id)
    assert body["revision_id"] == str(revision_id)
    assert body["version"] == 2
    assert body["metrics_pending"] is True
    assert [item["id"] for item in body["stops"]] == [str(stop_id) for stop_id in reversed_ids]
    assert [item["sequence"] for item in body["stops"]] == [1, 2, 3]
    assert response.headers["etag"] == '"2"'

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    db_session.expire_all()
    persisted = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == revision_id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert [stop.id for stop in persisted] == reversed_ids
    assert [stop.sequence for stop in persisted] == [1, 2, 3]
    assert all(stop.version == 2 for stop in persisted)

    metric = (
        db_session.query(RouteMetric)
        .filter(RouteMetric.revision_id == revision_id, RouteMetric.variant == "optimized")
        .one()
    )
    assert metric.calculation_json["stale"] is True
    assert metric.calculation_json["source"] == "osrm"
    assert metric.travel_seconds == 780

    refreshed = db_session.get(DailyRoute, route_id)
    assert refreshed is not None
    assert refreshed.version == 2


def test_reorder_if_match_mismatch_409(client: TestClient, db_session: Session) -> None:
    route, revision, stops, _metric = _seed_draft_route(db_session, org_name="reorder-if-match")
    org_id = route.organization_id
    headers = _planner_headers_for_assignee(client, db_session, route)
    ordered = list(reversed([stop.id for stop in stops]))

    missing = client.patch(
        f"/api/v1/routes/{route.id}/stops/order",
        params={"organization_id": str(org_id)},
        json={
            "revision_id": str(revision.id),
            "ordered_stop_ids": [str(stop_id) for stop_id in ordered],
        },
        headers=headers,
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "IF_MATCH_REQUIRED"

    stale = _reorder(
        client,
        route_id=route.id,
        org_id=org_id,
        revision_id=revision.id,
        ordered_stop_ids=ordered,
        headers=headers,
        if_match='"0"',
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "ROUTE_VERSION_CONFLICT"

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    db_session.expire_all()
    persisted = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == revision.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert [stop.id for stop in persisted] == [stop.id for stop in stops]
    metric = db_session.query(RouteMetric).filter(RouteMetric.revision_id == revision.id).one()
    assert metric.calculation_json.get("stale") is not True
    refreshed = db_session.get(DailyRoute, route.id)
    assert refreshed is not None
    assert refreshed.version == 1


def test_reorder_published_revision_409(client: TestClient, db_session: Session) -> None:
    route, revision, stops, _metric = _seed_draft_route(
        db_session, org_name="reorder-published", published=True
    )
    org_id = route.organization_id
    headers = _planner_headers_for_assignee(client, db_session, route)
    ordered = list(reversed([stop.id for stop in stops]))

    response = _reorder(
        client,
        route_id=route.id,
        org_id=org_id,
        revision_id=revision.id,
        ordered_stop_ids=ordered,
        headers=headers,
        version=1,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "REVISION_PUBLISHED"

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    db_session.expire_all()
    persisted = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == revision.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert [stop.id for stop in persisted] == [stop.id for stop in stops]
    metric = db_session.query(RouteMetric).filter(RouteMetric.revision_id == revision.id).one()
    assert metric.calculation_json.get("stale") is not True


def test_reorder_rejects_non_permutation_and_field_role(
    client: TestClient, db_session: Session
) -> None:
    route, revision, stops, _metric = _seed_draft_route(db_session, org_name="reorder-perm")
    org_id = route.organization_id
    headers = _planner_headers_for_assignee(client, db_session, route)
    incomplete = [stops[0].id]

    bad = _reorder(
        client,
        route_id=route.id,
        org_id=org_id,
        revision_id=revision.id,
        ordered_stop_ids=incomplete,
        headers=headers,
        version=1,
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "STOP_ORDER_NOT_PERMUTATION"

    field_headers = _auth_headers(client, db_session, org_id=org_id, role="field")
    forbidden = _reorder(
        client,
        route_id=route.id,
        org_id=org_id,
        revision_id=revision.id,
        ordered_stop_ids=list(reversed([stop.id for stop in stops])),
        headers=field_headers,
        version=1,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ROLE"
