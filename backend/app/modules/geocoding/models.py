"""Modelo ORM de intentos de geocodificación. Ref: diseño sección 6.1.

Solo la tabla; la lógica de scoring/consulta a Nominatim llega con 1.BE.8-1.BE.13.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from geoalchemy2 import Geography
from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.db.base import Base

GEOCODE_OUTCOMES = ("matched", "ambiguous", "not_found", "manual")


class GeocodeAttempt(Base):
    __tablename__ = "geocode_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    address_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("addresses.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_json_minimized: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    result_location = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
