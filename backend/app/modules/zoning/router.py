"""Endpoints de zonas y propuestas. Ref: diseño sección 8.4, RF-09, RF-10."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.session import get_db
from app.jobs.queue import JobQueue, get_job_queue
from app.modules.identity import service as identity_service
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import User
from app.modules.zoning import service
from app.modules.zoning.deps import get_proposal_for_member, get_zone_for_member, require_if_match
from app.modules.zoning.models import Zone, ZoneProposal
from app.modules.zoning.schemas import (
    LonLatOut,
    ZoneAcceptResponse,
    ZoneCreateRequest,
    ZoneOut,
    ZoneOverrideRequest,
    ZonePatchRequest,
    ZoneProposalAssignmentOut,
    ZoneProposalClusterOut,
    ZoneProposalCreateRequest,
    ZoneProposalCreateResponse,
    ZoneProposalMetricsOut,
    ZoneProposalOut,
    ZonesPage,
)

proposals_router = APIRouter(prefix="/zone-proposals", tags=["zoning"])
zones_router = APIRouter(prefix="/zones", tags=["zoning"])
router = APIRouter()
router.include_router(proposals_router)
router.include_router(zones_router)

_NOT_READY_STATUSES = frozenset({"queued", "running"})


def _etag(version: int) -> str:
    return f'"{version}"'


def _set_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = _etag(version)


@proposals_router.post("", status_code=202, response_model=ZoneProposalCreateResponse)
def create_zone_proposal(
    payload: ZoneProposalCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    queue: JobQueue = Depends(get_job_queue),
) -> ZoneProposalCreateResponse:
    identity_service.set_current_organization_context(db, organization_id=payload.organization_id)
    if not identity_service.is_member_of_organization(
        db, user_id=current_user.id, organization_id=payload.organization_id
    ):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")

    proposal = service.create_proposal(
        db,
        organization_id=payload.organization_id,
        max_visits=payload.max_visits,
        target_zones=payload.target_zones,
        strategy=payload.strategy,
        depot_lon=payload.depot_lon,
        depot_lat=payload.depot_lat,
    )
    job = queue.enqueue(
        queue="zoning",
        payload={"proposal_id": str(proposal.id), "organization_id": str(payload.organization_id)},
    )
    proposal = service.attach_job(db, proposal, job_id=job.id)
    return ZoneProposalCreateResponse(id=proposal.id, job_id=job.id, status=proposal.status)


@proposals_router.get("/{proposal_id}", response_model=ZoneProposalOut)
def get_zone_proposal(proposal: ZoneProposal = Depends(get_proposal_for_member)) -> ZoneProposalOut:
    # Diseño 8.4: GET 409 mientras el job no ha terminado. Terminales (succeeded/failed) → 200.
    if proposal.status in _NOT_READY_STATUSES:
        raise DomainError(
            409,
            "ZONE_PROPOSAL_NOT_READY",
            f"La propuesta sigue en estado {proposal.status}",
        )
    return _to_out(proposal)


@proposals_router.post("/{proposal_id}/accept", response_model=ZoneAcceptResponse)
def accept_zone_proposal(
    reset_overrides: bool = False,
    proposal: ZoneProposal = Depends(get_proposal_for_member),
    db: Session = Depends(get_db),
) -> ZoneAcceptResponse:
    zones, preserved = service.accept_proposal(db, proposal, reset_overrides=reset_overrides)
    return ZoneAcceptResponse(
        zones=[service.to_zone_out(db, zone) for zone in zones],
        preserved_override_count=preserved,
    )


@zones_router.get("", response_model=ZonesPage)
def list_zones(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ZonesPage:
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if not identity_service.is_member_of_organization(
        db, user_id=current_user.id, organization_id=organization_id
    ):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    return ZonesPage(zones=service.list_zones(db, organization_id=organization_id))


@zones_router.post("", status_code=201, response_model=ZoneOut)
def create_zone(
    payload: ZoneCreateRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ZoneOut:
    identity_service.set_current_organization_context(db, organization_id=payload.organization_id)
    if not identity_service.is_member_of_organization(
        db, user_id=current_user.id, organization_id=payload.organization_id
    ):
        raise DomainError(403, "FORBIDDEN_ORGANIZATION", "Sin acceso a esta organización")
    zone = service.create_zone(db, payload)
    _set_etag(response, zone.version)
    return service.to_zone_out(db, zone)


@zones_router.get("/{zone_id}", response_model=ZoneOut)
def get_zone(
    response: Response,
    zone: Zone = Depends(get_zone_for_member),
    db: Session = Depends(get_db),
) -> ZoneOut:
    _set_etag(response, zone.version)
    return service.to_zone_out(db, zone)


@zones_router.patch("/{zone_id}", response_model=ZoneOut)
def patch_zone(
    payload: ZonePatchRequest,
    response: Response,
    zone: Zone = Depends(get_zone_for_member),
    expected_version: int = Depends(require_if_match),
    db: Session = Depends(get_db),
) -> ZoneOut:
    updated = service.patch_zone(db, zone, payload, expected_version=expected_version)
    _set_etag(response, updated.version)
    return service.to_zone_out(db, updated)


@zones_router.put("/{zone_id}/patients/{patient_id}", status_code=204)
def override_zone_patient(
    patient_id: uuid.UUID,
    payload: ZoneOverrideRequest,
    response: Response,
    zone: Zone = Depends(get_zone_for_member),
    expected_version: int = Depends(require_if_match),
    db: Session = Depends(get_db),
) -> None:
    updated = service.assign_patient_manual(
        db,
        zone,
        patient_id=patient_id,
        reason=payload.reason,
        expected_version=expected_version,
    )
    _set_etag(response, updated.version)


def _to_out(proposal: ZoneProposal) -> ZoneProposalOut:
    result = proposal.result_json or {}
    clusters = [
        ZoneProposalClusterOut(
            cluster_id=cluster["cluster_id"],
            kind=cluster["kind"],
            member_ids=[uuid.UUID(member_id) for member_id in cluster.get("member_ids", [])],
            centroid=_centroid_out(cluster.get("centroid")),
        )
        for cluster in result.get("clusters", [])
    ]
    assignments = [
        ZoneProposalAssignmentOut(
            patient_id=uuid.UUID(item["patient_id"]),
            cluster_id=item["cluster_id"],
        )
        for item in result.get("assignments", [])
    ]
    outliers = [uuid.UUID(item) for item in result.get("outliers", [])]
    metrics_raw = result.get("metrics")
    metrics = ZoneProposalMetricsOut(**metrics_raw) if metrics_raw else None
    return ZoneProposalOut(
        id=proposal.id,
        organization_id=proposal.organization_id,
        status=proposal.status,
        job_id=proposal.job_id,
        params=proposal.params_json or {},
        clusters=clusters,
        assignments=assignments,
        outliers=outliers,
        metrics=metrics,
        error_code=proposal.error_code,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


def _centroid_out(raw: dict | None) -> LonLatOut | None:
    if not raw or raw.get("lon") is None or raw.get("lat") is None:
        return None
    return LonLatOut(lon=float(raw["lon"]), lat=float(raw["lat"]))
