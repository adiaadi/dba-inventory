"""add zabbix sync fields

Revision ID: 20260713_0002
Revises: 20260713_0001
Create Date: 2026-07-13 11:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0002"
down_revision: str | None = "20260713_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hosts",
        sa.Column(
            "zabbix_agent_availability",
            sa.String(length=40),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "hosts",
        sa.Column("problem_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "hosts",
        sa.Column("zabbix_last_sync_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_hosts_zabbix_agent_availability"),
        "hosts",
        ["zabbix_agent_availability"],
        unique=False,
    )
    op.alter_column("hosts", "zabbix_agent_availability", server_default=None)
    op.alter_column("hosts", "problem_count", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_hosts_zabbix_agent_availability"), table_name="hosts")
    op.drop_column("hosts", "zabbix_last_sync_at")
    op.drop_column("hosts", "problem_count")
    op.drop_column("hosts", "zabbix_agent_availability")
