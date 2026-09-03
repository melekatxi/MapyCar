"""planificacion: monthly_plans, daily_routes

Revision ID: bdf038e859a7
Revises: 7f30767de9b7
Create Date: 2026-08-30 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "bdf038e859a7"
down_revision: str | None = "7f30767de9b7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_RLS_TABLES = ("monthly_plans", "daily_routes")


def upgrade() -> None:
    op.create_unique_constraint("uq_teams_id_org", "teams", ["id", "organization_id"])
    op.create_table(
        "monthly_plans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("team_id", sa.UUID(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("constraints_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'validating', 'published', 'archived')",
            name="ck_monthly_plan_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["teams.id", "teams.organization_id"],
            name="fk_monthly_plans_team_org",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "team_id",
            "period",
            "version",
            name="uq_monthly_plans_org_team_period_version",
        ),
        sa.UniqueConstraint("id", "organization_id", name="uq_monthly_plans_id_org"),
    )
    op.create_index("ix_monthly_plans_organization_id", "monthly_plans", ["organization_id"])
    op.create_index("ix_monthly_plans_team_id", "monthly_plans", ["team_id"])
    op.create_index("ix_monthly_plans_created_by", "monthly_plans", ["created_by"])
    op.create_index(
        "ix_monthly_plans_org_period_status",
        "monthly_plans",
        ["organization_id", "period", "status"],
    )
    op.create_table(
        "daily_routes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("zone_id", sa.UUID(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("assignee_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_revision", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'optimizing', 'ready', 'published', "
            "'in_progress', 'completed', 'cancelled')",
            name="ck_daily_route_status",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["plan_id", "organization_id"],
            ["monthly_plans.id", "monthly_plans.organization_id"],
            name="fk_daily_routes_plan_org",
        ),
        sa.ForeignKeyConstraint(
            ["zone_id", "organization_id"],
            ["zones.id", "zones.organization_id"],
            name="fk_daily_routes_zone_org",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id", "organization_id"],
            ["user_memberships.user_id", "user_memberships.organization_id"],
            name="fk_daily_routes_assignee_org",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "service_date",
            "zone_id",
            "assignee_id",
            name="uq_daily_routes_plan_date_zone_assignee",
        ),
    )
    op.create_index("ix_daily_routes_organization_id", "daily_routes", ["organization_id"])
    op.create_index("ix_daily_routes_plan_id", "daily_routes", ["plan_id"])
    op.create_index("ix_daily_routes_zone_id", "daily_routes", ["zone_id"])
    op.create_index("ix_daily_routes_assignee_id", "daily_routes", ["assignee_id"])
    op.create_index(
        "ix_daily_routes_date_assignee_status",
        "daily_routes",
        ["service_date", "assignee_id", "status"],
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

    op.drop_index("ix_daily_routes_date_assignee_status", table_name="daily_routes")
    op.drop_index("ix_daily_routes_assignee_id", table_name="daily_routes")
    op.drop_index("ix_daily_routes_zone_id", table_name="daily_routes")
    op.drop_index("ix_daily_routes_plan_id", table_name="daily_routes")
    op.drop_index("ix_daily_routes_organization_id", table_name="daily_routes")
    op.drop_table("daily_routes")
    op.drop_index("ix_monthly_plans_org_period_status", table_name="monthly_plans")
    op.drop_index("ix_monthly_plans_created_by", table_name="monthly_plans")
    op.drop_index("ix_monthly_plans_team_id", table_name="monthly_plans")
    op.drop_index("ix_monthly_plans_organization_id", table_name="monthly_plans")
    op.drop_table("monthly_plans")
    op.drop_constraint("uq_teams_id_org", "teams", type_="unique")
