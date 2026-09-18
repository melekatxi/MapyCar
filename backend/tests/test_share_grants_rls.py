"""RLS de share_grants: aislamiento por organization_id.

Ref: 4.BE.5, 0.DATA.3, RNF-06.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.sharing.models import ShareGrant
from tests.test_routing_schema import _seed_route, _set_org


def test_organization_a_cannot_read_grants_of_organization_b(db_session: Session) -> None:
    org_a, user_a, route_a, _patient_a = _seed_route(db_session, "sg-A")
    db_session.add(
        ShareGrant(
            organization_id=org_a.id,
            route_id=route_a.id,
            subject_user_id=user_a.id,
            permission="view",
            created_by=user_a.id,
        )
    )
    db_session.commit()

    org_b, user_b, route_b, _patient_b = _seed_route(db_session, "sg-B")
    db_session.add(
        ShareGrant(
            organization_id=org_b.id,
            route_id=route_b.id,
            subject_user_id=user_b.id,
            permission="edit",
            created_by=user_b.id,
        )
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    rows = db_session.query(ShareGrant).all()
    assert {grant.organization_id for grant in rows} == {org_a.id}

    _set_org(db_session, org_b.id)
    rows = db_session.query(ShareGrant).all()
    assert {grant.organization_id for grant in rows} == {org_b.id}


def test_share_grants_hidden_without_org_context(db_session: Session) -> None:
    org, user, route, _patient = _seed_route(db_session, "sg-empty")
    db_session.add(
        ShareGrant(
            organization_id=org.id,
            route_id=route.id,
            subject_user_id=user.id,
            permission="view",
            created_by=user.id,
        )
    )
    db_session.commit()

    db_session.execute(text("RESET app.current_organization_id"))
    assert db_session.query(ShareGrant).all() == []


def test_share_grants_has_force_rls(db_session: Session) -> None:
    row = db_session.execute(
        text(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = 'share_grants'
            """
        )
    ).one()
    assert row == (True, True)
