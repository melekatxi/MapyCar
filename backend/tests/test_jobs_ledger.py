"""Ledger de jobs / Idempotency-Key: replay vs 409, UNIQUE y RLS.

Ref: 3.BE.14, diseño 6.1, 8.1.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.modules.identity.models import Organization
from app.modules.jobs.ledger import begin_idempotent_job, hash_request_payload
from app.modules.jobs.models import Job


def _set_org(db: Session, organization_id: uuid.UUID) -> None:
    db.execute(
        text("SELECT set_config('app.current_organization_id', :org_id, false)"),
        {"org_id": str(organization_id)},
    )


def _seed_org(db: Session, suffix: str) -> Organization:
    org = Organization(name=f"Jobs Ledger Org {suffix}")
    db.add(org)
    db.flush()
    _set_org(db, org.id)
    return org


def test_begin_idempotent_job_replays_same_payload(db_session: Session) -> None:
    org = _seed_org(db_session, "replay")
    payload = {"period": "2026-09", "filename": "a.xlsx"}
    first = begin_idempotent_job(
        db_session,
        organization_id=org.id,
        job_type="imports.validate",
        idempotency_key="key-1",
        payload=payload,
        resource_type="import_batch",
    )
    db_session.commit()

    _set_org(db_session, org.id)
    second = begin_idempotent_job(
        db_session,
        organization_id=org.id,
        job_type="imports.validate",
        idempotency_key="key-1",
        payload={"filename": "a.xlsx", "period": "2026-09"},
    )
    db_session.commit()

    assert second.id == first.id
    assert second.request_hash == hash_request_payload(payload)
    assert db_session.query(Job).count() == 1


def test_begin_idempotent_job_conflict_on_payload_reuse(db_session: Session) -> None:
    org = _seed_org(db_session, "reuse")
    begin_idempotent_job(
        db_session,
        organization_id=org.id,
        job_type="route.optimize",
        idempotency_key="same-key",
        payload={"objective": "time"},
    )
    db_session.commit()

    _set_org(db_session, org.id)
    with pytest.raises(DomainError) as exc_info:
        begin_idempotent_job(
            db_session,
            organization_id=org.id,
            job_type="route.optimize",
            idempotency_key="same-key",
            payload={"objective": "cost"},
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "IDEMPOTENCY_KEY_REUSE"
    assert db_session.query(Job).count() == 1


def test_jobs_unique_org_type_idempotency_key(db_session: Session) -> None:
    org = _seed_org(db_session, "uniq")
    db_session.add(
        Job(
            organization_id=org.id,
            type="imports.validate",
            idempotency_key="dup",
            request_hash="a" * 64,
        )
    )
    db_session.commit()

    _set_org(db_session, org.id)
    db_session.add(
        Job(
            organization_id=org.id,
            type="imports.validate",
            idempotency_key="dup",
            request_hash="b" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    _set_org(db_session, org.id)
    db_session.add(
        Job(
            organization_id=org.id,
            type="imports.commit",
            idempotency_key="dup",
            request_hash="c" * 64,
        )
    )
    db_session.commit()


def test_organization_a_cannot_read_jobs_of_organization_b(db_session: Session) -> None:
    org_a = _seed_org(db_session, "A")
    job_a = begin_idempotent_job(
        db_session,
        organization_id=org_a.id,
        job_type="imports.validate",
        idempotency_key="org-a",
        payload={"n": 1},
    )
    db_session.commit()

    org_b = _seed_org(db_session, "B")
    begin_idempotent_job(
        db_session,
        organization_id=org_b.id,
        job_type="imports.validate",
        idempotency_key="org-b",
        payload={"n": 2},
    )
    db_session.commit()

    _set_org(db_session, org_a.id)
    visible = {row.id for row in db_session.query(Job).all()}
    assert visible == {job_a.id}


def test_session_without_org_context_sees_no_jobs(db_session: Session) -> None:
    org = _seed_org(db_session, "Empty")
    begin_idempotent_job(
        db_session,
        organization_id=org.id,
        job_type="imports.validate",
        idempotency_key="empty",
        payload={"n": 1},
    )
    db_session.commit()

    db_session.execute(text("RESET app.current_organization_id"))
    assert db_session.query(Job).all() == []


def test_jobs_force_rls_and_status_index(db_session: Session) -> None:
    row = db_session.execute(
        text(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = 'jobs'
            """
        )
    ).one()
    assert row[0] is True
    assert row[1] is True

    indexes = db_session.execute(
        text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'jobs'
            """
        )
    ).fetchall()
    names = {item[0] for item in indexes}
    assert "uq_jobs_org_type_idempotency_key" in names
    assert "ix_jobs_status_created_at" in names
