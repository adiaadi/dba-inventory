from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, select
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
        "logo": "/static/img/oracle.png",
    },
    "postgresql": {
        "label": "PostgreSQL",
        "title": "POSTGRESQL DATABASE INVENTORY",
        "db_types": ["PostgreSQL"],
        "logo": "/static/img/postgresql.png",
    },
    "sqlserver": {
        "label": "SQLServer",
        "title": "SQLSERVER DATABASE INVENTORY",
        "db_types": ["SQL Server", "SQLServer"],
        "logo": "/static/img/sqlserver.png",
    },
}


def host_search_text(host: Host) -> str:
    return " ".join(
        value
        for value in (
            host.hostname,
            host.fqdn,
            host.db_type,
            host.zabbix_host_name,
            host.role,
            host.os_name,
            host.notes,
        )
        if value
    ).lower()


def detected_db_type(host: Host) -> str | None:
    text = host_search_text(host)
    hostname = (host.hostname or "").lower()
    if "postgresql" in text or "postgres" in text or hostname.startswith(("pg_", "pg-")):
        return "PostgreSQL"
    if "oracle" in text or "ora-" in hostname or hostname.startswith(("ora_", "ora-")):
        return "Oracle"
    if "sqlserver" in text or "sql server" in text or "mssql" in text:
        return "SQLServer"
    return None


def detected_server_platform(host: Host) -> str:
    text = host_search_text(host)
    virtual_markers = ("virtual", "vmware", "hyper-v", "hyperv", "kvm", "proxmox", "cloud", "-vm", "_vm")
    physical_markers = ("physical", "bare metal", "baremetal", "hardware")
    if any(marker in text for marker in virtual_markers):
        return "Virtual"
    if any(marker in text for marker in physical_markers):
        return "Physical"
    return "Unknown"


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
    all_hosts = db.scalars(select(Host).options(selectinload(Host.databases)).order_by(Host.hostname)).all()
    host_db_labels = {host.id: detected_db_type(host) for host in all_hosts}
    host_platform_labels = {host.id: detected_server_platform(host) for host in all_hosts}
    db_family_counts = {
        "Oracle": sum(1 for label in host_db_labels.values() if label == "Oracle"),
        "PostgreSQL": sum(1 for label in host_db_labels.values() if label == "PostgreSQL"),
        "SQLServer": sum(1 for label in host_db_labels.values() if label == "SQLServer"),
    }
    platform_counts = {
        "Virtual": sum(1 for label in host_platform_labels.values() if label == "Virtual"),
        "Physical": sum(1 for label in host_platform_labels.values() if label == "Physical"),
        "Unknown": sum(1 for label in host_platform_labels.values() if label == "Unknown"),
    }
    counts["databases"] = sum(db_family_counts.values())
    monitoring_counts = db.execute(
        select(Host.monitoring_status, func.count(Host.id))
        .group_by(Host.monitoring_status)
        .order_by(Host.monitoring_status)
    ).all()
    db_type_counts = [(label, count) for label, count in db_family_counts.items()]
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
    type_base_stmt = select(Host).options(selectinload(Host.databases)).order_by(Host.hostname)
    type_base_stmt = apply_host_filters(type_base_stmt, None, environment, role, monitoring_status)
    type_base_hosts = db.scalars(type_base_stmt).all()

    db_type_view = DB_TYPE_VIEWS.get(current_view)
    display_hosts = hosts_list
    if db_type_view:
        display_hosts = [
            host for host in type_base_hosts if host_db_labels.get(host.id) == db_type_view["label"]
        ]

    database_assets = [
        host for host in type_base_hosts if host_db_labels.get(host.id) in {"Oracle", "PostgreSQL", "SQLServer"}
    ]

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
        "platformLabels": list(platform_counts.keys()),
        "platformValues": list(platform_counts.values()),
    }
    section_tabs = [
        {"key": "overview", "label": "Overview", "icon": "bi-grid-1x2"},
        {"key": "hosts", "label": "Hosts", "icon": "bi-hdd-network"},
        {"key": "oracle", "label": "Oracle", "icon": "bi-database"},
        {"key": "postgresql", "label": "PostgreSQL", "icon": "bi-database-fill"},
        {"key": "sqlserver", "label": "SQLServer", "icon": "bi-server"},
    ]
    section_titles = {
        "overview": "DATABASE INVENTORY OVERVIEW",
        "hosts": "HOST INVENTORY - STATUS UPDATE",
        "databases": "DB ASSETS - STATUS UPDATE",
        "clusters": "HA/DR CLUSTERS - STATUS UPDATE",
        **{key: config["title"] for key, config in DB_TYPE_VIEWS.items()},
    }
    section_subtitles = {
        "overview": (
            f"{counts['hosts']} servers, Oracle {db_family_counts['Oracle']}, "
            f"PostgreSQL {db_family_counts['PostgreSQL']}, SQLServer {db_family_counts['SQLServer']}"
        ),
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
            "db_family_counts": db_family_counts,
            "platform_counts": platform_counts,
            "host_db_labels": host_db_labels,
            "host_platform_labels": host_platform_labels,
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
