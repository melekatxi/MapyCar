"""rls: aislamiento por organization_id

Revision ID: d67b2852712c
Revises: 5bd58fe9e9b2
Create Date: 2026-08-29 19:25:26.905828
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = 'd67b2852712c'
down_revision: str | None = '5bd58fe9e9b2'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


_TABLES = ("teams", "user_memberships")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE hace que la política aplique también al propietario de la tabla (rol de la app).
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid)
            WITH CHECK (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid)
            """
        )

    # Además del aislamiento por organización, un usuario siempre puede ver sus propias
    # membresías (necesario para /me, que lista organizaciones sin conocer una activa aún).
    # Las políticas permisivas del mismo comando (SELECT) se combinan con OR.
    op.execute(
        """
        CREATE POLICY self_membership_read_user_memberships ON user_memberships
        FOR SELECT
        USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS self_membership_read_user_memberships ON user_memberships"
    )
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
