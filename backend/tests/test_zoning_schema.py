"""Esquema de zones/zone_assignments: UNIQUE, CHECK, GiST y asignación vigente.

Ref: 2.BE.1, diseño 6.1-6.2.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.identity.models import Organization
from app.modules.imports.models import Patient
from app.modules.zoning.models import Zone, ZoneAssignment, ZoneProposal


def _set_org(db: Session, organization_id) -> None:
    db.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
        {"org_id": str(organization_id)},
    )


def test_zones_unique_name_per_organization(db_session: Session) -> None:
    org_a = Organization(name="Zoning Unique Org A")
    org_b = Organization(name="Zoning Unique Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    _set_org(db_session, org_a.id)
    db_session.add(Zone(organization_id=org_a.id, name="Norte", kind="urban"))
    db_session.commit()

    db_session.add(Zone(organization_id=org_a.id, name="Norte", kind="rural"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    _set_org(db_session, org_b.id)
    db_session.add(Zone(organization_id=org_b.id, name="Norte", kind="urban"))
    db_session.commit()


def test_zone_kind_check_rejects_invalid(db_session: Session) -> None:
    org = Organization(name="Zoning Kind Org")
    db_session.add(org)
    db_session.flush()
    _set_org(db_session, org.id)

    db_session.add(Zone(organization_id=org.id, name="Inválida", kind="suburban"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_zone_assignment_partial_unique_current_per_patient(db_session: Session) -> None:
    org = Organization(name="Zoning Assignment Org")
    db_session.add(org)
    db_session.flush()
    _set_org(db_session, org.id)

    patient = Patient(organization_id=org.id, external_ref="ZN-PAC-1", display_ref="Paciente ZN 1")
    zone_a = Zone(organization_id=org.id, name="Zona A", kind="urban")
    zone_b = Zone(organization_id=org.id, name="Zona B", kind="rural")
    db_session.add_all([patient, zone_a, zone_b])
    db_session.flush()

    now = datetime.now(UTC)
    db_session.add(
        ZoneAssignment(
            organization_id=org.id,
            zone_id=zone_a.id,
            patient_id=patient.id,
            source="cluster",
            valid_from=now - timedelta(days=30),
            valid_to=now - timedelta(days=1),
        )
    )
    db_session.add(
        ZoneAssignment(
            organization_id=org.id,
            zone_id=zone_b.id,
            patient_id=patient.id,
            source="manual",
            valid_from=now,
            valid_to=None,
        )
    )
    db_session.commit()

    db_session.add(
        ZoneAssignment(
            organization_id=org.id,
            zone_id=zone_a.id,
            patient_id=patient.id,
            source="postal",
            valid_from=now,
            valid_to=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_zone_assignment_source_check_rejects_invalid(db_session: Session) -> None:
    org = Organization(name="Zoning Source Org")
    db_session.add(org)
    db_session.flush()
    _set_org(db_session, org.id)

    patient = Patient(organization_id=org.id, external_ref="ZN-PAC-SRC", display_ref="Paciente SRC")
    zone = Zone(organization_id=org.id, name="Fuente", kind="mixed")
    db_session.add_all([patient, zone])
    db_session.flush()

    db_session.add(
        ZoneAssignment(
            organization_id=org.id,
            zone_id=zone.id,
            patient_id=patient.id,
            source="imported",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_zone_assignment_rejects_cross_org_patient(db_session: Session) -> None:
    org_a = Organization(name="Zoning FK Org A")
    org_b = Organization(name="Zoning FK Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    _set_org(db_session, org_a.id)
    zone_a = Zone(organization_id=org_a.id, name="Zona A", kind="urban")
    db_session.add(zone_a)
    db_session.flush()
    zone_a_id = zone_a.id
    db_session.commit()

    _set_org(db_session, org_b.id)
    patient_b = Patient(organization_id=org_b.id, external_ref="ZN-PAC-B", display_ref="Paciente B")
    db_session.add(patient_b)
    db_session.flush()
    patient_b_id = patient_b.id
    db_session.commit()

    _set_org(db_session, org_a.id)
    db_session.add(
        ZoneAssignment(
            organization_id=org_a.id,
            zone_id=zone_a_id,
            patient_id=patient_b_id,
            source="manual",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_zones_gist_indexes_exist(db_session: Session) -> None:
    rows = db_session.execute(
        text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'zones'
              AND indexdef ILIKE '%USING gist%'
            """
        )
    ).fetchall()
    names = {row[0] for row in rows}
    assert "idx_zones_boundary" in names
    assert "idx_zones_centroid" in names


def test_zones_geometry_columns_accept_postgis_values(db_session: Session) -> None:
    org = Organization(name="Zoning Geometry Org")
    db_session.add(org)
    db_session.flush()
    _set_org(db_session, org.id)

    zone = Zone(organization_id=org.id, name="Bilbao", kind="urban")
    db_session.add(zone)
    db_session.flush()

    db_session.execute(
        text(
            """
            UPDATE zones
            SET boundary = ST_Multi(
                    ST_GeomFromText(
                        'POLYGON((-3.0 43.2, -2.9 43.2, -2.9 43.3, -3.0 43.3, -3.0 43.2))',
                        4326
                    )
                ),
                centroid = ST_GeogFromText('SRID=4326;POINT(-2.95 43.25)')
            WHERE id = :id
            """
        ),
        {"id": zone.id},
    )
    db_session.commit()

    geom_type, geog_type = db_session.execute(
        text(
            """
            SELECT ST_GeometryType(boundary), GeometryType(centroid::geometry)
            FROM zones
            WHERE id = :id
            """
        ),
        {"id": zone.id},
    ).one()
    assert geom_type == "ST_MultiPolygon"
    assert geog_type == "POINT"


def test_zone_proposal_status_check_rejects_invalid(db_session: Session) -> None:
    org = Organization(name="Zoning Proposal Status Org")
    db_session.add(org)
    db_session.flush()
    _set_org(db_session, org.id)

    db_session.add(
        ZoneProposal(
            organization_id=org.id,
            status="published",
            params_json={"max_visits": 8},
            result_json={},
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
