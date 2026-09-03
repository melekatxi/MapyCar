"""RLS de route_revisions/stops/metrics: aislamiento por organization_id.

Ref: 3.BE.1, 0.DATA.3, RNF-06.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
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


def _seed_revision(
    db: Session, *, suffix: str
) -> tuple[Organization, RouteRevision, Patient]:
    org = Organization(name=f"Routing RLS Org {suffix}")
    db.add(org)
    db.flush()
    _set_org(db, org.id)
    team = Team(organization_id=org.id, name=f"Equipo {suffix}")
    user = User(
        email_normalized=f"rls-routing-{suffix}-{uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Planificador {suffix}",
    )
    db.add_all([team, user])
    db.flush()
    db.add(UserMembership(organization_id=org.id, user_id=user.id, role="planner"))
    zone = Zone(organization_id=org.id, name=f"Zona {suffix}", kind="urban")
    patient = Patient(
        organization_id=org.id,
        external_ref=f"RLS-{suffix}",
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
        service_date=date(2026, 9, 8),
        assignee_id=user.id,
    )
    db.add(route)
    db.flush()
    revision = RouteRevision(
        organization_id=org.id,
        route_id=route.id,
        revision=1,
        created_by=user.id,
    )
    db.add(revision)
    db.flush()
    return org, revision, patient


def test_organization_a_cannot_read_revisions_of_organization_b(db_session: Session) -> None:
    org_a, revision_a, _patient_a = _seed_revision(db_session, suffix="A")
    revision_a_id = revision_a.id
    db_session.commit()
    _org_b, revision_b, _patient_b = _seed_revision(db_session, suffix="B")
    revision_b_id = revision_b.id
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible = {row.id for row in db_session.query(RouteRevision).all()}
    assert visible == {revision_a_id}
    assert revision_b_id not in visible


def test_organization_a_cannot_read_stops_or_metrics_of_organization_b(
    db_session: Session,
) -> None:
    org_a, revision_a, patient_a = _seed_revision(db_session, suffix="SA")
    db_session.add(
        RouteStop(
            revision_id=revision_a.id,
            organization_id=org_a.id,
            patient_id=patient_a.id,
            sequence=1,
        )
    )
    db_session.add(
        RouteMetric(
            revision_id=revision_a.id,
            organization_id=org_a.id,
            variant="original",
            distance_m=10,
        )
    )
    db_session.commit()

    org_b, revision_b, patient_b = _seed_revision(db_session, suffix="SB")
    db_session.add(
        RouteStop(
            revision_id=revision_b.id,
            organization_id=org_b.id,
            patient_id=patient_b.id,
            sequence=1,
        )
    )
    db_session.add(
        RouteMetric(
            revision_id=revision_b.id,
            organization_id=org_b.id,
            variant="optimized",
            distance_m=20,
        )
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    assert {s.revision_id for s in db_session.query(RouteStop).all()} == {revision_a.id}
    assert {m.variant for m in db_session.query(RouteMetric).all()} == {"original"}


def test_session_without_org_context_sees_no_routing_rows(db_session: Session) -> None:
    org, revision, patient = _seed_revision(db_session, suffix="Empty")
    db_session.add(
        RouteStop(
            revision_id=revision.id,
            organization_id=org.id,
            patient_id=patient.id,
            sequence=1,
        )
    )
    db_session.add(
        RouteMetric(
            revision_id=revision.id,
            organization_id=org.id,
            variant="actual",
        )
    )
    db_session.commit()

    db_session.execute(text("RESET app.current_organization_id"))
    assert db_session.query(RouteRevision).all() == []
    assert db_session.query(RouteStop).all() == []
    assert db_session.query(RouteMetric).all() == []


def test_routing_tables_have_force_rls(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname IN ('route_revisions', 'route_stops', 'route_metrics')
            """
        )
    ).fetchall()
    by_name = {row[0]: (row[1], row[2]) for row in rows}
    for table in ("route_revisions", "route_stops", "route_metrics"):
        assert by_name[table] == (True, True)
