"""E2E de recálculo al añadir/quitar/modificar paradas (3.BE.9, RF-20, diseño 11.1).

PUT /routes/{id}/stops sustituye el conjunto. El ledger de optimize incluye
fingerprint de paradas: la clave anterior no se reutiliza; una clave nueva relanza.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.imports.models import Address, Patient
from app.modules.planning.models import DailyRoute
from app.modules.routing.models import RouteRevision, RouteStop
from tests.test_plans_e2e import _point
from tests.test_routing_optimize_e2e import (
    _body,
    _get_route,
    _post_optimize,
    _run_job,
    _seed_published_route,
)
from tests.test_routing_order_e2e import _auth_headers, _planner_headers_for_assignee


@pytest.fixture()
def queue() -> JobQueue:
    return JobQueue(fakeredis.FakeStrictRedis())


@pytest.fixture()
def client(db_session: Session, queue: JobQueue) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _put_stops(
    client: TestClient,
    *,
    route_id: uuid.UUID,
    org_id: uuid.UUID,
    headers: dict[str, str],
    patient_ids: list[uuid.UUID],
    version: int,
    if_match: str | None = None,
) -> object:
    request_headers = dict(headers)
    request_headers["If-Match"] = if_match if if_match is not None else f'"{version}"'
    return client.put(
        f"/api/v1/routes/{route_id}/stops",
        params={"organization_id": str(org_id)},
        json={"patient_ids": [str(item) for item in patient_ids]},
        headers=request_headers,
    )


def _add_geocoded_patient(
    db: Session, *, org_id: uuid.UUID, suffix: str, lon: float, lat: float
) -> Patient:
    identity_service.set_current_organization_context(db, organization_id=org_id)
    patient = Patient(
        organization_id=org_id,
        external_ref=f"RECALC-{suffix}",
        display_ref=f"Extra {suffix}",
    )
    db.add(patient)
    db.flush()
    db.add(
        Address(
            organization_id=org_id,
            patient_id=patient.id,
            address_ciphertext="enc",
            postal_code="48001",
            municipality="Bilbao",
            province="Bizkaia",
            location=_point(lon, lat),
            geocode_status="matched",
            is_active=True,
        )
    )
    db.commit()
    db.refresh(patient)
    return patient


def _prepare_optimized(
    client: TestClient, db: Session, *, org_name: str, n_stops: int = 3
):
    route, planner, patients = _seed_published_route(db, org_name=org_name, n_stops=n_stops)
    headers = _planner_headers_for_assignee(client, db, route)
    body = _body()
    posted = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        body=body,
        idempotency_key=f"opt-{org_name}",
    )
    assert posted.status_code == 202
    revision = _run_job(db, route, planner, body)
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    db.expire_all()
    persisted = db.get(DailyRoute, route.id)
    assert persisted is not None
    assert revision is not None
    return persisted, planner, patients, revision, headers, body


def test_replace_stops_invalidates_optimize_key_and_new_key_recalculates(
    client: TestClient, db_session: Session
) -> None:
    route, planner, patients, revision, headers, body = _prepare_optimized(
        client, db_session, org_name="recalc-key"
    )
    kept = [patients[0].id, patients[1].id]
    version_before = route.version

    replaced = _put_stops(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        patient_ids=kept,
        version=version_before,
    )
    assert replaced.status_code == 200
    payload = replaced.json()
    assert payload["revision_id"] == str(revision.id)
    assert [item["patient_id"] for item in payload["stops"]] == [str(pid) for pid in kept]
    assert payload["metrics_pending"] is True
    assert payload["version"] == version_before + 1
    assert replaced.headers["etag"] == f'"{payload["version"]}"'

    replay_old_key = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        body=body,
        idempotency_key="opt-recalc-key",
    )
    assert replay_old_key.status_code == 409
    assert replay_old_key.json()["code"] == "IDEMPOTENCY_KEY_REUSE"

    new_job = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        body=body,
        idempotency_key="opt-recalc-key-v2",
    )
    assert new_job.status_code == 202
    new_revision = _run_job(db_session, route, planner, body)
    assert new_revision is not None
    assert new_revision.id != revision.id
    assert new_revision.status == "draft"

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    stops = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == new_revision.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert {stop.patient_id for stop in stops} == set(kept)
    assert len(stops) == 2


def test_add_and_modify_stop_location_changes_fingerprint(
    client: TestClient, db_session: Session
) -> None:
    route, planner, patients, _revision, headers, body = _prepare_optimized(
        client, db_session, org_name="recalc-add"
    )
    extra = _add_geocoded_patient(
        db_session,
        org_id=route.organization_id,
        suffix="add",
        lon=-2.9300,
        lat=43.2700,
    )
    added_ids = [patient.id for patient in patients] + [extra.id]

    added = _put_stops(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        patient_ids=added_ids,
        version=route.version,
    )
    assert added.status_code == 200
    assert len(added.json()["stops"]) == 4

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    address = (
        db_session.query(Address)
        .filter(Address.patient_id == patients[0].id, Address.is_active.is_(True))
        .one()
    )
    address.location = _point(-2.9100, 43.2800)
    db_session.commit()

    refreshed = db_session.get(DailyRoute, route.id)
    assert refreshed is not None
    modified = _put_stops(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        patient_ids=added_ids,
        version=refreshed.version,
    )
    assert modified.status_code == 200

    old_key = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        body=body,
        idempotency_key="opt-recalc-add",
    )
    assert old_key.status_code == 409
    assert old_key.json()["code"] == "IDEMPOTENCY_KEY_REUSE"

    new_job = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        body=body,
        idempotency_key="opt-recalc-add-v2",
    )
    assert new_job.status_code == 202
    new_revision = _run_job(db_session, route, planner, body)
    assert new_revision is not None
    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    stops = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == new_revision.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert len(stops) == 4
    assert {stop.patient_id for stop in stops} == set(added_ids)


def test_replace_stops_on_published_creates_new_draft(
    client: TestClient, db_session: Session
) -> None:
    route, _planner, patients, revision, headers, _body = _prepare_optimized(
        client, db_session, org_name="recalc-pub"
    )
    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    frozen = db_session.get(RouteRevision, revision.id)
    assert frozen is not None
    frozen.status = "published"
    frozen.published_at = datetime.now(UTC)
    locked = db_session.get(DailyRoute, route.id)
    assert locked is not None
    locked.status = "published"
    db_session.commit()

    replaced = _put_stops(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        patient_ids=[patients[0].id, patients[1].id],
        version=locked.version,
    )
    assert replaced.status_code == 200
    assert replaced.json()["revision_id"] != str(revision.id)

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    still = db_session.get(RouteRevision, revision.id)
    assert still is not None
    assert still.status == "published"
    published_stops = (
        db_session.query(RouteStop).filter(RouteStop.revision_id == revision.id).count()
    )
    assert published_stops == 3
    draft = db_session.get(RouteRevision, uuid.UUID(replaced.json()["revision_id"]))
    assert draft is not None
    assert draft.status == "draft"
    draft_stops = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == draft.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert [stop.patient_id for stop in draft_stops] == [patients[0].id, patients[1].id]
    refreshed = db_session.get(DailyRoute, route.id)
    assert refreshed is not None
    assert refreshed.status == "draft"
    assert refreshed.current_revision == draft.id


def test_replace_stops_requires_if_match_and_planner_role(
    client: TestClient, db_session: Session
) -> None:
    route, _planner, patients, _revision, headers, _body = _prepare_optimized(
        client, db_session, org_name="recalc-auth"
    )
    kept = [patients[0].id]

    missing = client.put(
        f"/api/v1/routes/{route.id}/stops",
        params={"organization_id": str(route.organization_id)},
        json={"patient_ids": [str(patients[0].id)]},
        headers=headers,
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "IF_MATCH_REQUIRED"

    stale = _put_stops(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        patient_ids=kept,
        version=route.version,
        if_match='"0"',
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "ROUTE_VERSION_CONFLICT"

    field_headers = _auth_headers(client, db_session, org_id=route.organization_id, role="field")
    forbidden = _put_stops(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=field_headers,
        patient_ids=kept,
        version=route.version,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ROLE"

    unknown = _put_stops(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        patient_ids=[uuid.uuid4()],
        version=route.version,
    )
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "PATIENT_NOT_FOUND"


def test_same_optimize_key_replays_when_stops_unchanged(
    client: TestClient, db_session: Session
) -> None:
    route, _planner, _patients, _revision, headers, body = _prepare_optimized(
        client, db_session, org_name="recalc-replay"
    )
    replay = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        body=body,
        idempotency_key="opt-recalc-replay",
    )
    assert replay.status_code == 202
    assert replay.json()["status"] == "queued"

    detail = _get_route(client, route_id=route.id, org_id=route.organization_id, headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["stops"]) == 3
