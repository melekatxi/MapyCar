"""Modelo ORM de `share_grants`. Ref: diseño 6.1, 4.BE.5.

CHECK sujeto XOR token: interno (`subject_user_id`) o externo (`token_hash`), nunca
ambos ni ninguno. El token en claro no se persiste; solo el hash. Expiración
obligatoria si hay `token_hash`. Endpoints = 4.BE.6 / 4.BE.7.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

SHARE_PERMISSIONS = ("view", "edit")


class ShareGrant(Base):
    __tablename__ = "share_grants"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_share_grants_id_org"),
        CheckConstraint(
            "(subject_user_id IS NOT NULL AND token_hash IS NULL) "
            "OR (subject_user_id IS NULL AND token_hash IS NOT NULL)",
            name="ck_share_grants_subject_xor_token",
        ),
        CheckConstraint(
            "token_hash IS NULL OR expires_at IS NOT NULL",
            name="ck_share_grants_external_expires",
        ),
        CheckConstraint(f"permission IN {SHARE_PERMISSIONS}", name="ck_share_grants_permission"),
        ForeignKeyConstraint(
            ["route_id", "organization_id"],
            ["daily_routes.id", "daily_routes.organization_id"],
            name="fk_share_grants_route_org",
        ),
        ForeignKeyConstraint(
            ["subject_user_id", "organization_id"],
            ["user_memberships.user_id", "user_memberships.organization_id"],
            name="fk_share_grants_subject_org",
        ),
        Index("ix_share_grants_organization_id", "organization_id"),
        Index("ix_share_grants_route_id", "route_id"),
        Index(
            "uq_share_grants_token_hash",
            "token_hash",
            unique=True,
            postgresql_where=text("token_hash IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    route_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    permission: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
