"""E2E de POST /routes/{id}/publish: snapshot inmutable, If-Match e idempotencia.

Ref: 3.BE.11, RF-21, ADR-08, diseño 7.6 / 8.5.
Publicar responde 200 (transacción única, sin worker). FakeRouter (sin OSRM real).
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.router.fake import FakeRouter
from app.adapters.router.interface import Coordinate
from app.core.config import get_settings
from app.core.crypto import FieldCipher, KeyProvider
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.main import app
from app.modules.identity import service as identity_service
from app.modules.imports.deps import get_field_cipher
from app.modules.imports.models import Address
from app.modules.planning.models import DailyRoute
from app.modules.routing.models import RouteRevision, RouteStop
from app.modules.zoning.deps import get_router
from tests.test_routing_optimize_e2e import (
    _body,
    _get_route,
    _post_optimize,
    _run_job,
    _seed_published_route,
)
from tests.test_routing_order_e2e import _auth_headers, _planner_headers_for_assignee, _reorder


class _StaticKeyProvider(KeyProvider):
    def __init__(self, active: str, keys: dict[str, bytes]) -> None:
        self._active = active
        self._keys = keys

    def active_key_id(self) -> str:
        return self._active

    def get_key(self, key_id: str) -> bytes:
        return self._keys[key_id]


class _FailingRouter(FakeRouter):
    async def route(self, coordinates: list[Coordinate]) -> dict:
        raise RuntimeError("osrm down")


class _EmptyGeometryRouter(FakeRouter):
    async def route(self, coordinates: list[Coordinate]) -> dict:
        return {"geometry": None, "coordinates": []}


@pytest.fixture()
def queue() -> JobQueue:
    return JobQueue(fakeredis.FakeStrictRedis())


@pytest.fixture()
def cipher() -> FieldCipher:
    return FieldCipher(_StaticKeyProvider("k1", {"k1": os.urandom(32)}))


@pytest.fixture()
def client(db_session: Session, queue: JobQueue, cipher: FieldCipher) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    app.dependency_overrides[get_router] = lambda: FakeRouter()
    app.dependency_overrides[get_field_cipher] = lambda: cipher
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _encrypt_seed_addresses(db: Session, cipher: FieldCipher, org_id: uuid.UUID) -> None:
    identity_service.set_current_organization_context(db, organization_id=org_id)
    addresses = db.query(Address).filter(Address.organization_id == org_id).all()
    for index, address in enumerate(addresses, start=1):
        address.address_ciphertext = cipher.encrypt(f"Calle Mayor {index}, Bilbao")
    db.commit()


def _prepare_optimized_route(
    client: TestClient,
    db: Session,
    cipher: FieldCipher,
    *,
    org_name: str,
    n_stops: int = 3,
    body: dict | None = None,
):
    route, planner, patients = _seed_published_route(db, org_name=org_name, n_stops=n_stops)
    _encrypt_seed_addresses(db, cipher, route.organization_id)
    headers = _planner_headers_for_assignee(client, db, route)
    payload = body if body is not None else _body()
    posted = _post_optimize(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        body=payload,
        idempotency_key=f"opt-{org_name}",
    )
    assert posted.status_code == 202
    revision = _run_job(db, route, planner, payload)
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    db.expire_all()
    persisted = db.get(DailyRoute, route.id)
    assert persisted is not None
    assert revision is not None
    return persisted, planner, patients, revision, headers


def _publish(
    client: TestClient,
    *,
    route_id: uuid.UUID,
    org_id: uuid.UUID,
    headers: dict[str, str],
    version: int,
    body: dict | None = None,
    idempotency_key: str | None = "pub-key-1",
    if_match: str | None = None,
) -> object:
    request_headers = dict(headers)
    request_headers["If-Match"] = if_match if if_match is not None else f'"{version}"'
    if idempotency_key is not None:
        request_headers["Idempotency-Key"] = idempotency_key
    return client.post(
        f"/api/v1/routes/{route_id}/publish",
        params={"organization_id": str(org_id)},
        json=body if body is not None else {},
        headers=request_headers,
    )


def test_publish_freezes_snapshot_and_blocks_direct_edit(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, _planner, patients, revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="pub-ok"
    )
    org_id = route.organization_id
    version_before = route.version

    response = _publish(
        client, route_id=route.id, org_id=org_id, headers=headers, version=version_before
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route_id"] == str(route.id)
    assert body["revision_id"] == str(revision.id)
    assert body["revision"] == 1
    assert body["status"] == "published"
    assert body["revision_status"] == "published"
    assert body["version"] == version_before + 1
    assert body["published_at"]
    assert body["osrm_dataset_version"] == get_settings().osrm_dataset_version
    assert response.headers["etag"] == f'"{version_before + 1}"'

    identity_service.set_current_organization_context(db_session, organization_id=org_id)
    db_session.expire_all()
    persisted_route = db_session.get(DailyRoute, route.id)
    persisted_revision = db_session.get(RouteRevision, revision.id)
    assert persisted_route is not None
    assert persisted_revision is not None
    assert persisted_route.status == "published"
    assert persisted_route.current_revision == revision.id
    assert persisted_revision.status == "published"
    assert persisted_revision.published_at is not None
    snapshot = persisted_revision.constraints_json["snapshot"]
    assert snapshot["geometry"]["type"] == "LineString"
    assert len(snapshot["geometry"]["coordinates"]) >= 3
    assert snapshot["osrm_dataset_version"] == get_settings().osrm_dataset_version
    assert snapshot["osm_dataset_version"] == get_settings().osrm_dataset_version
    assert {item["patient_id"] for item in snapshot["order"]} == {str(p.id) for p in patients}
    assert [item["sequence"] for item in snapshot["order"]] == [1, 2, 3]
    assert set(snapshot["metrics"]) == {"original", "optimized"}

    stops = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == revision.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert len(stops) == 3
    for stop in stops:
        assert stop.address_snapshot_ciphertext
        assert "Calle Mayor" not in stop.address_snapshot_ciphertext
        decoded = json.loads(cipher.decrypt(stop.address_snapshot_ciphertext))
        assert "Calle Mayor" in decoded["address"]
        assert decoded["municipality"] == "Bilbao"
        assert decoded["postal_code"] == "48001"
        assert decoded["sequence"] == stop.sequence

    blocked = _reorder(
        client,
        route_id=route.id,
        org_id=org_id,
        revision_id=revision.id,
        ordered_stop_ids=list(reversed([stop.id for stop in stops])),
        headers=headers,
        version=persisted_route.version,
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "REVISION_PUBLISHED"


def test_publish_then_optimize_creates_new_draft_without_mutating_published(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, planner, _patients, revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="pub-rev"
    )
    published = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=route.version,
    )
    assert published.status_code == 200

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    frozen = db_session.get(RouteRevision, revision.id)
    assert frozen is not None
    frozen_snapshot = frozen.constraints_json["snapshot"]
    frozen_published_at = frozen.published_at
    frozen_ciphertexts = [
        stop.address_snapshot_ciphertext
        for stop in db_session.query(RouteStop)
        .filter(RouteStop.revision_id == revision.id)
        .order_by(RouteStop.sequence)
    ]

    new_revision = _run_job(db_session, route, planner, _body())
    assert new_revision is not None
    assert new_revision.id != revision.id
    assert new_revision.status == "draft"
    assert new_revision.published_at is None
    assert new_revision.revision == 2

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    still_published = db_session.get(RouteRevision, revision.id)
    assert still_published is not None
    assert still_published.status == "published"
    assert still_published.published_at == frozen_published_at
    assert still_published.constraints_json["snapshot"] == frozen_snapshot
    still_stops = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == revision.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    assert [stop.address_snapshot_ciphertext for stop in still_stops] == frozen_ciphertexts

    refreshed = db_session.get(DailyRoute, route.id)
    assert refreshed is not None
    assert refreshed.current_revision == new_revision.id
    assert refreshed.status == "ready"


def test_publish_idempotency_replays_same_key_and_rejects_payload_reuse(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, _planner, _patients, revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="pub-idem"
    )
    version = route.version
    first = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=version,
        idempotency_key="same-pub",
    )
    assert first.status_code == 200
    first_body = first.json()

    replay = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=version,
        idempotency_key="same-pub",
    )
    assert replay.status_code == 200
    assert replay.json() == first_body

    conflict = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=version,
        body={"revision_id": str(revision.id)},
        idempotency_key="same-pub",
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSE"


def test_publish_requires_headers_and_planner_role(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, _planner, _patients, _revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="pub-auth"
    )

    missing_key = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=route.version,
        idempotency_key=None,
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    missing_match = client.post(
        f"/api/v1/routes/{route.id}/publish",
        params={"organization_id": str(route.organization_id)},
        json={},
        headers={**headers, "Idempotency-Key": "pub-no-match"},
    )
    assert missing_match.status_code == 422
    assert missing_match.json()["code"] == "IF_MATCH_REQUIRED"

    stale = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=route.version,
        if_match='"0"',
        idempotency_key="pub-stale",
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "ROUTE_VERSION_CONFLICT"

    field_headers = _auth_headers(client, db_session, org_id=route.organization_id, role="field")
    forbidden = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=field_headers,
        version=route.version,
        idempotency_key="pub-field",
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ROLE"


def test_publish_rejects_infeasible_stale_metrics_and_router_failure(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    infeasible_route, _planner, _patients, infeasible_rev, inf_headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="pub-inf", n_stops=2
    )
    identity_service.set_current_organization_context(
        db_session, organization_id=infeasible_route.organization_id
    )
    db_session.expire_all()
    infeasible = db_session.get(RouteRevision, infeasible_rev.id)
    assert infeasible is not None
    infeasible.solver_status = "infeasible"
    db_session.commit()

    blocked_infeasible = _publish(
        client,
        route_id=infeasible_route.id,
        org_id=infeasible_route.organization_id,
        headers=inf_headers,
        version=infeasible_route.version,
        idempotency_key="pub-inf",
    )
    assert blocked_infeasible.status_code == 409
    assert blocked_infeasible.json()["code"] == "ROUTE_NOT_FEASIBLE"

    route, _planner, _patients, revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="pub-stale-m"
    )
    stops = (
        db_session.query(RouteStop)
        .filter(RouteStop.revision_id == revision.id)
        .order_by(RouteStop.sequence)
        .all()
    )
    reordered = _reorder(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        revision_id=revision.id,
        ordered_stop_ids=list(reversed([stop.id for stop in stops])),
        headers=headers,
        version=route.version,
    )
    assert reordered.status_code == 200
    stale = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=reordered.json()["version"],
        idempotency_key="pub-stale-m",
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "METRICS_STALE"

    ok_route, _planner, _patients, _revision, ok_headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="pub-osrm"
    )
    app.dependency_overrides[get_router] = lambda: _FailingRouter()
    down = _publish(
        client,
        route_id=ok_route.id,
        org_id=ok_route.organization_id,
        headers=ok_headers,
        version=ok_route.version,
        idempotency_key="pub-osrm",
    )
    assert down.status_code == 503
    assert down.json()["code"] == "ROUTER_UNAVAILABLE"

    app.dependency_overrides[get_router] = lambda: _EmptyGeometryRouter()
    empty = _publish(
        client,
        route_id=ok_route.id,
        org_id=ok_route.organization_id,
        headers=ok_headers,
        version=ok_route.version,
        idempotency_key="pub-empty-geom",
    )
    assert empty.status_code == 409
    assert empty.json()["code"] == "ROUTE_GEOMETRY_UNAVAILABLE"
    app.dependency_overrides[get_router] = lambda: FakeRouter()


def test_second_publish_returns_409_without_mutating_snapshot(
    client: TestClient, db_session: Session, cipher: FieldCipher
) -> None:
    route, _planner, _patients, revision, headers = _prepare_optimized_route(
        client, db_session, cipher, org_name="pub-twice"
    )
    first = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=route.version,
        idempotency_key="pub-first",
    )
    assert first.status_code == 200

    second = _publish(
        client,
        route_id=route.id,
        org_id=route.organization_id,
        headers=headers,
        version=first.json()["version"],
        idempotency_key="pub-second",
    )
    assert second.status_code == 409
    assert second.json()["code"] == "ROUTE_PUBLISHED"

    identity_service.set_current_organization_context(
        db_session, organization_id=route.organization_id
    )
    db_session.expire_all()
    persisted = db_session.get(RouteRevision, revision.id)
    assert persisted is not None
    assert persisted.status == "published"
    assert db_session.query(RouteRevision).filter(RouteRevision.route_id == route.id).count() == 1

    detail = _get_route(client, route_id=route.id, org_id=route.organization_id, headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "published"
