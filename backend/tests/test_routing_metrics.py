"""Métricas original vs optimizada sobre la misma matriz. Ref: 3.BE.6, RF-18, 4.BE.3."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.adapters.router.interface import Coordinate
from app.modules.identity.models import Organization, Team, User, UserMembership
from app.modules.imports.models import Patient
from app.modules.planning.models import DailyRoute, MonthlyPlan
from app.modules.routing.matrix import ComputedMatrix
from app.modules.routing.metrics import (
    build_metrics,
    metrics_for_order,
    metrics_from_reports,
    persist_metrics,
)
from app.modules.routing.models import RouteMetric, RouteRevision
from app.modules.zoning.models import Zone


def _asymmetric_matrix() -> ComputedMatrix:
    # Arcos i→j = 10*i + j (diagonal 0): original y reverso no coinciden.
    durations = [
        [0.0, 10.0, 20.0, 30.0],
        [1.0, 0.0, 12.0, 40.0],
        [2.0, 50.0, 0.0, 3.0],
        [4.0, 5.0, 6.0, 0.0],
    ]
    distances = [
        [0.0, 100.0, 200.0, 300.0],
        [10.0, 0.0, 120.0, 400.0],
        [20.0, 500.0, 0.0, 30.0],
        [40.0, 50.0, 60.0, 0.0],
    ]
    return ComputedMatrix(
        durations_seconds=durations,
        distances_meters=distances,
        matrix_hash="test-matrix-hash",
        profile="driving",
        dataset_version="dev",
        from_cache=False,
        coordinates=(
            Coordinate(43.26, -2.93),
            Coordinate(43.27, -2.94),
            Coordinate(43.28, -2.95),
            Coordinate(43.26, -2.93),
        ),
    )


def test_metrics_for_order_sums_arcs_and_service() -> None:
    matrix = _asymmetric_matrix()
    totals = metrics_for_order(
        matrix.durations_seconds,
        matrix.distances_meters,
        [0, 1, 2, 3],
        service_minutes=[5, 7],
    )
    # 0→1 (10 / 100) + 1→2 (12 / 120) + 2→3 (3 / 30)
    assert totals["travel_seconds"] == 25
    assert totals["distance_m"] == 250
    assert totals["service_seconds"] == (5 + 7) * 60


def test_build_metrics_share_matrix_hash_and_differ_on_asymmetric_order() -> None:
    matrix = _asymmetric_matrix()
    original_order = [0, 1, 2, 3]
    reversed_order = [0, 2, 1, 3]
    rows = build_metrics(
        uuid.uuid4(),
        matrix,
        original_order,
        reversed_order,
        organization_id=uuid.uuid4(),
        service_minutes=[8, 4],
    )
    by_variant = {row["variant"]: row for row in rows}
    assert set(by_variant) == {"original", "optimized"}
    original = by_variant["original"]
    optimized = by_variant["optimized"]
    assert original["calculation_json"]["matrix_hash"] == matrix.matrix_hash
    assert optimized["calculation_json"]["matrix_hash"] == matrix.matrix_hash
    assert (
        original["calculation_json"]["matrix_hash"] == optimized["calculation_json"]["matrix_hash"]
    )
    assert original["travel_seconds"] == 25
    assert optimized["travel_seconds"] == 20 + 50 + 40
    assert original["travel_seconds"] != optimized["travel_seconds"]
    assert original["distance_m"] != optimized["distance_m"]
    assert original["service_seconds"] == optimized["service_seconds"] == (8 + 4) * 60


def _set_org(db: Session, organization_id: uuid.UUID) -> None:
    from sqlalchemy import text

    db.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
        {"org_id": str(organization_id)},
    )


def test_persist_metrics_writes_original_and_optimized_rows(db_session: Session) -> None:
    org = Organization(name="Metrics Org")
    db_session.add(org)
    db_session.flush()
    _set_org(db_session, org.id)
    team = Team(organization_id=org.id, name="Equipo métricas")
    user = User(
        email_normalized=f"metrics-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Planificador",
    )
    db_session.add_all([team, user])
    db_session.flush()
    db_session.add(UserMembership(organization_id=org.id, user_id=user.id, role="planner"))
    zone = Zone(organization_id=org.id, name="Zona métricas", kind="urban")
    patient = Patient(organization_id=org.id, external_ref="M-1", display_ref="Paciente")
    db_session.add_all([zone, patient])
    db_session.flush()
    plan = MonthlyPlan(
        organization_id=org.id, team_id=team.id, period="2026-09", created_by=user.id
    )
    db_session.add(plan)
    db_session.flush()
    route = DailyRoute(
        organization_id=org.id,
        plan_id=plan.id,
        zone_id=zone.id,
        service_date=date(2026, 9, 1),
        assignee_id=user.id,
    )
    db_session.add(route)
    db_session.flush()
    revision = RouteRevision(
        organization_id=org.id, route_id=route.id, revision=1, created_by=user.id
    )
    db_session.add(revision)
    db_session.flush()

    rows = build_metrics(
        revision.id,
        _asymmetric_matrix(),
        [0, 1, 2, 3],
        [0, 2, 1, 3],
        organization_id=org.id,
        service_minutes=[5, 5],
    )
    persist_metrics(db_session, rows)
    db_session.commit()

    stored = db_session.query(RouteMetric).order_by(RouteMetric.variant).all()
    assert {m.variant for m in stored} == {"optimized", "original"}
    hashes = {m.calculation_json["matrix_hash"] for m in stored}
    assert hashes == {"test-matrix-hash"}
    by_variant = {m.variant: m for m in stored}
    assert by_variant["original"].travel_seconds != by_variant["optimized"].travel_seconds
    assert by_variant["original"].service_seconds == by_variant["optimized"].service_seconds


def _reported(**kwargs: object) -> SimpleNamespace:
    values = {
        "id": uuid.uuid4(),
        "status": "pending",
        "completed_at": None,
        "service_minutes": 10,
        "sequence": 1,
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def test_metrics_from_reports_span_minus_service_skips_do_not_travel() -> None:
    t0 = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    totals = metrics_from_reports(
        [
            _reported(status="completed", completed_at=t0, sequence=1),
            _reported(
                status="completed",
                completed_at=t0 + timedelta(minutes=40),
                sequence=2,
            ),
            _reported(
                status="skipped",
                completed_at=t0 + timedelta(hours=2),
                sequence=3,
            ),
        ],
        planned_travel_seconds=1800,
        planned_cost=9.0,
    )
    assert totals["service_seconds"] == 1200
    assert totals["travel_seconds"] == 1200
    assert totals["distance_m"] == 0
    assert totals["estimated_cost"] == 6.0
    assert totals["calculation_json"]["skipped"] == 1
    assert totals["calculation_json"]["distance_source"] == "unavailable"


def test_metrics_from_reports_failed_is_visited_without_service() -> None:
    t0 = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
    totals = metrics_from_reports(
        [
            _reported(status="failed", completed_at=t0, sequence=1),
            _reported(
                status="completed",
                completed_at=t0 + timedelta(minutes=30),
                sequence=2,
            ),
        ]
    )
    assert totals["service_seconds"] == 600
    assert totals["travel_seconds"] == 1200
    assert totals["calculation_json"]["failed"] == 1
    assert totals["calculation_json"]["completed"] == 1
