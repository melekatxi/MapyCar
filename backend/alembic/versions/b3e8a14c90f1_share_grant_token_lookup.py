"""Lookup de share_grants por token_hash sin contexto de org (4.BE.7).

Revision ID: b3e8a14c90f1
Revises: a7c4e91b02d8
Create Date: 2026-09-18 22:00:00.000000

SECURITY DEFINER: el canje público no conoce organization_id y RLS FORCE
ocultaría la fila. La función solo devuelve metadatos, nunca el token.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b3e8a14c90f1"
down_revision: str | None = "a7c4e91b02d8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.lookup_share_grant_by_token_hash(p_hash text)
        RETURNS TABLE (
            id uuid,
            organization_id uuid,
            route_id uuid,
            permission varchar,
            expires_at timestamptz,
            revoked_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT g.id, g.organization_id, g.route_id, g.permission, g.expires_at, g.revoked_at
            FROM share_grants g
            WHERE g.token_hash = p_hash
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.lookup_share_grant_by_token_hash(text)")
