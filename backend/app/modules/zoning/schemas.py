"""Esquemas Pydantic de zonas y propuestas. Ref: diseño sección 8.4, RF-10."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ZoneProposalCreateRequest(BaseModel):
    organization_id: uuid.UUID
    max_visits: int = Field(ge=1)
    target_zones: int | None = Field(default=None, ge=1)
    strategy: str | None = Field(default=None, max_length=50)
    depot_lon: float | None = Field(default=None, ge=-180, le=180)
    depot_lat: float | None = Field(default=None, ge=-90, le=90)


class ZoneProposalCreateResponse(BaseModel):
    id: uuid.UUID
    job_id: str
    status: str


class LonLatOut(BaseModel):
    lon: float
    lat: float


class ZoneProposalClusterOut(BaseModel):
    cluster_id: str
    kind: str
    member_ids: list[uuid.UUID]
    centroid: LonLatOut | None = None


class ZoneProposalAssignmentOut(BaseModel):
    patient_id: uuid.UUID
    cluster_id: str


class ZoneProposalMetricsOut(BaseModel):
    n_points: int
    n_clusters: int
    n_outliers: int
    max_cluster_size: int
    max_visits: int
    fallback: str | None = None


class ZoneProposalOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    status: str
    job_id: str | None
    params: dict
    clusters: list[ZoneProposalClusterOut]
    assignments: list[ZoneProposalAssignmentOut]
    outliers: list[uuid.UUID]
    metrics: ZoneProposalMetricsOut | None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


class ZoneGeometryIn(BaseModel):
    type: Literal["Polygon", "MultiPolygon"]
    coordinates: list[Any]


class ZoneCreateRequest(BaseModel):
    organization_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["urban", "rural", "mixed"]
    max_visits: int | None = Field(default=None, ge=1)
    centroid: LonLatOut | None = None
    geometry: ZoneGeometryIn | None = None


class ZonePatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: Literal["urban", "rural", "mixed"] | None = None
    max_visits: int | None = Field(default=None, ge=1)
    centroid: LonLatOut | None = None
    geometry: ZoneGeometryIn | None = None


class ZoneOverrideRequest(BaseModel):
    reason: str = Field(min_length=1)


class ZoneAssignmentCurrentOut(BaseModel):
    patient_id: uuid.UUID
    source: str
    override_reason: str | None = None


class ZoneOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    kind: str
    max_visits: int | None
    version: int
    centroid: LonLatOut | None = None
    assignments: list[ZoneAssignmentCurrentOut]


class ZoneListItemOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    kind: str
    max_visits: int | None
    version: int
    patient_count: int
    centroid: LonLatOut | None = None


class ZonesPage(BaseModel):
    zones: list[ZoneListItemOut]


class ZoneAcceptResponse(BaseModel):
    zones: list[ZoneOut]
    preserved_override_count: int
