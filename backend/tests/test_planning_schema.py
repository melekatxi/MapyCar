"""Esquema de monthly_plans/daily_routes: UNIQUE, CHECK y FK tenant-safe.

Ref: 2.BE.8, diseño 6.1-6.2.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.identity.models import Organization, Team, User, UserMembership
from app.modules.notifications.models import OutboxEvent
from app.modules.planning.models import DailyRoute, MonthlyPlan
from app.modules.zoning.models import Zone


def _set_org(db: Session, organization_id: uuid.UUID) -> None:
    db.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
        {"org_id": str(organization_id)},
    )


def _seed_org(db: Session, suffix: str) -> tuple[Organization, Team, User, Zone]:
    org = Organization(name=f"Planning Schema Org {suffix}")
    db.add(org)
    db.flush()
    _set_org(db, org.id)
    team = Team(organization_id=org.id, name=f"Equipo {suffix}")
    user = User(
        email_normalized=f"planner-{suffix}-{uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Planificador {suffix}",
    )
    db.add_all([team, user])
    db.flush()
    db.add(UserMembership(organization_id=org.id, user_id=user.id, role="planner"))
    zone = Zone(organization_id=org.id, name=f"Zona {suffix}", kind="urban")
    db.add(zone)
    db.flush()
    return org, team, user, zone


def test_monthly_plans_unique_org_team_period_version(db_session: Session) -> None:
    org, team, user, _zone = _seed_org(db_session, "uniq")
    db_session.add(
        MonthlyPlan(
            organization_id=org.id,
            team_id=team.id,
            period="2026-09",
            version=1,
            created_by=user.id,
        )
    )
    db_session.commit()

    db_session.add(
        MonthlyPlan(
            organization_id=org.id,
            team_id=team.id,
            period="2026-09",
            version=1,
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    _set_org(db_session, org.id)
    db_session.add(
        MonthlyPlan(
            organization_id=org.id,
            team_id=team.id,
            period="2026-09",
            version=2,
            created_by=user.id,
        )
    )
    db_session.commit()


def test_monthly_plan_status_check_rejects_invalid(db_session: Session) -> None:
    org, team, user, _zone = _seed_org(db_session, "status")
    db_session.add(
        MonthlyPlan(
            organization_id=org.id,
            team_id=team.id,
            period="2026-09",
            status="validated",
            created_by=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_monthly_plan_rejects_cross_org_team(db_session: Session) -> None:
    org_a, _team_a, user_a, _zone_a = _seed_org(db_session, "fk-a")
    _org_b, team_b, _user_b, _zone_b = _seed_org(db_session, "fk-b")
    team_b_id = team_b.id

    _set_org(db_session, org_a.id)
    db_session.add(
        MonthlyPlan(
            organization_id=org_a.id,
            team_id=team_b_id,
            period="2026-09",
            created_by=user_a.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_daily_routes_unique_plan_date_zone_assignee(db_session: Session) -> None:
    org, team, user, zone = _seed_org(db_session, "route-uniq")
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period="2026-09",
        created_by=user.id,
    )
    db_session.add(plan)
    db_session.flush()

    db_session.add(
        DailyRoute(
            organization_id=org.id,
            plan_id=plan.id,
            zone_id=zone.id,
            service_date=date(2026, 9, 1),
            assignee_id=user.id,
        )
    )
    db_session.commit()

    _set_org(db_session, org.id)
    db_session.add(
        DailyRoute(
            organization_id=org.id,
            plan_id=plan.id,
            zone_id=zone.id,
            service_date=date(2026, 9, 1),
            assignee_id=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_daily_route_allows_same_day_different_assignee(db_session: Session) -> None:
    org, team, user, zone = _seed_org(db_session, "route-ok")
    other = User(
        email_normalized=f"field-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Visitador",
    )
    db_session.add(other)
    db_session.flush()
    db_session.add(UserMembership(organization_id=org.id, user_id=other.id, role="field"))
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period="2026-09",
        created_by=user.id,
    )
    db_session.add(plan)
    db_session.flush()

    db_session.add_all(
        [
            DailyRoute(
                organization_id=org.id,
                plan_id=plan.id,
                zone_id=zone.id,
                service_date=date(2026, 9, 2),
                assignee_id=user.id,
            ),
            DailyRoute(
                organization_id=org.id,
                plan_id=plan.id,
                zone_id=zone.id,
                service_date=date(2026, 9, 2),
                assignee_id=other.id,
            ),
        ]
    )
    db_session.commit()


def test_daily_route_status_check_rejects_invalid(db_session: Session) -> None:
    org, team, user, zone = _seed_org(db_session, "route-status")
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period="2026-09",
        created_by=user.id,
    )
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        DailyRoute(
            organization_id=org.id,
            plan_id=plan.id,
            zone_id=zone.id,
            service_date=date(2026, 9, 3),
            assignee_id=user.id,
            status="assigned",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_daily_route_rejects_cross_org_zone(db_session: Session) -> None:
    org_a, team_a, user_a, _zone_a = _seed_org(db_session, "zone-a")
    _org_b, _team_b, _user_b, zone_b = _seed_org(db_session, "zone-b")
    zone_b_id = zone_b.id

    _set_org(db_session, org_a.id)
    plan = MonthlyPlan(
        organization_id=org_a.id,
        team_id=team_a.id,
        period="2026-09",
        created_by=user_a.id,
    )
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        DailyRoute(
            organization_id=org_a.id,
            plan_id=plan.id,
            zone_id=zone_b_id,
            service_date=date(2026, 9, 4),
            assignee_id=user_a.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_daily_route_rejects_assignee_without_org_membership(db_session: Session) -> None:
    org, team, user, zone = _seed_org(db_session, "assignee")
    outsider = User(
        email_normalized=f"outsider-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Ajeno",
    )
    db_session.add(outsider)
    db_session.flush()
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period="2026-09",
        created_by=user.id,
    )
    db_session.add(plan)
    db_session.flush()
    db_session.add(
        DailyRoute(
            organization_id=org.id,
            plan_id=plan.id,
            zone_id=zone.id,
            service_date=date(2026, 9, 5),
            assignee_id=outsider.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_daily_route_current_revision_is_nullable(db_session: Session) -> None:
    org, team, user, zone = _seed_org(db_session, "rev-null")
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period="2026-09",
        created_by=user.id,
    )
    db_session.add(plan)
    db_session.flush()
    route = DailyRoute(
        organization_id=org.id,
        plan_id=plan.id,
        zone_id=zone.id,
        service_date=date(2026, 9, 6),
        assignee_id=user.id,
    )
    db_session.add(route)
    db_session.commit()

    assert route.current_revision is None


def test_planning_btree_indexes_exist(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            """
            SELECT tablename, indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename IN ('monthly_plans', 'daily_routes')
            """
        )
    ).fetchall()
    names = {(row[0], row[1]) for row in rows}
    assert ("monthly_plans", "uq_monthly_plans_org_team_period_version") in names
    assert ("monthly_plans", "ix_monthly_plans_org_period_status") in names
    assert ("daily_routes", "uq_daily_routes_plan_date_zone_assignee") in names
    assert ("daily_routes", "ix_daily_routes_date_assignee_status") in names
    rows = db_session.execute(
        text(
            """
            SELECT tablename, indexname
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'outbox_events'
            """
        )
    ).fetchall()
    outbox_names = {(row[0], row[1]) for row in rows}
    assert ("outbox_events", "uq_outbox_events_id_org") in outbox_names
    assert ("outbox_events", "ix_outbox_events_unprocessed") in outbox_names


def test_outbox_events_processed_at_nullable(db_session: Session) -> None:
    org, team, user, _zone = _seed_org(db_session, "outbox-null")
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period="2026-09",
        created_by=user.id,
    )
    db_session.add(plan)
    db_session.flush()
    event = OutboxEvent(
        organization_id=org.id,
        event_type="plan.published",
        resource_type="monthly_plan",
        resource_id=plan.id,
        payload_json={"plan_id": str(plan.id)},
    )
    db_session.add(event)
    db_session.commit()

    assert event.processed_at is None
    row = db_session.execute(
        text(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = 'outbox_events'
            """
        )
    ).one()
    assert row[0] is True
    assert row[1] is True
