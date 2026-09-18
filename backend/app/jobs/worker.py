"""Runner de colas: `python -m app.jobs.worker <cola>`. Ref: 0.BE.6, 1.BE.2.

Sondeo simple; en producción se despliega como réplicas de este mismo proceso
(un contenedor por cola o varios) bajo un supervisor, no como hilo del API.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from collections.abc import Callable

from app.db.session import SessionLocal
from app.jobs.queue import get_job_queue
from app.modules.geocoding import service as geocoding_service
from app.modules.geocoding.deps import get_geocode_cache, get_geocoder
from app.modules.imports import service as imports_service
from app.modules.imports.deps import get_field_cipher, get_object_store
from app.modules.notifications import service as notifications_service
from app.modules.planning import service as planning_service
from app.modules.routing import export as routing_export
from app.modules.routing import service as routing_service
from app.modules.routing.deps import get_optimizer
from app.modules.routing.matrix import get_osrm_table_cache
from app.modules.zoning import service as zoning_service
from app.modules.zoning.deps import get_router

POLL_INTERVAL_SECONDS = 1.0


def _handle_validate_import(payload: dict) -> None:
    db = SessionLocal()
    try:
        imports_service.validate_import(
            db,
            get_object_store(),
            get_field_cipher(),
            batch_id=uuid.UUID(payload["batch_id"]),
            organization_id=uuid.UUID(payload["organization_id"]),
        )
    finally:
        db.close()


def _handle_geocode_batch(payload: dict) -> None:
    db = SessionLocal()
    try:
        asyncio.run(
            geocoding_service.geocode_eligible_addresses_for_batch(
                db,
                get_geocoder(),
                get_geocode_cache(),
                get_field_cipher(),
                batch_id=uuid.UUID(payload["batch_id"]),
            )
        )
    finally:
        db.close()


def _handle_zone_proposal(payload: dict) -> None:
    db = SessionLocal()
    try:
        zoning_service.run_zone_proposal(
            db,
            proposal_id=uuid.UUID(payload["proposal_id"]),
            organization_id=uuid.UUID(payload["organization_id"]),
            router=get_router(),
        )
    finally:
        db.close()


def _handle_generate_plan(payload: dict) -> None:
    db = SessionLocal()
    try:
        planning_service.generate_plan(
            db,
            plan_id=uuid.UUID(payload["plan_id"]),
            organization_id=uuid.UUID(payload["organization_id"]),
        )
    finally:
        db.close()


def _handle_optimize_route(payload: dict) -> None:
    db = SessionLocal()
    try:
        routing_service.optimize_route_job(
            db,
            route_id=uuid.UUID(payload["route_id"]),
            organization_id=uuid.UUID(payload["organization_id"]),
            created_by=uuid.UUID(payload["created_by"]),
            request=payload["request"],
            job_id=uuid.UUID(payload["job_id"]),
            router=get_router(),
            cache=get_osrm_table_cache(),
            optimizer=get_optimizer(),
            cipher=get_field_cipher(),
        )
    finally:
        db.close()


def _handle_export_route(payload: dict) -> None:
    db = SessionLocal()
    try:
        routing_export.export_route_job(
            db,
            get_object_store(),
            route_id=uuid.UUID(payload["route_id"]),
            organization_id=uuid.UUID(payload["organization_id"]),
            revision_id=uuid.UUID(payload["revision_id"]),
            format=payload["format"],
            job_id=uuid.UUID(payload["job_id"]),
        )
    finally:
        db.close()


def _handle_notifications(payload: dict) -> None:
    db = SessionLocal()
    try:
        notifications_service.consume_outbox_event(
            db,
            event_id=uuid.UUID(payload["event_id"]),
            organization_id=uuid.UUID(payload["organization_id"]),
        )
    finally:
        db.close()


HANDLERS: dict[str, Callable[[dict], None]] = {
    "imports": _handle_validate_import,
    "geocoding": _handle_geocode_batch,
    "zoning": _handle_zone_proposal,
    "planning": _handle_generate_plan,
    "optimization": _handle_optimize_route,
    "exports": _handle_export_route,
    "notifications": _handle_notifications,
}


def run_forever(queue_name: str) -> None:
    handler = HANDLERS.get(queue_name)
    if handler is None:
        raise SystemExit(f"Sin handler registrado para la cola '{queue_name}'")
    queue = get_job_queue()
    while True:
        job = queue.run_once(queue=queue_name, handler=handler)
        if job is None:
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python -m app.jobs.worker <cola>")
    run_forever(sys.argv[1])
