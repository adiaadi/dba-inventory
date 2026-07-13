from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Cluster, ClusterMember, DatabaseInstance, Host


def active_filters(
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
) -> dict[str, str]:
    values = {
        "db_type": db_type,
        "environment": environment,
        "role": role,
        "monitoring_status": monitoring_status,
    }
    return {key: value for key, value in values.items() if value}


def distinct_values(db: Session, column) -> list[str]:
    values = db.scalars(
        select(column).where(column.is_not(None), column != "").distinct().order_by(column)
    ).all()
    return [value for value in values if value]


def merged_distinct_values(db: Session, *columns) -> list[str]:
    values: set[str] = set()
    for column in columns:
        values.update(distinct_values(db, column))
    return sorted(values)


def get_filter_options(db: Session) -> dict[str, list[str]]:
    return {
        "db_types": distinct_values(db, DatabaseInstance.db_type),
        "environments": merged_distinct_values(db, Host.environment, DatabaseInstance.environment, Cluster.environment),
        "roles": merged_distinct_values(db, Host.role, DatabaseInstance.role, ClusterMember.role),
        "monitoring_statuses": distinct_values(db, Host.monitoring_status),
    }


def apply_host_filters(
    stmt: Select,
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
) -> Select:
    if db_type:
        stmt = stmt.join(Host.databases).where(DatabaseInstance.db_type == db_type).distinct()
    if environment:
        stmt = stmt.where(Host.environment == environment)
    if role:
        stmt = stmt.where(Host.role == role)
    if monitoring_status:
        stmt = stmt.where(Host.monitoring_status == monitoring_status)
    return stmt


def apply_database_filters(
    stmt: Select,
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
) -> Select:
    if monitoring_status:
        stmt = stmt.join(DatabaseInstance.host).where(Host.monitoring_status == monitoring_status)
    if db_type:
        stmt = stmt.where(DatabaseInstance.db_type == db_type)
    if environment:
        stmt = stmt.where(DatabaseInstance.environment == environment)
    if role:
        stmt = stmt.where(DatabaseInstance.role == role)
    return stmt


def apply_cluster_filters(
    stmt: Select,
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
) -> Select:
    if db_type or role or monitoring_status:
        stmt = stmt.join(Cluster.members).join(ClusterMember.database_instance)
        if db_type:
            stmt = stmt.where(DatabaseInstance.db_type == db_type)
        if role:
            stmt = stmt.where(ClusterMember.role == role)
        if monitoring_status:
            stmt = stmt.join(DatabaseInstance.host).where(Host.monitoring_status == monitoring_status)
        stmt = stmt.distinct()
    if environment:
        stmt = stmt.where(Cluster.environment == environment)
    return stmt
