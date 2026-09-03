"""Propuestas de zonificación, publicación de zonas y override manual.

Ref: RF-09, RF-10, diseño §7.3 y §8.4.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from geoalchemy2 import Geometry
from sqlalchemy import bindparam, cast, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.router.interface import Router
from app.core.errors import DomainError
from app.modules.identity import service as identity_service
from app.modules.imports.models import Address, Patient
from app.modules.zoning.clustering import ClusteringResult, cluster_points
from app.modules.zoning.cohesion import FALLBACK_ROUTER_TABLE_FAILED, apply_cohesion
from app.modules.zoning.deps import get_router
from app.modules.zoning.fallback import FALLBACK_MUNICIPIO_CP, fallback_group
from app.modules.zoning.features import PointFeatures, ZoningPoint, compute_features
from app.modules.zoning.models import Zone, ZoneAssignment, ZoneProposal
from app.modules.zoning.schemas import (
    LonLatOut,
    ZoneAssignmentCurrentOut,
    ZoneCreateRequest,
    ZoneGeometryIn,
    ZoneListItemOut,
    ZoneOut,
    ZonePatchRequest,
)

# Confirmados: diseño 7.3 paso 1. pending/ambiguous/not_found quedan fuera.
CONFIRMED_GEOCODE_STATUSES = ("matched", "manual")
MIN_CONFIRMED_POINTS = 2
DEFAULT_STRATEGY = "auto"
# Depósito por defecto: Abando (Bilbao), mismo origen que features/clustering.
BILBAO_DEPOT_LON = -2.9348
BILBAO_DEPOT_LAT = 43.2630


class ZoneProposalJobError(Exception):
    """Error de dominio en el worker: se persiste `failed` y no se reintenta."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def list_confirmed_points(db: Session, *, organization_id: uuid.UUID) -> list[ZoningPoint]:
    """Direcciones activas con geocode confirmado y coordenadas. Excluye pending/ambiguous/not_found."""
    rows = (
        db.query(
            Address.patient_id,
            Address.municipality,
            Address.postal_code,
            func.ST_X(cast(Address.location, Geometry)),
            func.ST_Y(cast(Address.location, Geometry)),
        )
        .join(Patient, Patient.id == Address.patient_id)
        .filter(
            Address.organization_id == organization_id,
            Patient.organization_id == organization_id,
            Address.is_active.is_(True),
            Address.geocode_status.in_(CONFIRMED_GEOCODE_STATUSES),
            Address.location.isnot(None),
        )
        .all()
    )
    points: list[ZoningPoint] = []
    for patient_id, municipality, postal_code, lon, lat in rows:
        if lon is None or lat is None:
            continue
        points.append(
            ZoningPoint(
                longitude=float(lon),
                latitude=float(lat),
                point_id=str(patient_id),
                municipality=municipality,
                postal_code=postal_code,
            )
        )
    return points


def create_proposal(
    db: Session,
    *,
    organization_id: uuid.UUID,
    max_visits: int,
    target_zones: int | None = None,
    strategy: str | None = None,
    depot_lon: float | None = None,
    depot_lat: float | None = None,
) -> ZoneProposal:
    """Valida geocodes/capacidad y deja la propuesta en `queued`. El caller encola el job."""
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    if max_visits < 1:
        raise DomainError(422, "INVALID_CAPACITY", "max_visits debe ser >= 1")
    if target_zones is not None and target_zones < 1:
        raise DomainError(422, "INVALID_TARGET_ZONES", "target_zones debe ser >= 1")
    if (depot_lon is None) ^ (depot_lat is None):
        raise DomainError(422, "INCOMPLETE_DEPOT", "depot_lon y depot_lat deben ir juntos")

    confirmed = list_confirmed_points(db, organization_id=organization_id)
    if len(confirmed) < MIN_CONFIRMED_POINTS:
        raise DomainError(
            422,
            "INSUFFICIENT_GEOCODES",
            "Se necesitan al menos 2 direcciones con geocode confirmado (matched o manual)",
        )

    resolved_lon = BILBAO_DEPOT_LON if depot_lon is None else depot_lon
    resolved_lat = BILBAO_DEPOT_LAT if depot_lat is None else depot_lat
    proposal = ZoneProposal(
        organization_id=organization_id,
        status="queued",
        params_json={
            "max_visits": max_visits,
            "target_zones": target_zones,
            "strategy": strategy or DEFAULT_STRATEGY,
            "depot_lon": resolved_lon,
            "depot_lat": resolved_lat,
        },
        result_json={},
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def attach_job(db: Session, proposal: ZoneProposal, *, job_id: str) -> ZoneProposal:
    proposal.job_id = job_id
    proposal.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(proposal)
    return proposal


def run_zone_proposal(
    db: Session,
    *,
    proposal_id: uuid.UUID,
    organization_id: uuid.UUID,
    router: Router | None = None,
) -> ZoneProposal:
    """Worker de la cola `zoning`: features, clustering, cohesión viaria y persistencia."""
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    proposal = db.get(ZoneProposal, proposal_id)
    if proposal is None or proposal.organization_id != organization_id:
        raise ZoneProposalJobError("ZONE_PROPOSAL_NOT_FOUND", "Propuesta no encontrada")

    proposal.status = "running"
    proposal.error_code = None
    proposal.updated_at = datetime.now(UTC)
    db.commit()

    try:
        result_json = _compute_proposal_result(db, proposal, router=router)
    except ZoneProposalJobError as exc:
        proposal.status = "failed"
        proposal.error_code = exc.code
        proposal.updated_at = datetime.now(UTC)
        db.commit()
        return proposal
    except Exception:
        proposal.status = "failed"
        proposal.error_code = "CLUSTERING_FAILED"
        proposal.updated_at = datetime.now(UTC)
        db.commit()
        raise

    proposal.status = "succeeded"
    proposal.result_json = result_json
    proposal.error_code = None
    proposal.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(proposal)
    return proposal


def run_proposal_clustering(
    features: Sequence[PointFeatures],
    *,
    max_visits: int,
    target_zones: int | None = None,
    router: Router,
) -> tuple[ClusteringResult, dict]:
    """Clustering + cohesión OSRM. Si `Router.table` falla, fallback municipio/CP."""
    clustering = cluster_points(features, max_visits=max_visits, target_zones=target_zones)
    cohesion = asyncio.run(apply_cohesion(clustering, features, router, max_visits=max_visits))
    extra: dict = {"used_router": cohesion.used_router}
    if cohesion.fallback_reason == FALLBACK_ROUTER_TABLE_FAILED:
        extra["fallback"] = FALLBACK_MUNICIPIO_CP
        extra["used_router"] = False
        return fallback_group(features, max_visits=max_visits), extra
    return cohesion.clustering, extra


def _compute_proposal_result(
    db: Session, proposal: ZoneProposal, *, router: Router | None = None
) -> dict:
    params = proposal.params_json or {}
    max_visits = int(params["max_visits"])
    target_zones = params.get("target_zones")
    target_zones_int = int(target_zones) if target_zones is not None else None
    depot = ZoningPoint(
        longitude=float(params.get("depot_lon", BILBAO_DEPOT_LON)),
        latitude=float(params.get("depot_lat", BILBAO_DEPOT_LAT)),
        point_id="depot",
        municipality="Bilbao",
        postal_code="48001",
    )
    points = list_confirmed_points(db, organization_id=proposal.organization_id)
    if len(points) < MIN_CONFIRMED_POINTS:
        raise ZoneProposalJobError(
            "INSUFFICIENT_GEOCODES",
            "Se necesitan al menos 2 direcciones con geocode confirmado",
        )
    features = compute_features(points, depot)
    resolved = router if router is not None else get_router()
    clustering, extra = run_proposal_clustering(
        features, max_visits=max_visits, target_zones=target_zones_int, router=resolved
    )
    return _serialize_result(clustering, features, max_visits=max_visits, extra_metrics=extra)


def _serialize_result(
    clustering: ClusteringResult,
    features: list[PointFeatures],
    *,
    max_visits: int,
    extra_metrics: dict | None = None,
) -> dict:
    by_id = {point.point_id: point for point in features if point.point_id}
    clusters_out: list[dict] = []
    assignments: list[dict] = []
    max_cluster_size = 0
    for cluster in clustering.clusters:
        members = [by_id[member_id] for member_id in cluster.member_ids if member_id in by_id]
        max_cluster_size = max(max_cluster_size, len(cluster.member_ids))
        if members:
            centroid = {
                "lon": sum(member.longitude for member in members) / len(members),
                "lat": sum(member.latitude for member in members) / len(members),
            }
        else:
            centroid = None
        clusters_out.append(
            {
                "cluster_id": cluster.cluster_id,
                "kind": cluster.kind,
                "member_ids": list(cluster.member_ids),
                "centroid": centroid,
                "centroid_xy": [cluster.centroid_xy[0], cluster.centroid_xy[1]],
            }
        )
        assignments.extend(
            {"patient_id": member_id, "cluster_id": cluster.cluster_id}
            for member_id in cluster.member_ids
        )
    return {
        "clusters": clusters_out,
        "assignments": assignments,
        "outliers": list(clustering.outliers),
        "metrics": {
            "n_points": len(features),
            "n_clusters": len(clustering.clusters),
            "n_outliers": len(clustering.outliers),
            "max_cluster_size": max_cluster_size,
            "max_visits": max_visits,
            **(extra_metrics or {}),
        },
    }


def to_zone_out(db: Session, zone: Zone) -> ZoneOut:
    return ZoneOut(
        id=zone.id,
        organization_id=zone.organization_id,
        name=zone.name,
        kind=zone.kind,
        max_visits=zone.max_visits,
        version=zone.version,
        centroid=_read_centroid(db, zone),
        assignments=_current_assignment_outs(db, zone.id),
    )


def list_zones(db: Session, *, organization_id: uuid.UUID) -> list[ZoneListItemOut]:
    """Zonas de la organización con ocupación vigente, capacidad y versión (2.FE.1)."""
    identity_service.set_current_organization_context(db, organization_id=organization_id)
    occupancy_rows = (
        db.query(ZoneAssignment.zone_id, func.count(ZoneAssignment.id))
        .filter(
            ZoneAssignment.organization_id == organization_id,
            ZoneAssignment.valid_to.is_(None),
        )
        .group_by(ZoneAssignment.zone_id)
        .all()
    )
    counts = {zone_id: int(count) for zone_id, count in occupancy_rows}
    rows = (
        db.query(
            Zone,
            func.ST_X(cast(Zone.centroid, Geometry)),
            func.ST_Y(cast(Zone.centroid, Geometry)),
        )
        .filter(Zone.organization_id == organization_id)
        .order_by(Zone.name)
        .all()
    )
    items: list[ZoneListItemOut] = []
    for zone, lon, lat in rows:
        centroid = None
        if lon is not None and lat is not None:
            centroid = LonLatOut(lon=float(lon), lat=float(lat))
        items.append(
            ZoneListItemOut(
                id=zone.id,
                organization_id=zone.organization_id,
                name=zone.name,
                kind=zone.kind,
                max_visits=zone.max_visits,
                version=zone.version,
                patient_count=counts.get(zone.id, 0),
                centroid=centroid,
            )
        )
    return items


def create_zone(db: Session, payload: ZoneCreateRequest) -> Zone:
    identity_service.set_current_organization_context(db, organization_id=payload.organization_id)
    name = _normalize_zone_name(payload.name)
    _ensure_unique_name(db, organization_id=payload.organization_id, name=name)
    zone = Zone(
        organization_id=payload.organization_id,
        name=name,
        kind=payload.kind,
        max_visits=payload.max_visits,
        version=1,
    )
    _apply_centroid(zone, payload.centroid)
    if payload.geometry is not None:
        zone.boundary = _geometry_to_wkt(payload.geometry)
    db.add(zone)
    _commit_zone(db)
    db.refresh(zone)
    return zone


def patch_zone(
    db: Session, zone: Zone, payload: ZonePatchRequest, *, expected_version: int
) -> Zone:
    identity_service.set_current_organization_context(db, organization_id=zone.organization_id)
    _require_version(zone, expected_version)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise DomainError(422, "ZONE_PATCH_EMPTY", "No hay campos para actualizar")
    if "name" in updates:
        name = _normalize_zone_name(updates["name"])
        _ensure_unique_name(db, organization_id=zone.organization_id, name=name, exclude_id=zone.id)
        zone.name = name
    if "kind" in updates:
        zone.kind = updates["kind"]
    if "max_visits" in updates:
        _ensure_capacity_fits(db, zone_id=zone.id, max_visits=updates["max_visits"])
        zone.max_visits = updates["max_visits"]
    if "centroid" in updates:
        _apply_centroid(zone, payload.centroid)
    if "geometry" in updates:
        zone.boundary = None if payload.geometry is None else _geometry_to_wkt(payload.geometry)
    zone.version = expected_version + 1
    _commit_zone(db)
    db.refresh(zone)
    return zone


def assign_patient_manual(
    db: Session,
    zone: Zone,
    *,
    patient_id: uuid.UUID,
    reason: str,
    expected_version: int,
) -> Zone:
    identity_service.set_current_organization_context(db, organization_id=zone.organization_id)
    _require_version(zone, expected_version)
    reason_clean = reason.strip()
    if not reason_clean:
        raise DomainError(422, "OVERRIDE_REASON_REQUIRED", "El motivo es obligatorio")
    patient = db.get(Patient, patient_id)
    if patient is None or patient.organization_id != zone.organization_id:
        raise DomainError(404, "PATIENT_NOT_FOUND", "Paciente no encontrado")

    current = _current_assignment(db, patient_id=patient_id)
    already_here = current is not None and current.zone_id == zone.id
    occupancy = _occupancy(db, zone.id)
    projected = occupancy if already_here else occupancy + 1
    if zone.max_visits is not None and projected > zone.max_visits:
        raise DomainError(
            409, "ZONE_CAPACITY_EXCEEDED", "La zona no admite más visitas con max_visits actual"
        )

    now = datetime.now(UTC)
    if current is not None:
        current.valid_to = now
        db.flush()
    db.add(
        ZoneAssignment(
            organization_id=zone.organization_id,
            zone_id=zone.id,
            patient_id=patient.id,
            source="manual",
            valid_from=now,
            valid_to=None,
            override_reason=reason_clean,
        )
    )
    zone.version = expected_version + 1
    db.commit()
    db.refresh(zone)
    return zone


def accept_proposal(
    db: Session, proposal: ZoneProposal, *, reset_overrides: bool = False
) -> tuple[list[Zone], int]:
    """Materializa clusters en `zones`/`zone_assignments`. No pisa overrides manuales vigentes."""
    identity_service.set_current_organization_context(db, organization_id=proposal.organization_id)
    if proposal.status != "succeeded":
        raise DomainError(
            409,
            "ZONE_PROPOSAL_NOT_SUCCEEDED",
            f"La propuesta no se puede aceptar en estado {proposal.status}",
        )

    result = proposal.result_json or {}
    clusters = result.get("clusters") or []
    params = proposal.params_json or {}
    max_visits = params.get("max_visits")
    max_visits_int = int(max_visits) if max_visits is not None else None

    cluster_zones: dict[str, Zone] = {}
    for cluster in clusters:
        zone = _upsert_zone_from_cluster(
            db,
            organization_id=proposal.organization_id,
            cluster=cluster,
            max_visits=max_visits_int,
        )
        cluster_zones[cluster["cluster_id"]] = zone

    proposed: dict[uuid.UUID, Zone] = {}
    for item in result.get("assignments") or []:
        cluster_id = item["cluster_id"]
        if cluster_id not in cluster_zones:
            continue
        proposed[uuid.UUID(str(item["patient_id"]))] = cluster_zones[cluster_id]

    now = datetime.now(UTC)
    current_rows = (
        db.query(ZoneAssignment)
        .filter(
            ZoneAssignment.organization_id == proposal.organization_id,
            ZoneAssignment.valid_to.is_(None),
        )
        .all()
    )
    current_by_patient = {row.patient_id: row for row in current_rows}

    for patient_id, zone in proposed.items():
        existing = current_by_patient.get(patient_id)
        if existing is not None and existing.source == "manual" and not reset_overrides:
            continue
        if existing is not None and existing.zone_id == zone.id and existing.source == "cluster":
            continue
        if existing is not None:
            existing.valid_to = now
            db.flush()
        db.add(
            ZoneAssignment(
                organization_id=proposal.organization_id,
                zone_id=zone.id,
                patient_id=patient_id,
                source="cluster",
                valid_from=now,
                valid_to=None,
                override_reason=None,
            )
        )

    proposed_ids = set(proposed)
    for existing in current_rows:
        if existing.patient_id in proposed_ids:
            continue
        if existing.source == "manual" and not reset_overrides:
            continue
        if existing.valid_to is None:
            existing.valid_to = now

    zone_ids = [zone.id for zone in cluster_zones.values()]
    db.commit()
    zones = (
        db.query(Zone).filter(Zone.id.in_(zone_ids)).order_by(Zone.name).all() if zone_ids else []
    )
    preserved = (
        db.query(ZoneAssignment)
        .filter(
            ZoneAssignment.organization_id == proposal.organization_id,
            ZoneAssignment.source == "manual",
            ZoneAssignment.valid_to.is_(None),
        )
        .count()
    )
    return zones, preserved


def _require_version(zone: Zone, expected_version: int) -> None:
    if zone.version != expected_version:
        raise DomainError(409, "ZONE_VERSION_CONFLICT", "La zona ha sido modificada")


def _normalize_zone_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise DomainError(422, "INVALID_ZONE_NAME", "El nombre no puede estar vacío")
    return cleaned


def _ensure_unique_name(
    db: Session,
    *,
    organization_id: uuid.UUID,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    query = db.query(Zone).filter(Zone.organization_id == organization_id, Zone.name == name)
    if exclude_id is not None:
        query = query.filter(Zone.id != exclude_id)
    if query.one_or_none() is not None:
        raise DomainError(409, "ZONE_NAME_CONFLICT", "Ya existe una zona con ese nombre")


def _ensure_capacity_fits(db: Session, *, zone_id: uuid.UUID, max_visits: int | None) -> None:
    if max_visits is None:
        return
    occupancy = _occupancy(db, zone_id)
    if occupancy > max_visits:
        raise DomainError(
            409, "ZONE_CAPACITY_EXCEEDED", "Hay más asignaciones vigentes que el nuevo max_visits"
        )


def _occupancy(db: Session, zone_id: uuid.UUID) -> int:
    return (
        db.query(ZoneAssignment)
        .filter(ZoneAssignment.zone_id == zone_id, ZoneAssignment.valid_to.is_(None))
        .count()
    )


def _current_assignment(db: Session, *, patient_id: uuid.UUID) -> ZoneAssignment | None:
    return (
        db.query(ZoneAssignment)
        .filter(ZoneAssignment.patient_id == patient_id, ZoneAssignment.valid_to.is_(None))
        .one_or_none()
    )


def _current_assignment_outs(db: Session, zone_id: uuid.UUID) -> list[ZoneAssignmentCurrentOut]:
    rows = (
        db.query(ZoneAssignment)
        .filter(ZoneAssignment.zone_id == zone_id, ZoneAssignment.valid_to.is_(None))
        .order_by(ZoneAssignment.valid_from)
        .all()
    )
    return [
        ZoneAssignmentCurrentOut(
            patient_id=row.patient_id, source=row.source, override_reason=row.override_reason
        )
        for row in rows
    ]


def _read_centroid(db: Session, zone: Zone) -> LonLatOut | None:
    if zone.centroid is None:
        return None
    lon, lat = db.execute(
        text("SELECT ST_X(centroid::geometry), ST_Y(centroid::geometry) FROM zones WHERE id = :id"),
        {"id": zone.id},
    ).one()
    if lon is None or lat is None:
        return None
    return LonLatOut(lon=float(lon), lat=float(lat))


def _apply_centroid(zone: Zone, centroid: LonLatOut | None) -> None:
    if centroid is None:
        zone.centroid = None
        return
    zone.centroid = f"SRID=4326;POINT({centroid.lon} {centroid.lat})"


def _geometry_to_wkt(geometry: ZoneGeometryIn) -> str:
    if geometry.type == "Polygon":
        polygons = [geometry.coordinates]
    else:
        polygons = geometry.coordinates
    if not isinstance(polygons, list) or not polygons:
        raise DomainError(422, "INVALID_GEOMETRY", "geometry no contiene polígonos")
    rendered: list[str] = []
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise DomainError(422, "INVALID_GEOMETRY", "Cada polígono necesita al menos un anillo")
        rings = [_ring_to_wkt(ring) for ring in polygon]
        rendered.append("(" + ", ".join(rings) + ")")
    return "SRID=4326;MULTIPOLYGON(" + ", ".join(rendered) + ")"


def _ring_to_wkt(ring: object) -> str:
    if not isinstance(ring, list) or len(ring) < 3:
        raise DomainError(422, "INVALID_GEOMETRY", "Cada anillo necesita al menos 3 posiciones")
    points: list[str] = []
    for position in ring:
        if not isinstance(position, (list, tuple)) or len(position) < 2:
            raise DomainError(422, "INVALID_GEOMETRY", "Cada posición debe ser [lon, lat]")
        try:
            lon = float(position[0])
            lat = float(position[1])
        except (TypeError, ValueError) as exc:
            raise DomainError(422, "INVALID_GEOMETRY", "Coordenadas no numéricas") from exc
        points.append(f"{lon} {lat}")
    if points[0] != points[-1]:
        points.append(points[0])
    if len(points) < 4:
        raise DomainError(422, "INVALID_GEOMETRY", "El anillo no cierra un polígono")
    return "(" + ", ".join(points) + ")"


def _upsert_zone_from_cluster(
    db: Session,
    *,
    organization_id: uuid.UUID,
    cluster: dict,
    max_visits: int | None,
) -> Zone:
    name = str(cluster["cluster_id"])
    kind = cluster.get("kind") or "mixed"
    if kind not in ("urban", "rural", "mixed"):
        kind = "mixed"
    zone = (
        db.query(Zone)
        .filter(Zone.organization_id == organization_id, Zone.name == name)
        .one_or_none()
    )
    centroid_raw = cluster.get("centroid") or {}
    centroid = None
    if centroid_raw.get("lon") is not None and centroid_raw.get("lat") is not None:
        centroid = LonLatOut(lon=float(centroid_raw["lon"]), lat=float(centroid_raw["lat"]))
    if zone is None:
        zone = Zone(
            organization_id=organization_id,
            name=name,
            kind=kind,
            max_visits=max_visits,
            version=1,
        )
        db.add(zone)
        db.flush()
    else:
        zone.kind = kind
        zone.max_visits = max_visits
        zone.version += 1
    _apply_centroid(zone, centroid)
    _apply_cluster_hull(db, zone, cluster.get("member_ids") or [])
    db.flush()
    return zone


def _apply_cluster_hull(db: Session, zone: Zone, member_ids: list) -> None:
    # Hull opcional: 1-2 puntos no dan MULTIPOLYGON; se deja solo el centroide.
    uuids: list[uuid.UUID] = []
    for member_id in member_ids:
        try:
            uuids.append(uuid.UUID(str(member_id)))
        except ValueError:
            continue
    if len(uuids) < 3:
        return
    stmt = text(
        """
        SELECT ST_AsEWKT(hull), ST_GeometryType(hull)
        FROM (
            SELECT ST_Multi(ST_ConvexHull(ST_Collect(location::geometry))) AS hull
            FROM addresses
            WHERE organization_id = :org_id
              AND patient_id IN :patient_ids
              AND is_active IS TRUE
              AND location IS NOT NULL
        ) s
        """
    ).bindparams(bindparam("patient_ids", expanding=True))
    row = db.execute(stmt, {"org_id": zone.organization_id, "patient_ids": uuids}).one()
    ewkt, geom_type = row
    if ewkt and geom_type == "ST_MultiPolygon":
        zone.boundary = ewkt


def _commit_zone(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        orig = str(getattr(exc, "orig", exc))
        if "uq_zones_org_name" in orig:
            raise DomainError(
                409, "ZONE_NAME_CONFLICT", "Ya existe una zona con ese nombre"
            ) from exc
        raise DomainError(409, "ZONE_CONFLICT", "No se pudo guardar la zona") from exc
