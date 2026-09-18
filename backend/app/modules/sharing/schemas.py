"""Esquemas de compartición interna y externa. Ref: 4.BE.6, 4.BE.7, diseño 8.6."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class CreateShareRequest(BaseModel):
    """Interno si hay `subject_user_id`; externo si no (expires_at obligatorio)."""

    subject_user_id: uuid.UUID | None = None
    permission: Literal["view", "edit"] = "view"
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _internal_or_external(self) -> Self:
        if self.subject_user_id is None:
            if self.expires_at is None:
                raise ValueError("expires_at es obligatorio en compartición externa")
            if self.permission != "view":
                raise ValueError("el enlace externo solo admite permission=view")
        return self


class ShareGrantOut(BaseModel):
    id: uuid.UUID
    route_id: uuid.UUID
    subject_user_id: uuid.UUID | None = None
    permission: str
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_by: uuid.UUID
    last_accessed_at: datetime | None = None
    kind: Literal["internal", "external"]
    token: str | None = None


class ShareGrantListOut(BaseModel):
    grants: list[ShareGrantOut] = Field(default_factory=list)


class PublicShareExchangeRequest(BaseModel):
    token: str = Field(min_length=32)


class PublicShareStopOut(BaseModel):
    sequence: int


class PublicShareViewOut(BaseModel):
    route_id: uuid.UUID
    service_date: date
    stop_count: int
    stops: list[PublicShareStopOut] = Field(default_factory=list)
    permission: str
    expires_at: datetime | None = None
