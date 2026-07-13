from __future__ import annotations

from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models import Cluster, DatabaseInstance, Host

DEMO_CLUSTER_NAMES = [
    "payments-patroni-prod",
    "billing-oracle-standby",
    "crm-sql-log-shipping",
]

DEMO_DATABASE_NAMES = [
    "payments-pg-01",
    "payments-pg-02",
    "billing-ora-standby",
    "crm-sql-stage",
]

DEMO_HOSTNAMES = [
    "pg-prod-01",
    "pg-prod-02",
    "ora-standby-01",
    "mssql-stage-01",
]


def cleanup_demo_data() -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        clusters = db.execute(delete(Cluster).where(Cluster.name.in_(DEMO_CLUSTER_NAMES))).rowcount or 0
        databases = db.execute(
            delete(DatabaseInstance).where(DatabaseInstance.name.in_(DEMO_DATABASE_NAMES))
        ).rowcount or 0
        hosts = db.execute(delete(Host).where(Host.hostname.in_(DEMO_HOSTNAMES))).rowcount or 0
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return clusters, databases, hosts


def main() -> None:
    clusters, databases, hosts = cleanup_demo_data()
    print(f"Demo cleanup complete. Clusters: {clusters}. Databases: {databases}. Hosts: {hosts}.")


if __name__ == "__main__":
    main()
