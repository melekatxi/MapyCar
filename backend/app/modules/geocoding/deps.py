"""Dependencias FastAPI del módulo de geocodificación: adaptador, caché y autorización."""
from __future__ import annotations

import uuid
from functools import lru_cache

import redis
from fastapi import Depends
from sqlalchemy.orm import Session

from app.adapters.geocoder.interface import Geocoder
from app.adapters.geocoder.nominatim import NominatimGeocoder
from app.core.config import get_settings
from app.core.errors import DomainError
from app.db.session import get_db
from app.modules.geocoding.cache import GeocodeCache
from app.modules.identity import service as identity_service
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.imports.models import Address

# Bounding box aproximado de la Comunidad Autónoma Vasca (min_lon, min_lat, max_lon, max_lat). ADR-07.
EUSKADI_BOUNDING_BOX = (-3.6, 42.85, -1.9, 43.55)


@lru_cache
def get_geocoder() -> Geocoder:
    return NominatimGeocoder(get_settings().nominatim_base_url, bounding_box=EUSKADI_BOUNDING_BOX)


@lru_cache
def get_geocode_cache() -> GeocodeCache:
    return GeocodeCache(redis.Redis.from_url(get_settings().redis_url))


def get_address_for_member(
    address_id: uuid.UUID,
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Address:
    # organization_id explícito por el mismo motivo que en imports.deps.get_batch_for_member:
    # RLS necesita el contexto ANTES de poder leer la fila.
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if not identity_service.is_member_of_organization(db, user_id=current_user.id, organization_id=organization_id):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    address = db.get(Address, address_id)
    if address is None or address.organization_id != organization_id:
        raise DomainError(404, "ADDRESS_NOT_FOUND", "Dirección no encontrada")
    return address

