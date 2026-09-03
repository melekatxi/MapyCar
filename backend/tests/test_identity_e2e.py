"""E2E de login y aislamiento por organización (rechazo 403 entre organizaciones). Ref: 0.BE.5."""
from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.modules.identity import service
from app.modules.identity.models import Organization, Team, User, UserMembership


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _create_user_with_membership(db: Session, *, organization: Organization, role: str = "planner") -> User:
    email = f"planner-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email_normalized=email,
        display_name="Planificadora de prueba",
        password_hash=hash_password("Sup3rSecreta!"),
    )
    db.add(user)
    db.flush()
    service.set_current_organization_context(db, organization_id=organization.id)
    db.add(UserMembership(organization_id=organization.id, user_id=user.id, role=role))
    db.commit()
    return user


def test_login_and_access_own_organization(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org propia")
    db_session.add(org)
    db_session.commit()
    user = _create_user_with_membership(db_session, organization=org)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": user.email_normalized, "password": "Sup3rSecreta!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    response = client.get(
        f"/api/v1/organizations/{org.id}/ping", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


def test_user_cannot_access_other_organization(client: TestClient, db_session: Session) -> None:
    own_org = Organization(name="Org propia")
    other_org = Organization(name="Org ajena")
    db_session.add_all([own_org, other_org])
    db_session.commit()
    user = _create_user_with_membership(db_session, organization=own_org)

    login = client.post(
        "/api/v1/auth/login",
        json={"email": user.email_normalized, "password": "Sup3rSecreta!"},
    )
    token = login.json()["access_token"]

    response = client.get(
        f"/api/v1/organizations/{other_org.id}/ping", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


def test_list_teams_is_scoped_to_organization(client: TestClient, db_session: Session) -> None:
    own_org = Organization(name="Org equipos propia")
    other_org = Organization(name="Org equipos ajena")
    db_session.add_all([own_org, other_org])
    db_session.commit()
    user = _create_user_with_membership(db_session, organization=own_org)

    own_org_id, other_org_id = own_org.id, other_org.id
    service.set_current_organization_context(db_session, organization_id=own_org_id)
    own_team = Team(organization_id=own_org_id, name="Equipo Bilbao")
    db_session.add(own_team)
    db_session.commit()
    own_team_id = own_team.id
    service.set_current_organization_context(db_session, organization_id=other_org_id)
    db_session.add(Team(organization_id=other_org_id, name="Equipo ajeno"))
    db_session.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": user.email_normalized, "password": "Sup3rSecreta!"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    listed = client.get(
        "/api/v1/teams",
        params={"organization_id": str(own_org_id)},
        headers=headers,
    )
    assert listed.status_code == 200
    teams = listed.json()["teams"]
    assert [item["name"] for item in teams] == ["Equipo Bilbao"]
    assert teams[0]["id"] == str(own_team_id)
    assert teams[0]["organization_id"] == str(own_org_id)
    assert teams[0]["active"] is True

    forbidden = client.get(
        "/api/v1/teams",
        params={"organization_id": str(other_org_id)},
        headers=headers,
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN_ORGANIZATION"


def test_login_rejects_wrong_password(client: TestClient, db_session: Session) -> None:
    org = Organization(name="Org propia")
    db_session.add(org)
    db_session.commit()
    user = _create_user_with_membership(db_session, organization=org)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email_normalized, "password": "incorrecta"},
    )
    assert response.status_code == 401
