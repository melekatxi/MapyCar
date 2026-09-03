"""Esquema de route_revisions/stops/metrics: UNIQUE, CHECK, GiST y FK tenant-safe.

Ref: 3.BE.1, diseño 6.1-6.2.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.identity.models import Organization, Team, User, UserMembership
from app.modules.imports.models import Patient
from app.modules.planning.models import DailyRoute, MonthlyPlan
from app.modules.routing.models import RouteMetric, RouteRevision, RouteStop
from app.modules.zoning.models import Zone


def _set_org(db: Session, organization_id: uuid.UUID) -> None:
    db.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
        {"org_id": str(organization_id)},
    )


def _seed_route(db: Session, suffix: str) -> tuple[Organization, User, DailyRoute, Patient]:
    org = Organization(name=f"Routing Schema Org {suffix}")
    db.add(org)
    db.flush()
    _set_org(db, org.id)
    team = Team(organization_id=org.id, name=f"Equipo {suffix}")
    user = User(
        email_normalized=f"routing-{suffix}-{uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Planificador {suffix}",
    )
    db.add_all([team, user])
    db.flush()
    db.add(UserMembership(organization_id=org.id, user_id=user.id, role="planner"))
    zone = Zone(organization_id=org.id, name=f"Zona {suffix}", kind="urban")
    patient = Patient(
        organization_id=org.id,
        external_ref=f"RS-{suffix}",
        display_ref=f"Paciente {suffix}",
    )
    db.add_all([zone, patient])
    db.flush()
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period="2026-09",
        created_by=user.id,
    )
    db.add(plan)
    db.flush()
    route = DailyRoute(
        organization_id=org.id,
        plan_id=plan.id,
        zone_id=zone.id,
        service_date=date(2026, 9, 1),
        assignee_id=user.id,
    )
    db.add(route)
    db.flush()
    return org, user, route, patient


def test_route_revisions_unique_route_revision(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "uniq")
    db_session.add(
        RouteRevision(
            organization_id=org.id,
            route_id=route.id,
            revision=1,
            created_by=user.id,
        )
    )
    db_session.commit()

    _set_org(db_session, org.id)
    db_session.add(
        RouteRevision(
            organization_id=org.id,
            route_id=route.id,
            revision=1,
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    _set_org(db_session, org.id)
    db_session.add(
        RouteRevision(
            organization_id=org.id,
            route_id=route.id,
            revision=2,
            created_by=user.id,
        )
    )
    db_session.commit()


def test_route_revision_rejects_cross_org_route(db_session: Session) -> None:
    org_a, user_a, _route_a, _patient_a = _seed_route(db_session, "fk-a")
    _org_b, _user_b, route_b, _patient_b = _seed_route(db_session, "fk-b")
    route_b_id = route_b.id

    _set_org(db_session, org_a.id)
    db_session.add(
        RouteRevision(
            organization_id=org_a.id,
            route_id=route_b_id,
            revision=1,
            created_by=user_a.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_published_revision_requires_published_at(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "pub")
    db_session.commit()

    _set_org(db_session, org.id)
    db_session.add(
        RouteRevision(
            organization_id=org.id,
            route_id=route.id,
            revision=1,
            status="published",
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    _set_org(db_session, org.id)
    revision = RouteRevision(
        organization_id=org.id,
        route_id=route.id,
        revision=1,
        status="published",
        published_at=datetime.now(UTC),
        created_by=user.id,
    )
    db_session.add(revision)
    db_session.flush()
    route.current_revision = revision.id
    db_session.commit()
    assert route.current_revision == revision.id


def test_daily_route_current_revision_rejects_cross_org(db_session: Session) -> None:
    org_a, _user_a, route_a, _patient_a = _seed_route(db_session, "cur-a")
    org_b, user_b, route_b, _patient_b = _seed_route(db_session, "cur-b")
    revision_b = RouteRevision(
        organization_id=org_b.id,
        route_id=route_b.id,
        revision=1,
        created_by=user_b.id,
    )
    db_session.add(revision_b)
    db_session.flush()
    revision_b_id = revision_b.id
    db_session.commit()

    _set_org(db_session, org_a.id)
    route_a.current_revision = revision_b_id
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_route_stops_unique_revision_sequence_and_patient(db_session: Session) -> None:
    org, user, route, patient = _seed_route(db_session, "stop-uniq")
    other = Patient(
        organization_id=org.id,
        external_ref="RS-stop-uniq-2",
        display_ref="Paciente 2",
    )
    db_session.add(other)
    db_session.flush()
    revision = RouteRevision(
        organization_id=org.id,
        route_id=route.id,
        revision=1,
        created_by=user.id,
    )
    db_session.add(revision)
    db_session.flush()
    db_session.add(
        RouteStop(
            revision_id=revision.id,
            organization_id=org.id,
            patient_id=patient.id,
            sequence=1,
        )
    )
    db_session.commit()

    _set_org(db_session, org.id)
    db_session.add(
        RouteStop(
            revision_id=revision.id,
            organization_id=org.id,
            patient_id=other.id,
            sequence=1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    _set_org(db_session, org.id)
    db_session.add(
        RouteStop(
            revision_id=revision.id,
            organization_id=org.id,
            patient_id=patient.id,
            sequence=2,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    _set_org(db_session, org.id)
    db_session.add(
        RouteStop(
            revision_id=revision.id,
            organization_id=org.id,
            patient_id=other.id,
            sequence=2,
        )
    )
    db_session.commit()


def test_route_stop_window_must_be_ordered_when_both_set(db_session: Session) -> None:
    org, user, route, patient = _seed_route(db_session, "window")
    revision = RouteRevision(
        organization_id=org.id,
        route_id=route.id,
        revision=1,
        created_by=user.id,
    )
    db_session.add(revision)
    db_session.commit()

    _set_org(db_session, org.id)
    db_session.add(
        RouteStop(
            revision_id=revision.id,
            organization_id=org.id,
            patient_id=patient.id,
            sequence=1,
            window_start=time(12, 0),
            window_end=time(11, 0),
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    _set_org(db_session, org.id)
    db_session.add(
        RouteStop(
            revision_id=revision.id,
            organization_id=org.id,
            patient_id=patient.id,
            sequence=1,
            window_start=time(9, 0),
            window_end=time(10, 30),
        )
    )
    db_session.commit()


def test_route_stop_rejects_cross_org_patient(db_session: Session) -> None:
    org_a, user_a, route_a, _patient_a = _seed_route(db_session, "stop-a")
    _org_b, _user_b, _route_b, patient_b = _seed_route(db_session, "stop-b")
    patient_b_id = patient_b.id
    _set_org(db_session, org_a.id)
    revision = RouteRevision(
        organization_id=org_a.id,
        route_id=route_a.id,
        revision=1,
        created_by=user_a.id,
    )
    db_session.add(revision)
    db_session.flush()
    db_session.add(
        RouteStop(
            revision_id=revision.id,
            organization_id=org_a.id,
            patient_id=patient_b_id,
            sequence=1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_route_metrics_pk_revision_variant(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "metric")
    revision = RouteRevision(
        organization_id=org.id,
        route_id=route.id,
        revision=1,
        created_by=user.id,
    )
    db_session.add(revision)
    db_session.flush()
    db_session.add(
        RouteMetric(
            revision_id=revision.id,
            organization_id=org.id,
            variant="original",
            distance_m=1000,
            travel_seconds=120,
            service_seconds=60,
            estimated_cost=1.5,
        )
    )
    db_session.commit()

    _set_org(db_session, org.id)
    db_session.add(
        RouteMetric(
            revision_id=revision.id,
            organization_id=org.id,
            variant="original",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    _set_org(db_session, org.id)
    db_session.add(
        RouteMetric(
            revision_id=revision.id,
            organization_id=org.id,
            variant="optimized",
            distance_m=800,
        )
    )
    db_session.commit()


def test_route_metrics_variant_check_rejects_invalid(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "metric-ck")
    revision = RouteRevision(
        organization_id=org.id,
        route_id=route.id,
        revision=1,
        created_by=user.id,
    )
    db_session.add(revision)
    db_session.flush()
    db_session.add(
        RouteMetric(
            revision_id=revision.id,
            organization_id=org.id,
            variant="planned",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_route_stops_gist_index_exists(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'route_stops'
              AND indexdef ILIKE '%USING gist%'
            """
        )
    ).fetchall()
    names = {row[0] for row in rows}
    assert "idx_route_stops_location" in names


def test_route_stops_location_accepts_geography(db_session: Session) -> None:
    org, user, route, patient = _seed_route(db_session, "gist")
    revision = RouteRevision(
        organization_id=org.id,
        route_id=route.id,
        revision=1,
        created_by=user.id,
    )
    db_session.add(revision)
    db_session.flush()
    stop = RouteStop(
        revision_id=revision.id,
        organization_id=org.id,
        patient_id=patient.id,
        sequence=1,
        address_snapshot_ciphertext="",
        location="SRID=4326;POINT(-2.935 43.263)",
    )
    db_session.add(stop)
    db_session.commit()
    assert stop.location is not None


def test_routing_btree_indexes_exist(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            """
            SELECT tablename, indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('route_revisions', 'route_stops', 'route_metrics', 'daily_routes')
            """
        )
    ).fetchall()
    names = {(row[0], row[1]) for row in rows}
    assert ("route_revisions", "uq_route_revisions_route_revision") in names
    assert ("route_stops", "uq_route_stops_revision_sequence") in names
    assert ("route_stops", "uq_route_stops_revision_patient") in names
    assert ("daily_routes", "uq_daily_routes_id_org") in names
    assert ("route_metrics", "ix_route_metrics_revision_id") in names
