"""initial inventory schema

Revision ID: 20260713_0001
Revises:
Create Date: 2026-07-13 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hosts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hostname", sa.String(length=120), nullable=False),
        sa.Column("fqdn", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("environment", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("os_name", sa.String(length=120), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("owner_team", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("zabbix_hostid", sa.String(length=80), nullable=True),
        sa.Column("zabbix_host_name", sa.String(length=255), nullable=True),
        sa.Column("zabbix_url", sa.String(length=500), nullable=True),
        sa.Column("monitoring_status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hostname"),
    )
    op.create_index(op.f("ix_hosts_environment"), "hosts", ["environment"], unique=False)
    op.create_index(op.f("ix_hosts_hostname"), "hosts", ["hostname"], unique=False)
    op.create_index(op.f("ix_hosts_monitoring_status"), "hosts", ["monitoring_status"], unique=False)
    op.create_index(op.f("ix_hosts_role"), "hosts", ["role"], unique=False)
    op.create_index(op.f("ix_hosts_zabbix_hostid"), "hosts", ["zabbix_hostid"], unique=False)

    op.create_table(
        "clusters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("cluster_type", sa.String(length=80), nullable=False),
        sa.Column("environment", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("primary_node", sa.String(length=160), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_clusters_cluster_type"), "clusters", ["cluster_type"], unique=False)
    op.create_index(op.f("ix_clusters_environment"), "clusters", ["environment"], unique=False)
    op.create_index(op.f("ix_clusters_name"), "clusters", ["name"], unique=False)
    op.create_index(op.f("ix_clusters_status"), "clusters", ["status"], unique=False)

    op.create_table(
        "database_instances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("db_type", sa.String(length=60), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("environment", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("service_name", sa.String(length=160), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("powa_repository", sa.String(length=255), nullable=True),
        sa.Column("powa_server_name", sa.String(length=255), nullable=True),
        sa.Column("powa_database_name", sa.String(length=255), nullable=True),
        sa.Column("last_snapshot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_database_instances_db_type"), "database_instances", ["db_type"], unique=False)
    op.create_index(op.f("ix_database_instances_environment"), "database_instances", ["environment"], unique=False)
    op.create_index(op.f("ix_database_instances_host_id"), "database_instances", ["host_id"], unique=False)
    op.create_index(op.f("ix_database_instances_name"), "database_instances", ["name"], unique=False)
    op.create_index(op.f("ix_database_instances_powa_server_name"), "database_instances", ["powa_server_name"], unique=False)
    op.create_index(op.f("ix_database_instances_role"), "database_instances", ["role"], unique=False)
    op.create_index(op.f("ix_database_instances_status"), "database_instances", ["status"], unique=False)

    op.create_table(
        "cluster_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("database_instance_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("sync_state", sa.String(length=80), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["clusters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["database_instance_id"], ["database_instances.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_id", "database_instance_id", name="uq_cluster_member_instance"),
    )
    op.create_index(op.f("ix_cluster_members_cluster_id"), "cluster_members", ["cluster_id"], unique=False)
    op.create_index(
        op.f("ix_cluster_members_database_instance_id"),
        "cluster_members",
        ["database_instance_id"],
        unique=False,
    )
    op.create_index(op.f("ix_cluster_members_role"), "cluster_members", ["role"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_cluster_members_role"), table_name="cluster_members")
    op.drop_index(op.f("ix_cluster_members_database_instance_id"), table_name="cluster_members")
    op.drop_index(op.f("ix_cluster_members_cluster_id"), table_name="cluster_members")
    op.drop_table("cluster_members")

    op.drop_index(op.f("ix_database_instances_status"), table_name="database_instances")
    op.drop_index(op.f("ix_database_instances_role"), table_name="database_instances")
    op.drop_index(op.f("ix_database_instances_powa_server_name"), table_name="database_instances")
    op.drop_index(op.f("ix_database_instances_name"), table_name="database_instances")
    op.drop_index(op.f("ix_database_instances_host_id"), table_name="database_instances")
    op.drop_index(op.f("ix_database_instances_environment"), table_name="database_instances")
    op.drop_index(op.f("ix_database_instances_db_type"), table_name="database_instances")
    op.drop_table("database_instances")

    op.drop_index(op.f("ix_clusters_status"), table_name="clusters")
    op.drop_index(op.f("ix_clusters_name"), table_name="clusters")
    op.drop_index(op.f("ix_clusters_environment"), table_name="clusters")
    op.drop_index(op.f("ix_clusters_cluster_type"), table_name="clusters")
    op.drop_table("clusters")

    op.drop_index(op.f("ix_hosts_zabbix_hostid"), table_name="hosts")
    op.drop_index(op.f("ix_hosts_role"), table_name="hosts")
    op.drop_index(op.f("ix_hosts_monitoring_status"), table_name="hosts")
    op.drop_index(op.f("ix_hosts_hostname"), table_name="hosts")
    op.drop_index(op.f("ix_hosts_environment"), table_name="hosts")
    op.drop_table("hosts")
