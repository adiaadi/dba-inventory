from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Cluster, ClusterMember, DatabaseInstance, Host


def seed() -> None:
    db = SessionLocal()
    try:
        existing_hosts = db.scalar(select(func.count(Host.id))) or 0
        if existing_hosts:
            return

        pg_primary = Host(
            hostname="pg-prod-01",
            fqdn="pg-prod-01.example.local",
            ip_address="10.10.1.11",
            environment="prod",
            role="database",
            db_type="PostgreSQL",
            os_name="Ubuntu 24.04 LTS",
            location="dc-east",
            owner_team="DBA",
            zabbix_hostid="10451",
            zabbix_host_name="pg-prod-01",
            zabbix_url="https://zabbix.example.local/hosts.php?hostid=10451",
            zabbix_agent_availability="available",
            problem_count=0,
            monitoring_status="ok",
        )
        pg_replica = Host(
            hostname="pg-prod-02",
            fqdn="pg-prod-02.example.local",
            ip_address="10.10.1.12",
            environment="prod",
            role="database",
            db_type="PostgreSQL",
            os_name="Ubuntu 24.04 LTS",
            location="dc-west",
            owner_team="DBA",
            zabbix_hostid="10452",
            zabbix_host_name="pg-prod-02",
            zabbix_url="https://zabbix.example.local/hosts.php?hostid=10452",
            zabbix_agent_availability="available",
            problem_count=1,
            monitoring_status="warning",
        )
        oracle_host = Host(
            hostname="ora-standby-01",
            fqdn="ora-standby-01.example.local",
            ip_address="10.20.5.31",
            environment="prod",
            role="standby",
            db_type="Oracle",
            os_name="Oracle Linux 9",
            location="dc-east",
            owner_team="DBA",
            zabbix_hostid="10610",
            zabbix_host_name="ora-standby-01",
            zabbix_url="https://zabbix.example.local/hosts.php?hostid=10610",
            zabbix_agent_availability="available",
            problem_count=0,
            monitoring_status="ok",
        )
        sql_host = Host(
            hostname="mssql-stage-01",
            fqdn="mssql-stage-01.example.local",
            ip_address="10.30.2.21",
            environment="stage",
            role="database",
            db_type="SQL Server",
            os_name="Windows Server 2022",
            location="dc-lab",
            owner_team="BI",
            zabbix_hostid="10820",
            zabbix_host_name="mssql-stage-01",
            zabbix_url="https://zabbix.example.local/hosts.php?hostid=10820",
            zabbix_agent_availability="unknown",
            problem_count=0,
            monitoring_status="maintenance",
        )

        now = datetime.now(UTC)
        pg_main = DatabaseInstance(
            host=pg_primary,
            name="payments-pg-01",
            db_type="PostgreSQL",
            version="16",
            port=5432,
            environment="prod",
            role="primary",
            service_name="payments",
            powa_repository="powa_prod",
            powa_server_name="pg-prod-01",
            powa_database_name="payments",
            last_snapshot=now - timedelta(minutes=12),
            status="ok",
        )
        pg_standby = DatabaseInstance(
            host=pg_replica,
            name="payments-pg-02",
            db_type="PostgreSQL",
            version="16",
            port=5432,
            environment="prod",
            role="replica",
            service_name="payments",
            powa_repository="powa_prod",
            powa_server_name="pg-prod-02",
            powa_database_name="payments",
            last_snapshot=now - timedelta(hours=2),
            status="warning",
        )
        oracle_standby = DatabaseInstance(
            host=oracle_host,
            name="billing-ora-standby",
            db_type="Oracle",
            version="19c",
            port=1521,
            environment="prod",
            role="physical standby",
            service_name="billing",
            status="ok",
        )
        sql_log_shipping = DatabaseInstance(
            host=sql_host,
            name="crm-sql-stage",
            db_type="SQL Server",
            version="2022",
            port=1433,
            environment="stage",
            role="secondary",
            service_name="crm",
            status="maintenance",
        )

        patroni = Cluster(
            name="payments-patroni-prod",
            cluster_type="Patroni",
            environment="prod",
            status="degraded",
            primary_node="pg-prod-01",
            description="PostgreSQL HA cluster for payments service.",
            members=[
                ClusterMember(database_instance=pg_main, role="leader", sync_state="sync", priority=100),
                ClusterMember(database_instance=pg_standby, role="replica", sync_state="async", priority=90),
            ],
        )
        oracle_cluster = Cluster(
            name="billing-oracle-standby",
            cluster_type="Oracle Standby",
            environment="prod",
            status="ok",
            primary_node="billing-ora-primary",
            members=[
                ClusterMember(database_instance=oracle_standby, role="standby", sync_state="apply", priority=50),
            ],
        )
        sql_cluster = Cluster(
            name="crm-sql-log-shipping",
            cluster_type="SQL Server Log Shipping",
            environment="stage",
            status="maintenance",
            primary_node="crm-sql-primary",
            members=[
                ClusterMember(database_instance=sql_log_shipping, role="secondary", sync_state="restoring", priority=10),
            ],
        )

        db.add_all([patroni, oracle_cluster, sql_cluster])
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
