"""notifications in-app consumidas desde outbox_events (4.BE.9)

Revision ID: c4f1d82e90a3
Revises: b3e8a14c90f1
Create Date: 2026-09-18 23:10:00.000000

No duplica outbox_events (2.BE.13, e4c8a2b91d07). event_id + recipient_id
hacen el consumo idempotente. GET/PATCH HTTP = 4.BE.10.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4f1d82e90a3"
down_revision: str | None = "b3e8a14c90f1"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_RLS_TABLES = ("notifications",)


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unread"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "\"type\" IN ('route.shared', 'route.reassigned', 'plan.published')",
            name="ck_notifications_type",
        ),
        sa.CheckConstraint(
            "status IN ('unread', 'read')",
            name="ck_notifications_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["recipient_id", "organization_id"],
            ["user_memberships.user_id", "user_memberships.organization_id"],
            name="fk_notifications_recipient_org",
        ),
        sa.ForeignKeyConstraint(
            ["event_id", "organization_id"],
            ["outbox_events.id", "outbox_events.organization_id"],
            name="fk_notifications_event_org",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_notifications_id_org"),
        sa.UniqueConstraint(
            "event_id",
            "recipient_id",
            name="uq_notifications_event_recipient",
        ),
    )
    op.create_index("ix_notifications_organization_id", "notifications", ["organization_id"])
    op.create_index(
        "ix_notifications_recipient_status",
        "notifications",
        ["recipient_id", "status"],
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

    op.drop_index("ix_notifications_recipient_status", table_name="notifications")
    op.drop_index("ix_notifications_organization_id", table_name="notifications")
    op.drop_table("notifications")
