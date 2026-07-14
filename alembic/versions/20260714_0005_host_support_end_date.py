"""add host support end date

Revision ID: 20260714_0005
Revises: 20260714_0004
Create Date: 2026-07-14 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0005"
down_revision: str | None = "20260714_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("support_end_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("hosts", "support_end_date")
