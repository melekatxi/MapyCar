"""Dependencias FastAPI del módulo de importación: adaptadores y autorización por organización."""
from __future__ import annotations

import uuid
from functools import lru_cache

from fastapi import Depends, Form
from sqlalchemy.orm import Session

from app.adapters.object_store.fake import InMemoryObjectStore
from app.adapters.object_store.interface import ObjectStore
from app.adapters.object_store.s3 import S3ObjectStore
from app.core.config import get_settings
from app.core.crypto import EnvKeyProvider, FieldCipher, ObjectCipher
from app.core.errors import DomainError
from app.db.session import get_db
from app.modules.identity import service as identity_service
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User, UserMembership
from app.modules.imports.models import ImportBatch

IMPORT_CREATOR_ROLES = ("admin", "planner")


@lru_cache
def get_object_store() -> ObjectStore:
    settings = get_settings()
    if not settings.s3_endpoint_url.strip():
        return InMemoryObjectStore()
    return S3ObjectStore(
        endpoint_url=settings.s3_endpoint_url,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        cipher=ObjectCipher(EnvKeyProvider()),
    )


@lru_cache
def get_field_cipher() -> FieldCipher:
    return FieldCipher(EnvKeyProvider())


def require_import_creator(
    organization_id: uuid.UUID = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> tuple[User, uuid.UUID]:
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    membership = (
        db.query(UserMembership)
        .filter(
            UserMembership.user_id == current_user.id,
            UserMembership.organization_id == organization_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    if membership.role not in IMPORT_CREATOR_ROLES:
        raise DomainError(403, "FORBIDDEN_ROLE", "Rol sin permiso para importar")
    return current_user, organization_id


def get_batch_for_member(
    batch_id: uuid.UUID,
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ImportBatch:
    # organization_id se exige explícito (no solo en el path) porque las políticas RLS de
    # import_batches necesitan app.current_organization_id ANTES de poder leer la fila y así
    # conocer a qué organización pertenece; ver 4de5ef6d835f_rls_import_batches_patients_addresses.
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if not identity_service.is_member_of_organization(db, user_id=current_user.id, organization_id=organization_id):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.organization_id != organization_id:
        raise DomainError(404, "IMPORT_BATCH_NOT_FOUND", "Carga no encontrada")
    return batch


def require_organization_access(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if not identity_service.is_member_of_organization(db, user_id=current_user.id, organization_id=organization_id):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    return organization_id
