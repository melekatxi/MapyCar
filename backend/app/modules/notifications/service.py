"""Escritura del outbox y consumo idempotente. GET/PATCH HTTP = 4.BE.10.

El caller de `record_event` hace commit. Tras el commit, `schedule_outbox`
encola el event_id (best-effort). El consumidor registra `event_id` y no
duplica filas si se reejecuta.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import redis
from sqlalchemy.orm import Session

from app.jobs.queue import get_job_queue
from app.modules.identity import service as identity_service
from app.modules.notifications.models import (
    EVENT_PLAN_PUBLISHED,
    EVENT_ROUTE_REASSIGNED,
    EVENT_SHARE_CREATED,
    NOTIFICATION_PLAN_PUBLISHED,
    NOTIFICATION_ROUTE_REASSIGNED,
    NOTIFICATION_ROUTE_SHARED,
    NOTIFICATION_STATUS_UNREAD,
    Notification,
    OutboxEvent,
)

NOTIFICATIONS_QUEUE = "notifications"


def record_event(
    db: Session,
    *,
    organization_id: uuid.UUID,
    event_type: str,
    resource_type: str,
    resource_id: uuid.UUID,
    payload: dict[str, Any],
) -> OutboxEvent:
    event = OutboxEvent(
        organization_id=organization_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        payload_json=payload,
    )
    db.add(event)
    db.flush()
    return event


def schedule_outbox(event: OutboxEvent) -> None:
    """Encola el event_id. Si Redis no está, el evento queda unprocessed."""
    try:
        get_job_queue().enqueue(
            queue=NOTIFICATIONS_QUEUE,
            payload={
                "event_id": str(event.id),
                "organization_id": str(event.organization_id),
            },
        )
    except (redis.RedisError, OSError):
        return


def consume_outbox_event(
    db: Session,
    *,
    event_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> list[Notification]:
    """Crea notificaciones in-app y marca processed_at. Reejecutar es no-op."""
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    event = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.id == event_id,
            OutboxEvent.organization_id == organization_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if event is None:
        return []
    if event.processed_at is not None:
        return _notifications_for_event(db, event_id=event.id)

    notif_type = _notification_type(event.event_type)
    resource_id = _resource_id(event)
    now = datetime.now(UTC)
    created: list[Notification] = []
    if notif_type is not None:
        for recipient_id in _recipients_for(event):
            existing = (
                db.query(Notification)
                .filter(
                    Notification.event_id == event.id,
                    Notification.recipient_id == recipient_id,
                    Notification.organization_id == organization_id,
                )
                .one_or_none()
            )
            if existing is not None:
                created.append(existing)
                continue
            row = Notification(
                organization_id=organization_id,
                recipient_id=recipient_id,
                type=notif_type,
                resource_id=resource_id,
                event_id=event.id,
                status=NOTIFICATION_STATUS_UNREAD,
                sent_at=now,
            )
            db.add(row)
            created.append(row)
        db.flush()
    event.processed_at = now
    db.commit()
    for row in created:
        db.refresh(row)
    return created


def consume_unprocessed(
    db: Session,
    *,
    organization_id: uuid.UUID,
    limit: int = 100,
) -> int:
    """Procesa eventos pendientes de la org. Cada uno en su transacción."""
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    pending = (
        db.query(OutboxEvent.id)
        .filter(
            OutboxEvent.organization_id == organization_id,
            OutboxEvent.processed_at.is_(None),
        )
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
        .limit(limit)
        .all()
    )
    count = 0
    for (event_id,) in pending:
        consume_outbox_event(db, event_id=event_id, organization_id=organization_id)
        count += 1
    return count


def _notifications_for_event(db: Session, *, event_id: uuid.UUID) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.event_id == event_id)
        .order_by(Notification.id)
        .all()
    )


def _notification_type(event_type: str) -> str | None:
    mapping = {
        EVENT_SHARE_CREATED: NOTIFICATION_ROUTE_SHARED,
        EVENT_ROUTE_REASSIGNED: NOTIFICATION_ROUTE_REASSIGNED,
        EVENT_PLAN_PUBLISHED: NOTIFICATION_PLAN_PUBLISHED,
    }
    return mapping.get(event_type)


def _recipients_for(event: OutboxEvent) -> list[uuid.UUID]:
    payload = event.payload_json or {}
    if event.event_type == EVENT_SHARE_CREATED:
        raw = payload.get("subject_user_id")
        return [_as_uuid(raw)] if raw else []
    if event.event_type == EVENT_ROUTE_REASSIGNED:
        raw = payload.get("assignee_id")
        return [_as_uuid(raw)] if raw else []
    if event.event_type == EVENT_PLAN_PUBLISHED:
        seen: list[uuid.UUID] = []
        for item in payload.get("assignee_ids") or []:
            value = _as_uuid(item)
            if value not in seen:
                seen.append(value)
        return seen
    return []


def _resource_id(event: OutboxEvent) -> uuid.UUID:
    payload = event.payload_json or {}
    raw = payload.get("route_id") or payload.get("plan_id")
    if raw:
        return _as_uuid(raw)
    return event.resource_id


def _as_uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
