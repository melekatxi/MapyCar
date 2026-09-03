from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str


class MembershipOut(BaseModel):
    organization_id: uuid.UUID
    role: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    memberships: list[MembershipOut]


class TeamOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    active: bool


class TeamsPage(BaseModel):
    teams: list[TeamOut]
