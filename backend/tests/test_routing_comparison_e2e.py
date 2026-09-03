"""E2E de GET /routes/{id}/comparison: original vs optimized y ahorro.

Ref: 3.BE.8, RF-18, diseño sección 8.5. 409 si faltan métricas o están stale.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.routing.models import RouteMetric, RouteRevision
from tests.test_routing_order_e2e import (
    _auth_headers,
    _planner_headers_for_assignee,
    _reorder,
    _seed_draft_route,
)

_ORIGINAL = {
    "distance_m": 5000,
    "travel_seconds": 1000,
    "service_seconds": 120,
    "estimated_cost": 5.0,
}


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _add_original_metric(
    db: Session,
    revision: RouteRevision,
    *,
    stale: bool = False,
) -> RouteMetric:
    identity_service.set_current_organization_context(db, organization_id=revision.organization_id)
    payload: dict[str, object] = {"source": "osrm"}
    if stale:
        payload["stale"] = True
    metric = RouteMetric(
        revision_id=revision.id,
        organization_id=revision.organization_id,
        variant="original",
        distance_m=_ORIGINAL["distance_m"],
        travel_seconds=_ORIGINAL["travel_seconds"],
        service_seconds=_ORIGINAL["service_seconds"],
        estimated_cost=_ORIGINAL["estimated_cost"],
        calculation_json=payload,
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return metric


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


def test_comparison_returns_original_optimized_and_savings(
    client: TestClient, db_session: Session
) -> None:
    route, revision, _stops, optimized = _seed_draft_route(db_session, org_name="cmp-ok")
    original = _add_original_metric(db_session, revision)
    headers = _planner_headers_for_assignee(client, db_session, route)

    response = _get_comparison(
        client, route_id=route.id, org_id=route.organization_id, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["original"] == {
        "distance_m": original.distance_m,
        "travel_seconds": original.travel_seconds,
        "service_seconds": original.service_seconds,
        "estimated_cost": original.estimated_cost,
    }
    assert body["optimized"] == {
        "distance_m": optimized.distance_m,
        "travel_seconds": optimized.travel_seconds,
        "service_seconds": optimized.service_seconds,
        "estimated_cost": optimized.estimated_cost,
    }
    saved_distance = original.distance_m - optimized.distance_m
    saved_travel = original.travel_seconds - optimized.travel_seconds
    saved_cost = original.estimated_cost - optimized.estimated_cost
    assert body["savings"]["distance_m"] == saved_distance
    assert body["savings"]["travel_seconds"] == saved_travel
    assert body["savings"]["estimated_cost"] == pytest.approx(saved_cost)
    assert body["savings"]["travel_seconds_pct"] == pytest.approx(22.0)


def test_comparison_stale_metrics_409(client: TestClient, db_session: Session) -> None:
    route, revision, _stops, _optimized = _seed_draft_route(db_session, org_name="cmp-flag")
    _add_original_metric(db_session, revision, stale=True)
    headers = _planner_headers_for_assignee(client, db_session, route)

    stale = _get_comparison(
        client, route_id=route.id, org_id=route.organization_id, headers=headers
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "METRICS_STALE"


def test_comparison_stale_after_reorder_409(client: TestClient, db_session: Session) -> None:
    route, revision, stops, _optimized = _seed_draft_route(db_session, org_name="cmp-stale")
    _add_original_metric(db_session, revision)
    org_id = route.organization_id
    headers = _planner_headers_for_assignee(client, db_session, route)

    ok = _get_comparison(client, route_id=route.id, org_id=org_id, headers=headers)
    assert ok.status_code == 200

    reversed_ids = list(reversed([stop.id for stop in stops]))
    patched = _reorder(
        client,
        route_id=route.id,
        org_id=org_id,
        revision_id=revision.id,
        ordered_stop_ids=reversed_ids,
        headers=headers,
        version=1,
    )
    assert patched.status_code == 200

    stale = _get_comparison(client, route_id=route.id, org_id=org_id, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["code"] == "METRICS_STALE"


def test_comparison_missing_metrics_409(client: TestClient, db_session: Session) -> None:
    route, _revision, _stops, _optimized = _seed_draft_route(db_session, org_name="cmp-missing")
    headers = _planner_headers_for_assignee(client, db_session, route)

    response = _get_comparison(
        client, route_id=route.id, org_id=route.organization_id, headers=headers
    )
    assert response.status_code == 409
    assert response.json()["code"] == "METRICS_UNAVAILABLE"


def test_comparison_rejects_field_role(client: TestClient, db_session: Session) -> None:
    route, revision, _stops, _optimized = _seed_draft_route(db_session, org_name="cmp-field")
    _add_original_metric(db_session, revision)
    field_headers = _auth_headers(client, db_session, org_id=route.organization_id, role="field")

    forbidden = _get_comparison(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=field_headers,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ROLE"
