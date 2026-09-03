"""Verifica que RLS impide leer monthly_plans/daily_routes de otra organización.

Ref: 2.BE.8, 0.DATA.3, RNF-06.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import text
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


def _seed_plan(
    db: Session, *, suffix: str, period: str
) -> tuple[Organization, MonthlyPlan, Zone, User]:
    org = Organization(name=f"Planning RLS Org {suffix}")
    db.add(org)
    db.flush()
    _set_org(db, org.id)
    team = Team(organization_id=org.id, name=f"Equipo {suffix}")
    user = User(
        email_normalized=f"rls-{suffix}-{uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Planificador {suffix}",
    )
    db.add_all([team, user])
    db.flush()
    db.add(UserMembership(organization_id=org.id, user_id=user.id, role="planner"))
    zone = Zone(organization_id=org.id, name=f"Zona {suffix}", kind="urban")
    db.add(zone)
    db.flush()
    plan = MonthlyPlan(
        organization_id=org.id,
        team_id=team.id,
        period=period,
        created_by=user.id,
    )
    db.add(plan)
    db.flush()
    return org, plan, zone, user


def test_organization_a_cannot_read_monthly_plans_of_organization_b(db_session: Session) -> None:
    _seed_plan(db_session, suffix="A", period="2026-08")
    db_session.commit()
    _seed_plan(db_session, suffix="B", period="2026-09")
    db_session.commit()

    org_a = db_session.query(Organization).filter(Organization.name == "Planning RLS Org A").one()
    _set_org(db_session, org_a.id)
    visible_periods = {p.period for p in db_session.query(MonthlyPlan).all()}

    assert visible_periods == {"2026-08"}


def test_organization_a_cannot_read_daily_routes_of_organization_b(db_session: Session) -> None:
    org_a, plan_a, zone_a, user_a = _seed_plan(db_session, suffix="RA", period="2026-08")
    db_session.add(
        DailyRoute(
            organization_id=org_a.id,
            plan_id=plan_a.id,
            zone_id=zone_a.id,
            service_date=date(2026, 8, 10),
            assignee_id=user_a.id,
            status="draft",
        )
    )
    db_session.commit()

    org_b, plan_b, zone_b, user_b = _seed_plan(db_session, suffix="RB", period="2026-09")
    db_session.add(
        DailyRoute(
            organization_id=org_b.id,
            plan_id=plan_b.id,
            zone_id=zone_b.id,
            service_date=date(2026, 9, 10),
            assignee_id=user_b.id,
            status="ready",
        )
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible_statuses = {r.status for r in db_session.query(DailyRoute).all()}

    assert visible_statuses == {"draft"}


def test_session_without_org_context_sees_no_plans_or_routes(db_session: Session) -> None:
    org, plan, zone, user = _seed_plan(db_session, suffix="Empty", period="2026-10")
    db_session.add(
        DailyRoute(
            organization_id=org.id,
            plan_id=plan.id,
            zone_id=zone.id,
            service_date=date(2026, 10, 1),
            assignee_id=user.id,
        )
    )
    db_session.add(
        OutboxEvent(
            organization_id=org.id,
            event_type="plan.published",
            resource_type="monthly_plan",
            resource_id=plan.id,
            payload_json={"plan_id": str(plan.id)},
        )
    )
    db_session.commit()

    db_session.execute(text("RESET app.current_organization_id"))
    assert db_session.query(MonthlyPlan).all() == []
    assert db_session.query(DailyRoute).all() == []
    assert db_session.query(OutboxEvent).all() == []


def test_organization_a_cannot_read_outbox_of_organization_b(db_session: Session) -> None:
    org_a, plan_a, _zone_a, _user_a = _seed_plan(db_session, suffix="OA", period="2026-08")
    db_session.add(
        OutboxEvent(
            organization_id=org_a.id,
            event_type="plan.published",
            resource_type="monthly_plan",
            resource_id=plan_a.id,
            payload_json={"plan_id": str(plan_a.id)},
        )
    )
    db_session.commit()

    org_b, plan_b, _zone_b, _user_b = _seed_plan(db_session, suffix="OB", period="2026-09")
    db_session.add(
        OutboxEvent(
            organization_id=org_b.id,
            event_type="plan.published",
            resource_type="monthly_plan",
            resource_id=plan_b.id,
            payload_json={"plan_id": str(plan_b.id)},
        )
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible = {str(event.resource_id) for event in db_session.query(OutboxEvent).all()}
    assert visible == {str(plan_a.id)}
