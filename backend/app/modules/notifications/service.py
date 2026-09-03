"""Escritura del outbox. No entrega notificaciones (4.BE.9). El caller hace commit."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.modules.notifications.models import OutboxEvent


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
