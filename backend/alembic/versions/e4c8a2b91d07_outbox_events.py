"""planificacion: outbox_events para POST /plans/{id}/publish

Revision ID: e4c8a2b91d07
Revises: 024e6184b61b
Create Date: 2026-08-30 22:00:00.000000

Delta vs 4.BE.9 / diseño 6.1: no existe `notifications` todavía. 2.BE.13 necesita
un outbox transaccional (sección 11.1) en la misma transacción que daily_routes.
`processed_at` queda nulo; el consumidor llega en Fase 4.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e4c8a2b91d07"
down_revision: str | None = "024e6184b61b"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_RLS_TABLES = ("outbox_events",)


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_outbox_events_id_org"),
    )
    op.create_index("ix_outbox_events_organization_id", "outbox_events", ["organization_id"])
    op.create_index(
        "ix_outbox_events_resource",
        "outbox_events",
        ["resource_type", "resource_id"],
    )
    op.create_index(
        "ix_outbox_events_unprocessed",
        "outbox_events",
        ["processed_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
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

    op.drop_index("ix_outbox_events_unprocessed", table_name="outbox_events")
    op.drop_index("ix_outbox_events_resource", table_name="outbox_events")
    op.drop_index("ix_outbox_events_organization_id", table_name="outbox_events")
    op.drop_table("outbox_events")
