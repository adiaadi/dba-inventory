"""add host db type

Revision ID: 20260713_0003
Revises: 20260713_0002
Create Date: 2026-07-13 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0003"
down_revision: str | None = "20260713_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("db_type", sa.String(length=60), nullable=True))
    op.create_index(op.f("ix_hosts_db_type"), "hosts", ["db_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_hosts_db_type"), table_name="hosts")
    op.drop_column("hosts", "db_type")
