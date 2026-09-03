"""Verifica que RLS impide leer import_batches/patients/addresses de otra organización.

Ref: 0.DATA.3 (patrón), 1.DATA.1, RNF-06.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.identity.models import Organization, User
from app.modules.imports.models import Address, ImportBatch, Patient


def _set_org(db: Session, organization_id: uuid.UUID) -> None:
    db.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
        {"org_id": str(organization_id)},
    )


def test_organization_a_cannot_read_import_batches_of_organization_b(db_session: Session) -> None:
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()
    creator = User(email_normalized="creator@example.com", display_name="Creador")
    db_session.add(creator)
    db_session.flush()
    user_id = creator.id

    _set_org(db_session, org_a.id)
    db_session.add(
        ImportBatch(
            organization_id=org_a.id,
            period="2026-08",
            filename="a.csv",
            file_sha256="a" * 64,
            created_by=user_id,
        )
    )
    db_session.commit()

    _set_org(db_session, org_b.id)
    db_session.add(
        ImportBatch(
            organization_id=org_b.id,
            period="2026-08",
            filename="b.csv",
            file_sha256="b" * 64,
            created_by=user_id,
        )
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible_filenames = {b.filename for b in db_session.query(ImportBatch).all()}

    assert visible_filenames == {"a.csv"}


def test_organization_a_cannot_read_patients_or_addresses_of_organization_b(db_session: Session) -> None:
    org_a = Organization(name="Org A")
    org_b = Organization(name="Org B")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    _set_org(db_session, org_a.id)
    patient_a = Patient(organization_id=org_a.id, external_ref="PAC-A", display_ref="Paciente A")
    db_session.add(patient_a)
    db_session.flush()
    db_session.add(
        Address(
            organization_id=org_a.id,
            patient_id=patient_a.id,
            address_ciphertext="cif-a",
            postal_code="48001",
            municipality="Bilbao",
            province="Bizkaia",
        )
    )
    db_session.commit()

    _set_org(db_session, org_b.id)
    patient_b = Patient(organization_id=org_b.id, external_ref="PAC-B", display_ref="Paciente B")
    db_session.add(patient_b)
    db_session.flush()
    db_session.add(
        Address(
            organization_id=org_b.id,
            patient_id=patient_b.id,
            address_ciphertext="cif-b",
            postal_code="48002",
            municipality="Barakaldo",
            province="Bizkaia",
        )
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    assert {p.external_ref for p in db_session.query(Patient).all()} == {"PAC-A"}
    assert {a.municipality for a in db_session.query(Address).all()} == {"Bilbao"}
