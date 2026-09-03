"""planificacion: result_json, conflicts_json, job_id en monthly_plans

Revision ID: 024e6184b61b
Revises: c8e41f7a02b3
Create Date: 2026-08-30 21:00:00.000000

El solver de 2.BE.11 persiste calendario, asignaciones y conflictos en el plan.
No se reutiliza constraints_json (shape de CalendarConstraints). DailyRoute
queda para 2.BE.14 (assignee_id obligatorio).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "024e6184b61b"
down_revision: str | None = "c8e41f7a02b3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "monthly_plans",
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "monthly_plans",
        sa.Column(
            "conflicts_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("monthly_plans", sa.Column("job_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("monthly_plans", "job_id")
    op.drop_column("monthly_plans", "conflicts_json")
    op.drop_column("monthly_plans", "result_json")
