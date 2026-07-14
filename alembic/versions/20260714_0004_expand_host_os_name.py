"""expand host os name

Revision ID: 20260714_0004
Revises: 20260713_0003
Create Date: 2026-07-14 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0004"
down_revision: str | None = "20260713_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "hosts",
        "os_name",
        existing_type=sa.String(length=120),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "hosts",
        "os_name",
        existing_type=sa.Text(),
        type_=sa.String(length=120),
        existing_nullable=True,
    )
