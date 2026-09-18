"""Esquemas de jobs durables. Ref: diseño 8.5 GET /jobs/{id}."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class JobOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    type: str
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    status: str
    progress: int
    attempt: int
    error_code: str | None = None
    result_json: dict = {}
    created_at: datetime
    updated_at: datetime
