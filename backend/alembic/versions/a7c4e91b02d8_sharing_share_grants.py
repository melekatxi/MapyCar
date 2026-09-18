"""sharing: share_grants con CHECK sujeto XOR token

Revision ID: a7c4e91b02d8
Revises: d02e1f58a4c3
Create Date: 2026-09-18 21:20:00.000000

Interno: subject_user_id NOT NULL y token_hash NULL.
Externo: token_hash NOT NULL, subject_user_id NULL y expires_at obligatorio.
Solo se guarda el hash del token. Endpoints en 4.BE.6 / 4.BE.7.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c4e91b02d8"
down_revision: str | None = "d02e1f58a4c3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_RLS_TABLES = ("share_grants",)


def upgrade() -> None:
    op.create_table(
        "share_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("route_id", sa.UUID(), nullable=False),
        sa.Column("subject_user_id", sa.UUID(), nullable=True),
        sa.Column("permission", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(subject_user_id IS NOT NULL AND token_hash IS NULL) "
            "OR (subject_user_id IS NULL AND token_hash IS NOT NULL)",
            name="ck_share_grants_subject_xor_token",
        ),
        sa.CheckConstraint(
            "token_hash IS NULL OR expires_at IS NOT NULL",
            name="ck_share_grants_external_expires",
        ),
        sa.CheckConstraint(
            "permission IN ('view', 'edit')",
            name="ck_share_grants_permission",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["route_id", "organization_id"],
            ["daily_routes.id", "daily_routes.organization_id"],
            name="fk_share_grants_route_org",
        ),
        sa.ForeignKeyConstraint(
            ["subject_user_id", "organization_id"],
            ["user_memberships.user_id", "user_memberships.organization_id"],
            name="fk_share_grants_subject_org",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_share_grants_id_org"),
    )
    op.create_index("ix_share_grants_organization_id", "share_grants", ["organization_id"])
    op.create_index("ix_share_grants_route_id", "share_grants", ["route_id"])
    op.create_index(
        "uq_share_grants_token_hash",
        "share_grants",
        ["token_hash"],
        unique=True,
        postgresql_where=sa.text("token_hash IS NOT NULL"),
    )

    for table in _RLS_TABLES:
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
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("uq_share_grants_token_hash", table_name="share_grants")
    op.drop_index("ix_share_grants_route_id", table_name="share_grants")
    op.drop_index("ix_share_grants_organization_id", table_name="share_grants")
    op.drop_table("share_grants")
