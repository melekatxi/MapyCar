"""Compartición interna y externa de rutas. Ref: 4.BE.6, 4.BE.7, RF-27, RF-28.

POST es 201 en la misma transacción (ledger `route.share`). GET no devuelve token.
El token externo (≥256 bit) solo se muestra una vez; en BD vive el SHA-256.
La vista pública oculta referencia, coords, estados y paciente.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.modules.identity import service as identity_service
from app.modules.identity.models import UserMembership
from app.modules.jobs.ledger import begin_idempotent_job
from app.modules.jobs.models import Job
from app.modules.notifications.models import (
    EVENT_SHARE_CREATED,
    EVENT_SHARE_REVOKED,
    RESOURCE_SHARE_GRANT,
)
from app.modules.notifications.service import record_event, schedule_outbox
from app.modules.planning.models import DailyRoute
from app.modules.routing.models import RouteStop
from app.modules.sharing.models import ShareGrant
from app.modules.sharing.schemas import (
    CreateShareRequest,
    PublicShareStopOut,
    PublicShareViewOut,
    ShareGrantListOut,
    ShareGrantOut,
)
from app.modules.sharing.tokens import (
    SESSION_TTL_SECONDS,
    generate_share_token,
    hash_share_token,
)

SHARE_JOB_TYPE = "route.share"
SHARE_RESOURCE_TYPE = "route"
SHARE_MANAGER_ROLES = ("admin", "planner")


def has_active_share(db: Session, *, route_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    now = datetime.now(UTC)
    grant = (
        db.query(ShareGrant)
        .filter(
            ShareGrant.route_id == route_id,
            ShareGrant.subject_user_id == user_id,
            ShareGrant.revoked_at.is_(None),
        )
        .one_or_none()
    )
    if grant is None:
        return False
    return grant.expires_at is None or grant.expires_at > now


def create_share(
    db: Session,
    route: DailyRoute,
    payload: CreateShareRequest,
    *,
    created_by: uuid.UUID,
    idempotency_key: str,
) -> ShareGrantOut:
    if payload.subject_user_id is None:
        return _create_external_share(
            db, route, payload, created_by=created_by, idempotency_key=idempotency_key
        )
    return _create_internal_share(
        db, route, payload, created_by=created_by, idempotency_key=idempotency_key
    )


def _normalize_expires(expires_at: datetime | None) -> datetime | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise DomainError(422, "SHARE_EXPIRES_IN_PAST", "expires_at debe ser futuro")
    return expires_at


def _begin_share_job(
    db: Session,
    route: DailyRoute,
    payload: CreateShareRequest,
    *,
    idempotency_key: str,
) -> Job:
    ledger_payload = {
        "route_id": str(route.id),
        **payload.model_dump(mode="json"),
    }
    return begin_idempotent_job(
        db,
        organization_id=route.organization_id,
        job_type=SHARE_JOB_TYPE,
        idempotency_key=idempotency_key,
        payload=ledger_payload,
        resource_type=SHARE_RESOURCE_TYPE,
        resource_id=route.id,
    )


def _create_internal_share(
    db: Session,
    route: DailyRoute,
    payload: CreateShareRequest,
    *,
    created_by: uuid.UUID,
    idempotency_key: str,
) -> ShareGrantOut:
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    assert payload.subject_user_id is not None
    if payload.subject_user_id == created_by:
        raise DomainError(422, "SHARE_SELF_NOT_ALLOWED", "No se puede compartir la ruta consigo mismo")
    expires_at = _normalize_expires(payload.expires_at)

    job = _begin_share_job(db, route, payload, idempotency_key=idempotency_key)
    if job.result_json:
        return ShareGrantOut.model_validate(job.result_json)

    membership = (
        db.query(UserMembership)
        .filter(
            UserMembership.user_id == payload.subject_user_id,
            UserMembership.organization_id == route.organization_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise DomainError(404, "SHARE_SUBJECT_NOT_FOUND", "El usuario no pertenece a la organización")

    existing = (
        db.query(ShareGrant)
        .filter(
            ShareGrant.route_id == route.id,
            ShareGrant.organization_id == route.organization_id,
            ShareGrant.subject_user_id == payload.subject_user_id,
            ShareGrant.revoked_at.is_(None),
        )
        .one_or_none()
    )
    if existing is not None:
        raise DomainError(409, "SHARE_ALREADY_EXISTS", "Ya existe una compartición activa para este usuario")

    grant = ShareGrant(
        organization_id=route.organization_id,
        route_id=route.id,
        subject_user_id=payload.subject_user_id,
        permission=payload.permission,
        expires_at=expires_at,
        created_by=created_by,
    )
    db.add(grant)
    db.flush()
    event = record_event(
        db,
        organization_id=route.organization_id,
        event_type=EVENT_SHARE_CREATED,
        resource_type=RESOURCE_SHARE_GRANT,
        resource_id=grant.id,
        payload={
            "route_id": str(route.id),
            "share_id": str(grant.id),
            "subject_user_id": str(payload.subject_user_id),
            "permission": payload.permission,
            "kind": "internal",
        },
    )
    out = _to_out(grant)
    job.status = "succeeded"
    job.progress = 100
    job.result_json = out.model_dump(mode="json")
    db.commit()
    schedule_outbox(event)
    db.refresh(grant)
    return _to_out(grant)


def _create_external_share(
    db: Session,
    route: DailyRoute,
    payload: CreateShareRequest,
    *,
    created_by: uuid.UUID,
    idempotency_key: str,
) -> ShareGrantOut:
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    expires_at = _normalize_expires(payload.expires_at)
    if expires_at is None:
        raise DomainError(422, "SHARE_EXPIRES_REQUIRED", "expires_at es obligatorio en compartición externa")

    job = _begin_share_job(db, route, payload, idempotency_key=idempotency_key)
    if job.result_json:
        return ShareGrantOut.model_validate(job.result_json)

    raw_token = generate_share_token()
    grant = ShareGrant(
        organization_id=route.organization_id,
        route_id=route.id,
        subject_user_id=None,
        permission="view",
        token_hash=hash_share_token(raw_token),
        expires_at=expires_at,
        created_by=created_by,
    )
    db.add(grant)
    db.flush()
    event = record_event(
        db,
        organization_id=route.organization_id,
        event_type=EVENT_SHARE_CREATED,
        resource_type=RESOURCE_SHARE_GRANT,
        resource_id=grant.id,
        payload={
            "route_id": str(route.id),
            "share_id": str(grant.id),
            "kind": "external",
        },
    )
    out = _to_out(grant, token=raw_token)
    job.status = "succeeded"
    job.progress = 100
    job.result_json = out.model_dump(mode="json")
    db.commit()
    schedule_outbox(event)
    db.refresh(grant)
    return _to_out(grant, token=raw_token)


def revoke_share(
    db: Session,
    *,
    share_id: uuid.UUID,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> None:
    """Marca revoked_at. El acceso (GET interno o exchange) falla en la siguiente petición."""
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    membership = (
        db.query(UserMembership)
        .filter(
            UserMembership.user_id == actor_id,
            UserMembership.organization_id == organization_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    if membership.role not in SHARE_MANAGER_ROLES:
        raise DomainError(403, "FORBIDDEN_ROLE", "Rol sin permiso para revocar comparticiones")

    grant = db.get(ShareGrant, share_id)
    if grant is None or grant.organization_id != organization_id:
        raise DomainError(404, "SHARE_NOT_FOUND", "Compartición no encontrada")
    if grant.revoked_at is not None:
        raise DomainError(409, "SHARE_ALREADY_REVOKED", "La compartición ya está revocada")

    grant.revoked_at = datetime.now(UTC)
    event = record_event(
        db,
        organization_id=organization_id,
        event_type=EVENT_SHARE_REVOKED,
        resource_type=RESOURCE_SHARE_GRANT,
        resource_id=grant.id,
        payload={
            "route_id": str(grant.route_id),
            "actor_id": str(actor_id),
            "kind": "external" if grant.token_hash else "internal",
        },
    )
    db.commit()
    schedule_outbox(event)


def list_shares(db: Session, route: DailyRoute) -> ShareGrantListOut:
    identity_service.set_current_organization_context(db, organization_id=route.organization_id)
    grants = (
        db.query(ShareGrant)
        .filter(
            ShareGrant.route_id == route.id,
            ShareGrant.organization_id == route.organization_id,
            ShareGrant.revoked_at.is_(None),
        )
        .order_by(ShareGrant.id)
        .all()
    )
    return ShareGrantListOut(grants=[_to_out(grant) for grant in grants])


def exchange_public_token(
    db: Session, *, token: str
) -> tuple[PublicShareViewOut, int, ShareGrant]:
    digest = hash_share_token(token.strip())
    row = db.execute(
        text("SELECT * FROM lookup_share_grant_by_token_hash(:h)"),
        {"h": digest},
    ).mappings().first()
    if row is None:
        raise DomainError(401, "SHARE_TOKEN_INVALID", "Token de compartición no válido")
    if row["revoked_at"] is not None:
        raise DomainError(410, "SHARE_REVOKED", "La compartición ha sido revocada")
    expires_at = row["expires_at"]
    now = datetime.now(UTC)
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at is not None and expires_at <= now:
        raise DomainError(410, "SHARE_EXPIRED", "La compartición ha caducado")

    org_id = row["organization_id"]
    identity_service.set_current_organization_context(db, organization_id=org_id)
    grant = db.get(ShareGrant, row["id"])
    if grant is None:
        raise DomainError(401, "SHARE_TOKEN_INVALID", "Token de compartición no válido")
    grant.last_accessed_at = now
    db.commit()

    route = db.get(DailyRoute, grant.route_id)
    if route is None:
        raise DomainError(404, "ROUTE_NOT_FOUND", "Ruta no encontrada")
    view = _minimized_view(db, route, grant)
    remaining = SESSION_TTL_SECONDS
    if grant.expires_at is not None:
        remaining = min(remaining, max(1, int((grant.expires_at - now).total_seconds())))
    return view, remaining, grant


def _minimized_view(db: Session, route: DailyRoute, grant: ShareGrant) -> PublicShareViewOut:
    stops: list[RouteStop] = []
    if route.current_revision is not None:
        stops = (
            db.query(RouteStop)
            .filter(
                RouteStop.revision_id == route.current_revision,
                RouteStop.organization_id == route.organization_id,
            )
            .order_by(RouteStop.sequence)
            .all()
        )
    return PublicShareViewOut(
        route_id=route.id,
        service_date=route.service_date,
        stop_count=len(stops),
        stops=[PublicShareStopOut(sequence=stop.sequence) for stop in stops],
        permission=grant.permission,
        expires_at=grant.expires_at,
    )


def _to_out(grant: ShareGrant, token: str | None = None) -> ShareGrantOut:
    return ShareGrantOut(
        id=grant.id,
        route_id=grant.route_id,
        subject_user_id=grant.subject_user_id,
        permission=grant.permission,
        expires_at=grant.expires_at,
        revoked_at=grant.revoked_at,
        created_by=grant.created_by,
        last_accessed_at=grant.last_accessed_at,
        kind="external" if grant.token_hash else "internal",
        token=token,
    )
