from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Cluster, ClusterMember, DatabaseInstance, Host
from app.routers.common import (
    active_filters,
    apply_cluster_filters,
    apply_host_filters,
    get_filter_options,
)
from app.web import templates

router = APIRouter()

DB_TYPE_VIEWS = {
    "oracle": {
        "label": "Oracle",
        "title": "ORACLE DATABASE INVENTORY",
        "db_types": ["Oracle"],
        "logo": "/static/img/oracle_logo.svg",
    },
    "postgresql": {
        "label": "PostgreSQL",
        "title": "POSTGRESQL DATABASE INVENTORY",
        "db_types": ["PostgreSQL"],
        "logo": "/static/img/postgresql_logo.svg",
    },
    "sqlserver": {
        "label": "SQLServer",
        "title": "SQLSERVER DATABASE INVENTORY",
        "db_types": ["SQL Server", "SQLServer"],
        "logo": "/static/img/sqlserver_logo.svg",
    },
}


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    view: str = "overview",
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
    db: Session = Depends(get_db),
):
    allowed_views = {"overview", "hosts", "databases", "clusters", *DB_TYPE_VIEWS.keys()}
    current_view = view if view in allowed_views else "overview"
    filters = active_filters(db_type, environment, role, monitoring_status)
    counts = {
        "hosts": db.scalar(select(func.count(Host.id))) or 0,
        "databases": db.scalar(select(func.count(DatabaseInstance.id))) or 0,
        "clusters": db.scalar(select(func.count(Cluster.id))) or 0,
    }
    host_db_assets = db.scalar(select(func.count(Host.id)).where(Host.db_type.is_not(None), Host.db_type != "")) or 0
    if host_db_assets:
        counts["databases"] = host_db_assets
    monitoring_counts = db.execute(
        select(Host.monitoring_status, func.count(Host.id))
        .group_by(Host.monitoring_status)
        .order_by(Host.monitoring_status)
    ).all()
    db_type_counts = db.execute(
        select(Host.db_type, func.count(Host.id))
        .where(Host.db_type.is_not(None), Host.db_type != "")
        .group_by(Host.db_type)
        .order_by(Host.db_type)
    ).all()
    if not db_type_counts:
        db_type_counts = db.execute(
            select(DatabaseInstance.db_type, func.count(DatabaseInstance.id))
            .group_by(DatabaseInstance.db_type)
            .order_by(DatabaseInstance.db_type)
        ).all()
    environment_counts = db.execute(
        select(Host.environment, func.count(Host.id))
        .group_by(Host.environment)
        .order_by(Host.environment)
    ).all()
    availability_counts = db.execute(
        select(Host.zabbix_agent_availability, func.count(Host.id))
        .group_by(Host.zabbix_agent_availability)
        .order_by(Host.zabbix_agent_availability)
    ).all()
    problem_total = db.scalar(select(func.coalesce(func.sum(Host.problem_count), 0))) or 0
    problem_average = round(problem_total / counts["hosts"], 2) if counts["hosts"] else 0
    last_sync_at = db.scalar(select(func.max(Host.zabbix_last_sync_at)))
    top_hosts = db.scalars(
        select(Host)
        .options(selectinload(Host.databases))
        .order_by(desc(Host.problem_count), Host.monitoring_status, Host.hostname)
        .limit(10)
    ).all()
    hosts_stmt = select(Host).options(selectinload(Host.databases)).order_by(Host.hostname)
    hosts_stmt = apply_host_filters(hosts_stmt, db_type, environment, role, monitoring_status)
    hosts_list = db.scalars(hosts_stmt).all()

    db_type_view = DB_TYPE_VIEWS.get(current_view)
    display_hosts = hosts_list
    if db_type_view:
        typed_hosts_stmt = (
            select(Host)
            .options(selectinload(Host.databases))
            .outerjoin(Host.databases)
            .where(
                or_(
                    Host.db_type.in_(db_type_view["db_types"]),
                    DatabaseInstance.db_type.in_(db_type_view["db_types"]),
                )
            )
            .distinct()
            .order_by(Host.hostname)
        )
        typed_hosts_stmt = apply_host_filters(typed_hosts_stmt, None, environment, role, monitoring_status)
        display_hosts = db.scalars(typed_hosts_stmt).all()

    database_assets_stmt = (
        select(Host)
        .options(selectinload(Host.databases))
        .where(Host.db_type.is_not(None), Host.db_type != "")
        .order_by(Host.db_type, Host.hostname)
    )
    database_assets_stmt = apply_host_filters(database_assets_stmt, db_type, environment, role, monitoring_status)
    database_assets = db.scalars(database_assets_stmt).all()

    clusters_stmt = (
        select(Cluster)
        .options(
            selectinload(Cluster.members)
            .selectinload(ClusterMember.database_instance)
            .selectinload(DatabaseInstance.host)
        )
        .order_by(Cluster.cluster_type, Cluster.name)
    )
    clusters_stmt = apply_cluster_filters(clusters_stmt, db_type, environment, role, monitoring_status)
    clusters = db.scalars(clusters_stmt).all()
    recent_snapshots = db.scalars(
        select(DatabaseInstance)
        .options(selectinload(DatabaseInstance.host))
        .where(DatabaseInstance.last_snapshot.is_not(None))
        .order_by(desc(DatabaseInstance.last_snapshot))
        .limit(6)
    ).all()
    chart_data = {
        "monitoringLabels": [status or "unknown" for status, _ in monitoring_counts],
        "monitoringValues": [count for _, count in monitoring_counts],
        "dbTypeLabels": [db_type or "unknown" for db_type, _ in db_type_counts],
        "dbTypeValues": [count for _, count in db_type_counts],
        "environmentLabels": [environment or "unknown" for environment, _ in environment_counts],
        "environmentValues": [count for _, count in environment_counts],
        "availabilityLabels": [availability or "unknown" for availability, _ in availability_counts],
        "availabilityValues": [count for _, count in availability_counts],
    }
    section_tabs = [
        {"key": "overview", "label": "Overview", "icon": "bi-grid-1x2"},
        {"key": "hosts", "label": "Hosts", "icon": "bi-hdd-network"},
        {"key": "oracle", "label": "Oracle", "icon": "bi-database"},
        {"key": "postgresql", "label": "PostgreSQL", "icon": "bi-database-fill"},
        {"key": "sqlserver", "label": "SQLServer", "icon": "bi-server"},
    ]
    section_titles = {
        "overview": "BNKC DATABASE INVENTORY OVERVIEW",
        "hosts": "HOST INVENTORY - STATUS UPDATE",
        "databases": "DB ASSETS - STATUS UPDATE",
        "clusters": "HA/DR CLUSTERS - STATUS UPDATE",
        **{key: config["title"] for key, config in DB_TYPE_VIEWS.items()},
    }
    section_subtitles = {
        "overview": f"{counts['hosts']} hosts, {counts['databases']} DB assets, {counts['clusters']} HA/DR clusters",
        "hosts": f"{len(hosts_list)} hosts in current view",
        "databases": f"{len(database_assets)} DB assets in current view",
        "clusters": f"{len(clusters)} clusters in current view",
        **{
            key: f"{len(display_hosts) if key == current_view else 0} hosts in current view"
            for key in DB_TYPE_VIEWS
        },
    }
    if db_type_view:
        section_subtitles[current_view] = f"{len(display_hosts)} {db_type_view['label']} hosts in current view"

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "active_page": "dashboard" if current_view == "overview" else current_view,
            "current_view": current_view,
            "section_tabs": section_tabs,
            "section_title": section_titles[current_view],
            "section_subtitle": section_subtitles[current_view],
            "section_logo": db_type_view["logo"] if db_type_view else None,
            "counts": counts,
            "hosts": hosts_list,
            "display_hosts": display_hosts,
            "db_type_view": db_type_view,
            "database_assets": database_assets,
            "monitoring_counts": monitoring_counts,
            "db_type_counts": db_type_counts,
            "environment_counts": environment_counts,
            "availability_counts": availability_counts,
            "problem_total": problem_total,
            "problem_average": problem_average,
            "last_sync_at": last_sync_at,
            "top_hosts": top_hosts,
            "chart_data": chart_data,
            "clusters": clusters,
            "recent_snapshots": recent_snapshots,
            "filters": filters,
            "filter_options": get_filter_options(db),
        },
    )
