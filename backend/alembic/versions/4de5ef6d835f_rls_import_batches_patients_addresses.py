"""rls import_batches patients addresses

Revision ID: 4de5ef6d835f
Revises: ca4dfdc05164
Create Date: 2026-08-29 22:32:10.374493
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = '4de5ef6d835f'
down_revision: str | None = 'ca4dfdc05164'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# import_rows y geocode_attempts no tienen organization_id propio (ref. diseño 6.1):
# su aislamiento se aplica en la capa de aplicación uniendo siempre con import_batches/addresses.
_TABLES = ("import_batches", "patients", "addresses")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid)
            WITH CHECK (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid)
            """
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
