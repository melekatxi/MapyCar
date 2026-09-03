"""zonas: zones, zone_assignments

Revision ID: 7f30767de9b7
Revises: 4de5ef6d835f
Create Date: 2026-08-30 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa

from alembic import op

revision: str = "7f30767de9b7"
down_revision: str | None = "4de5ef6d835f"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_RLS_TABLES = ("zones", "zone_assignments")


def upgrade() -> None:
    op.create_unique_constraint("uq_patients_id_org", "patients", ["id", "organization_id"])
    op.create_table(
        "zones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("max_visits", sa.Integer(), nullable=True),
        sa.Column(
            "boundary",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                dimension=2,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                spatial_index=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "centroid",
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
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind IN ('urban', 'rural', 'mixed')", name="ck_zone_kind"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_zones_org_name"),
        sa.UniqueConstraint("id", "organization_id", name="uq_zones_id_org"),
    )
    op.create_index("ix_zones_organization_id", "zones", ["organization_id"], unique=False)
    op.create_index(
        "idx_zones_boundary", "zones", ["boundary"], unique=False, postgresql_using="gist"
    )
    op.create_index(
        "idx_zones_centroid", "zones", ["centroid"], unique=False, postgresql_using="gist"
    )
    op.create_table(
        "zone_assignments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("zone_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "source IN ('cluster', 'postal', 'manual')", name="ck_zone_assignment_source"
        ),
        sa.ForeignKeyConstraint(
            ["zone_id", "organization_id"],
            ["zones.id", "zones.organization_id"],
            name="fk_zone_assignments_zone_org",
        ),
        sa.ForeignKeyConstraint(
            ["patient_id", "organization_id"],
            ["patients.id", "patients.organization_id"],
            name="fk_zone_assignments_patient_org",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_zone_assignments_current_patient",
        "zone_assignments",
        ["patient_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.create_index("ix_zone_assignments_zone_id", "zone_assignments", ["zone_id"], unique=False)
    op.create_index(
        "ix_zone_assignments_patient_id", "zone_assignments", ["patient_id"], unique=False
    )
    op.create_index(
        "ix_zone_assignments_organization_id",
        "zone_assignments",
        ["organization_id"],
        unique=False,
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

    op.drop_index("ix_zone_assignments_organization_id", table_name="zone_assignments")
    op.drop_index("ix_zone_assignments_patient_id", table_name="zone_assignments")
    op.drop_index("ix_zone_assignments_zone_id", table_name="zone_assignments")
    op.drop_index(
        "uq_zone_assignments_current_patient",
        table_name="zone_assignments",
        postgresql_where=sa.text("valid_to IS NULL"),
    )
    op.drop_table("zone_assignments")
    op.drop_index("idx_zones_centroid", table_name="zones")
    op.drop_index("idx_zones_boundary", table_name="zones")
    op.drop_index("ix_zones_organization_id", table_name="zones")
    op.drop_table("zones")
    op.drop_constraint("uq_patients_id_org", "patients", type_="unique")
