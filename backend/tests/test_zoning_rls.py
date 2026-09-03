"""Verifica que RLS impide leer zones/zone_assignments de otra organización.

Ref: 2.BE.1, 0.DATA.3, RNF-06.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.identity.models import Organization
from app.modules.imports.models import Patient
from app.modules.zoning.models import Zone, ZoneAssignment, ZoneProposal


def _set_org(db: Session, organization_id: uuid.UUID) -> None:
    db.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
        {"org_id": str(organization_id)},
    )


def test_organization_a_cannot_read_zones_of_organization_b(db_session: Session) -> None:
    org_a = Organization(name="Zoning RLS Org A")
    org_b = Organization(name="Zoning RLS Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    _set_org(db_session, org_a.id)
    db_session.add(Zone(organization_id=org_a.id, name="Zona A", kind="urban"))
    db_session.commit()

    _set_org(db_session, org_b.id)
    db_session.add(Zone(organization_id=org_b.id, name="Zona B", kind="rural"))
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible_names = {z.name for z in db_session.query(Zone).all()}

    assert visible_names == {"Zona A"}


def test_organization_a_cannot_read_zone_assignments_of_organization_b(db_session: Session) -> None:
    org_a = Organization(name="Zoning RLS Assign Org A")
    org_b = Organization(name="Zoning RLS Assign Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    _set_org(db_session, org_a.id)
    patient_a = Patient(organization_id=org_a.id, external_ref="ZN-RLS-A", display_ref="Paciente A")
    zone_a = Zone(organization_id=org_a.id, name="Asignación A", kind="urban")
    db_session.add_all([patient_a, zone_a])
    db_session.flush()
    db_session.add(
        ZoneAssignment(
            organization_id=org_a.id,
            zone_id=zone_a.id,
            patient_id=patient_a.id,
            source="cluster",
        )
    )
    db_session.commit()

    _set_org(db_session, org_b.id)
    patient_b = Patient(organization_id=org_b.id, external_ref="ZN-RLS-B", display_ref="Paciente B")
    zone_b = Zone(organization_id=org_b.id, name="Asignación B", kind="rural")
    db_session.add_all([patient_b, zone_b])
    db_session.flush()
    db_session.add(
        ZoneAssignment(
            organization_id=org_b.id,
            zone_id=zone_b.id,
            patient_id=patient_b.id,
            source="postal",
        )
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible_sources = {a.source for a in db_session.query(ZoneAssignment).all()}

    assert visible_sources == {"cluster"}


def test_session_without_org_context_sees_no_zones(db_session: Session) -> None:
    org = Organization(name="Zoning RLS Empty Org")
    db_session.add(org)
    db_session.flush()
    _set_org(db_session, org.id)
    db_session.add(Zone(organization_id=org.id, name="Invisible", kind="mixed"))
    db_session.commit()

    db_session.execute(text("RESET app.current_organization_id"))
    assert db_session.query(Zone).all() == []
    assert db_session.query(ZoneAssignment).all() == []
    assert db_session.query(ZoneProposal).all() == []


def test_organization_a_cannot_read_zone_proposals_of_organization_b(db_session: Session) -> None:
    org_a = Organization(name="Zoning RLS Proposal Org A")
    org_b = Organization(name="Zoning RLS Proposal Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    _set_org(db_session, org_a.id)
    db_session.add(
        ZoneProposal(
            organization_id=org_a.id,
            status="succeeded",
            params_json={"max_visits": 8, "strategy": "auto"},
            result_json={"clusters": [], "outliers": [], "metrics": {}},
        )
    )
    db_session.commit()

    _set_org(db_session, org_b.id)
    db_session.add(
        ZoneProposal(
            organization_id=org_b.id,
            status="queued",
            params_json={"max_visits": 10, "strategy": "auto"},
            result_json={},
        )
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible_status = {p.status for p in db_session.query(ZoneProposal).all()}

    assert visible_status == {"succeeded"}
