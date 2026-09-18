"""Esquemas del histórico de rutas. Ref: 4.BE.1, RF-23, RF-24, diseño 8.5."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class HistoryStopOut(BaseModel):
    sequence: int
    patient_id: uuid.UUID
    external_ref: str | None = None
    lat: float | None = None
    lon: float | None = None


class HistoryRouteOut(BaseModel):
    route_id: uuid.UUID
    revision_id: uuid.UUID
    revision: int
    published_at: datetime
    service_date: date
    zone_id: uuid.UUID
    assignee_id: uuid.UUID
    objective: str | None = None
    stops: list[HistoryStopOut] = Field(default_factory=list)


class HistoryRoutesPage(BaseModel):
    items: list[HistoryRouteOut]
    next_cursor: str | None = None
