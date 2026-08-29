"""Verifica que RLS impide leer filas de otra organización. Ref: 0.DATA.3, RNF-06."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.identity.models import Organization, Team


def _set_org(db: Session, organization_id) -> None:
    db.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
        {"org_id": str(organization_id)},
    )


def test_session_without_org_context_sees_no_rows(db_session: Session) -> None:
    org = Organization(name="Org A")
    db_session.add(org)
    db_session.flush()
    _set_org(db_session, org.id)
    db_session.add(Team(organization_id=org.id, name="Equipo Norte"))
    db_session.commit()

    db_session.execute(text("RESET app.current_organization_id"))
    visible_teams = db_session.query(Team).all()

    assert visible_teams == []


def test_organization_a_cannot_read_rows_of_organization_b(db_session: Session) -> None:
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    _set_org(db_session, org_a.id)
    db_session.add(Team(organization_id=org_a.id, name="Equipo A"))
    db_session.commit()

    _set_org(db_session, org_b.id)
    db_session.add(Team(organization_id=org_b.id, name="Equipo B"))
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible_names = {t.name for t in db_session.query(Team).all()}

    assert visible_names == {"Equipo A"}
