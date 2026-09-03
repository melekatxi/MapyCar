"""routing: route_revisions, route_stops, route_metrics

Revision ID: c91d0e47f3b2
Revises: e4c8a2b91d07
Create Date: 2026-08-30 23:00:00.000000

FK circular: se crea route_revisions (FK a daily_routes) y después
daily_routes.current_revision → route_revisions.id.
Revisión published: CHECK status draft|published; inmutabilidad en aplicación
(no trigger). Snapshot de dirección cifrado (ADR-08) puede ir vacío hasta 3.BE.11.
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c91d0e47f3b2"
down_revision: str | None = "e4c8a2b91d07"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_RLS_TABLES = ("route_revisions", "route_stops", "route_metrics")


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_daily_routes_id_org", "daily_routes", ["id", "organization_id"]
    )
    op.create_table(
        "route_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("route_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("objective", sa.String(length=20), nullable=False),
        sa.Column("origin", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("destination", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("solver_status", sa.String(length=20), nullable=False),
        sa.Column(
            "constraints_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("osrm_dataset_version", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'published')",
            name="ck_route_revision_status",
        ),
        sa.CheckConstraint(
            "objective IN ('time', 'cost')",
            name="ck_route_revision_objective",
        ),
        sa.CheckConstraint(
            "solver_status IN ('pending', 'running', 'feasible', 'infeasible', "
            "'timeout', 'failed')",
            name="ck_route_revision_solver_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_route_revision_number"),
        sa.CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) "
            "OR (status = 'published' AND published_at IS NOT NULL)",
            name="ck_route_revision_published_at",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["route_id", "organization_id"],
            ["daily_routes.id", "daily_routes.organization_id"],
            name="fk_route_revisions_route_org",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "route_id",
            "revision",
            name="uq_route_revisions_route_revision",
        ),
        sa.UniqueConstraint("id", "organization_id", name="uq_route_revisions_id_org"),
    )
    op.create_index(
        "ix_route_revisions_organization_id", "route_revisions", ["organization_id"]
    )
    op.create_index("ix_route_revisions_route_id", "route_revisions", ["route_id"])
    op.create_index("ix_route_revisions_created_by", "route_revisions", ["created_by"])

    op.create_table(
        "route_stops",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("address_snapshot_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "location",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                from_text="ST_GeogFromText",
                name="geography",
                spatial_index=False,
            ),
            nullable=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("service_minutes", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.Time(), nullable=True),
        sa.Column("window_end", sa.Time(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'skipped')",
            name="ck_route_stop_status",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_route_stop_sequence"),
        sa.CheckConstraint("service_minutes >= 0", name="ck_route_stop_service_minutes"),
        sa.CheckConstraint("version >= 1", name="ck_route_stop_version"),
        sa.CheckConstraint(
            "window_start IS NULL OR window_end IS NULL OR window_start < window_end",
            name="ck_route_stop_window",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "organization_id"],
            ["route_revisions.id", "route_revisions.organization_id"],
            name="fk_route_stops_revision_org",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id", "organization_id"],
            ["patients.id", "patients.organization_id"],
            name="fk_route_stops_patient_org",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id",
            "sequence",
            name="uq_route_stops_revision_sequence",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "patient_id",
            name="uq_route_stops_revision_patient",
        ),
    )
    op.create_index(
        "ix_route_stops_organization_id", "route_stops", ["organization_id"]
    )
    op.create_index("ix_route_stops_revision_id", "route_stops", ["revision_id"])
    op.create_index("ix_route_stops_patient_id", "route_stops", ["patient_id"])
    op.create_index(
        "idx_route_stops_location",
        "route_stops",
        ["location"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "route_metrics",
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("variant", sa.String(length=20), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=False),
        sa.Column("travel_seconds", sa.Integer(), nullable=False),
        sa.Column("service_seconds", sa.Integer(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column(
            "calculation_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.CheckConstraint(
            "variant IN ('original', 'optimized', 'actual')",
            name="ck_route_metric_variant",
        ),
        sa.CheckConstraint("distance_m >= 0", name="ck_route_metric_distance"),
        sa.CheckConstraint("travel_seconds >= 0", name="ck_route_metric_travel"),
        sa.CheckConstraint("service_seconds >= 0", name="ck_route_metric_service"),
        sa.ForeignKeyConstraint(
            ["revision_id", "organization_id"],
            ["route_revisions.id", "route_revisions.organization_id"],
            name="fk_route_metrics_revision_org",
        ),
        sa.PrimaryKeyConstraint("revision_id", "variant"),
    )
    op.create_index(
        "ix_route_metrics_organization_id", "route_metrics", ["organization_id"]
    )
    op.create_index("ix_route_metrics_revision_id", "route_metrics", ["revision_id"])

    op.create_foreign_key(
        "fk_daily_routes_current_revision_org",
        "daily_routes",
        "route_revisions",
        ["current_revision", "organization_id"],
        ["id", "organization_id"],
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

    op.drop_constraint(
        "fk_daily_routes_current_revision_org", "daily_routes", type_="foreignkey"
    )
    op.drop_index("ix_route_metrics_revision_id", table_name="route_metrics")
    op.drop_index("ix_route_metrics_organization_id", table_name="route_metrics")
    op.drop_table("route_metrics")
    op.drop_index("idx_route_stops_location", table_name="route_stops")
    op.drop_index("ix_route_stops_patient_id", table_name="route_stops")
    op.drop_index("ix_route_stops_revision_id", table_name="route_stops")
    op.drop_index("ix_route_stops_organization_id", table_name="route_stops")
    op.drop_table("route_stops")
    op.drop_index("ix_route_revisions_created_by", table_name="route_revisions")
    op.drop_index("ix_route_revisions_route_id", table_name="route_revisions")
    op.drop_index("ix_route_revisions_organization_id", table_name="route_revisions")
    op.drop_table("route_revisions")
    op.drop_constraint("uq_daily_routes_id_org", "daily_routes", type_="unique")
