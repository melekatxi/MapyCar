"""GET /history/routes. Ref: 4.BE.1, diseño 8.5."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.history import service
from app.modules.history.schemas import HistoryRoutesPage
from app.modules.identity.deps import require_organization_member
from app.modules.identity.models import User

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/routes", response_model=HistoryRoutesPage)
def list_history_routes(
    organization_id: uuid.UUID,
    current_user: User = Depends(require_organization_member),
    db: Session = Depends(get_db),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    zone: uuid.UUID | None = None,
    assignee: uuid.UUID | None = None,
    patient_ref: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> HistoryRoutesPage:
    return service.list_route_history(
        db,
        organization_id=organization_id,
        current_user=current_user,
        date_from=date_from,
        date_to=date_to,
        zone_id=zone,
        assignee_id=assignee,
        patient_ref=patient_ref,
        cursor=cursor,
        limit=limit,
    )
