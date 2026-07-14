from collections import Counter

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
        "title": "ORACLE",
        "db_types": ["Oracle"],
        "logo": "/static/img/oracle.png",
    },
    "postgresql": {
        "label": "PostgreSQL",
        "title": "POSTGRESQL",
        "db_types": ["PostgreSQL"],
        "logo": "/static/img/postgresql.png",
    },
    "sqlserver": {
        "label": "SQLServer",
        "title": "SQL SERVER",
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


def normalized_db_type(value: str | None) -> str | None:
    text = (value or "").lower().replace("_", " ").replace("-", " ")
    if "postgresql" in text or "postgres" in text:
        return "PostgreSQL"
    if "oracle" in text:
        return "Oracle"
    if "sqlserver" in text or "sql server" in text or "mssql" in text:
        return "SQLServer"
    return None


def imported_zabbix_tags(host: Host) -> dict[str, list[str]]:
    notes = host.notes or ""
    marker = "Zabbix tags:"
    if marker not in notes:
        return {}
    tag_text = notes.split(marker, 1)[1].split(";", 1)[0]
    tags: dict[str, list[str]] = {}
    for item in tag_text.split(","):
        if "=" not in item:
            continue
        tag_name, tag_value = item.split("=", 1)
        tag_name = tag_name.strip().lower()
        tag_value = tag_value.strip()
        if tag_name and tag_value:
            tags.setdefault(tag_name, []).append(tag_value)
    return tags


def imported_zabbix_inventory(host: Host) -> dict[str, str]:
    notes = host.notes or ""
    marker = "Zabbix inventory:"
    if marker not in notes:
        return {}
    inventory_text = notes.split(marker, 1)[1].split(";", 1)[0]
    inventory: dict[str, str] = {}
    for item in inventory_text.split(","):
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            inventory[key] = value
    return inventory


def first_tag_value(host: Host, tag_names: tuple[str, ...]) -> str | None:
    tags = imported_zabbix_tags(host)
    for tag_name in tag_names:
        values = tags.get(tag_name)
        if values:
            return values[0]
    return None


def has_tag_value(host: Host, tag_name: str, expected_value: str) -> bool:
    tags = imported_zabbix_tags(host)
    return any(value.lower() == expected_value.lower() for value in tags.get(tag_name, []))


def detected_db_type(host: Host) -> str | None:
    tags = imported_zabbix_tags(host)
    for tag_name in ("database", "server"):
        for tag_value in tags.get(tag_name, []):
            detected = normalized_db_type(tag_value)
            if detected:
                return detected

    for value in (
        host.db_type,
        host.notes,
        host.zabbix_host_name,
        host.hostname,
        host.fqdn,
    ):
        detected = normalized_db_type(value)
        if detected:
            return detected

    hostname = (host.hostname or "").lower()
    if hostname.startswith(("pg_", "pg-")):
        return "PostgreSQL"
    if "ora-" in hostname or hostname.startswith(("ora_", "ora-")):
        return "Oracle"
    return None


def is_os_class_host(host: Host) -> bool:
    return has_tag_value(host, "class", "os")


def unique_hosts(hosts: list[Host]) -> list[Host]:
    seen: set[str] = set()
    unique: list[Host] = []
    for host in hosts:
        key = str(host.zabbix_hostid or host.hostname or host.id).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(host)
    return unique


def detected_server_platform(host: Host) -> str:
    text = host_search_text(host)
    virtual_markers = ("virtual", "vmware", "hyper-v", "hyperv", "kvm", "proxmox", "cloud", "-vm", "_vm")
    physical_markers = ("physical", "bare metal", "baremetal", "hardware")
    if any(marker in text for marker in virtual_markers):
        return "Virtual"
    if any(marker in text for marker in physical_markers):
        return "Physical"
    return "Unknown"


def is_virtual_server(host: Host) -> bool:
    explicit_value = first_tag_value(host, ("virtual", "is_virtual", "vm"))
    if explicit_value:
        return explicit_value.lower() in {"1", "true", "yes", "y", "virtual", "vm"}
    type_value = first_tag_value(host, ("type", "server_type", "platform"))
    if type_value and type_value.lower() in {"virtual", "vm", "vmware", "hyper-v", "hyperv", "kvm"}:
        return True
    return detected_server_platform(host) == "Virtual"


def operating_system_label(host: Host) -> str:
    inventory = imported_zabbix_inventory(host)
    return (
        host.os_name
        or inventory.get("os_full")
        or inventory.get("os")
        or inventory.get("os_short")
        or "-"
    )


def server_model_label(host: Host) -> str:
    tag_value = first_tag_value(host, ("server_model", "model", "hardware_model"))
    if tag_value:
        return tag_value

    inventory = imported_zabbix_inventory(host)
    vendor = inventory.get("vendor")
    model = inventory.get("model")
    if vendor and model:
        return f"{vendor} {model}"
    return (
        model
        or inventory.get("hardware_full")
        or inventory.get("hardware")
        or inventory.get("chassis")
        or "-"
    )


def server_core_label(host: Host) -> str:
    return first_tag_value(host, ("core", "cores", "cpu_core", "cpu_cores", "vcpu", "vcpus", "cpu")) or "-"


def server_ram_label(host: Host) -> str:
    return first_tag_value(host, ("ram", "memory", "mem", "ram_gb", "memory_gb")) or "-"


def imported_zabbix_group_names(host: Host) -> list[str]:
    notes = host.notes or ""
    marker = "Imported from Zabbix groups:"
    if marker not in notes:
        return []
    group_text = notes.split(marker, 1)[1].split(";", 1)[0]
    return [group_name.strip() for group_name in group_text.split(",") if group_name.strip()]


def is_database_group_name(group_name: str) -> bool:
    normalized = group_name.strip().lower()
    return normalized.endswith(" database") or normalized.endswith(" databases")


def is_server_group_name(group_name: str) -> bool:
    normalized = group_name.strip().lower()
    return normalized.endswith(" server") or normalized.endswith(" servers")


def detected_zabbix_asset_kind(host: Host) -> str:
    tags = imported_zabbix_tags(host)
    if tags.get("database"):
        return "database"
    if tags.get("server"):
        return "server"

    group_names = imported_zabbix_group_names(host)
    if any(is_database_group_name(group_name) for group_name in group_names):
        return "database"
    if any(is_server_group_name(group_name) for group_name in group_names):
        return "server"

    role = (host.role or "").lower()
    if "server" in role:
        return "server"
    return "database"


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    view: str = "overview",
    asset_view: str = "databases",
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
    db: Session = Depends(get_db),
):
    allowed_views = {"overview", "hosts", "databases", "clusters", *DB_TYPE_VIEWS.keys()}
    current_view = view if view in allowed_views else "overview"
    current_asset_view = asset_view if asset_view in {"databases", "servers"} else "databases"
    filters = active_filters(db_type, environment, role, monitoring_status)
    counts = {
        "hosts": db.scalar(select(func.count(Host.id))) or 0,
        "databases": db.scalar(select(func.count(DatabaseInstance.id))) or 0,
        "clusters": db.scalar(select(func.count(Cluster.id))) or 0,
    }
    all_hosts = db.scalars(select(Host).options(selectinload(Host.databases)).order_by(Host.hostname)).all()
    host_db_labels = {host.id: detected_db_type(host) for host in all_hosts}
    host_platform_labels = {host.id: detected_server_platform(host) for host in all_hosts}
    host_asset_kinds = {host.id: detected_zabbix_asset_kind(host) for host in all_hosts}
    host_virtual_labels = {host.id: "YES" if is_virtual_server(host) else "NO" for host in all_hosts}
    host_os_labels = {host.id: operating_system_label(host) for host in all_hosts}
    host_model_labels = {host.id: server_model_label(host) for host in all_hosts}
    host_core_labels = {host.id: server_core_label(host) for host in all_hosts}
    host_ram_labels = {host.id: server_ram_label(host) for host in all_hosts}
    os_class_hosts = unique_hosts([host for host in all_hosts if is_os_class_host(host)])
    server_hosts = os_class_hosts
    db_family_counts = {
        family: sum(
            1
            for host in all_hosts
            if host_db_labels.get(host.id) == family and host_asset_kinds.get(host.id) == "database"
        )
        for family in ("Oracle", "PostgreSQL", "SQLServer")
    }
    db_family_server_counts = {
        family: sum(
            1
            for host in server_hosts
            if host_db_labels.get(host.id) == family
        )
        for family in ("Oracle", "PostgreSQL", "SQLServer")
    }
    platform_counts = {
        "Virtual": sum(1 for host in server_hosts if host_platform_labels.get(host.id) == "Virtual"),
        "Physical": sum(1 for host in server_hosts if host_platform_labels.get(host.id) == "Physical"),
        "Unknown": sum(1 for host in server_hosts if host_platform_labels.get(host.id) == "Unknown"),
    }
    counts["databases"] = sum(db_family_counts.values())
    counts["servers"] = len(server_hosts)
    monitoring_counter = Counter(host.monitoring_status or "unknown" for host in server_hosts)
    monitoring_counts = sorted(monitoring_counter.items())
    db_type_counts = [(label, count) for label, count in db_family_server_counts.items()]
    environment_counter = Counter(host.environment or "unknown" for host in server_hosts)
    environment_counts = sorted(environment_counter.items())
    availability_counter = Counter(host.zabbix_agent_availability or "unknown" for host in server_hosts)
    availability_counts = sorted(availability_counter.items())
    problem_total = sum(host.problem_count or 0 for host in server_hosts)
    problem_average = round(problem_total / counts["servers"], 2) if counts["servers"] else 0
    last_sync_at = db.scalar(select(func.max(Host.zabbix_last_sync_at)))
    top_hosts = sorted(
        server_hosts,
        key=lambda host: (-(host.problem_count or 0), host.monitoring_status or "", host.hostname),
    )[:10]
    requested_db_type = normalized_db_type(db_type)
    hosts_stmt = select(Host).options(selectinload(Host.databases)).order_by(Host.hostname)
    hosts_stmt = apply_host_filters(hosts_stmt, None, environment, role, monitoring_status)
    hosts_list = db.scalars(hosts_stmt).all()
    if requested_db_type:
        hosts_list = [host for host in hosts_list if host_db_labels.get(host.id) == requested_db_type]
    type_base_stmt = select(Host).options(selectinload(Host.databases)).order_by(Host.hostname)
    type_base_stmt = apply_host_filters(type_base_stmt, None, environment, role, monitoring_status)
    type_base_hosts = db.scalars(type_base_stmt).all()

    db_type_view = DB_TYPE_VIEWS.get(current_view)
    display_hosts = hosts_list
    type_database_assets: list[Host] = []
    type_server_assets: list[Host] = []
    if db_type_view:
        type_hosts = [
            host for host in type_base_hosts if host_db_labels.get(host.id) == db_type_view["label"]
        ]
        type_database_assets = [
            host for host in type_hosts if host_asset_kinds.get(host.id) == "database"
        ]
        type_server_assets = [
            host for host in type_hosts if host_asset_kinds.get(host.id) == "server"
        ]
        if not type_database_assets:
            type_database_assets = type_hosts
        if not type_server_assets:
            type_server_assets = type_hosts
        display_hosts = type_database_assets if current_asset_view == "databases" else type_server_assets

    database_assets = [
        host
        for host in type_base_hosts
        if host_db_labels.get(host.id) in {"Oracle", "PostgreSQL", "SQLServer"}
        and host_asset_kinds.get(host.id) == "database"
    ]
    server_assets = [
        host
        for host in type_base_hosts
        if host_db_labels.get(host.id) in {"Oracle", "PostgreSQL", "SQLServer"}
        and host_asset_kinds.get(host.id) == "server"
    ]
    filtered_server_hosts = unique_hosts([host for host in hosts_list if is_os_class_host(host)])
    if current_view == "hosts":
        display_hosts = filtered_server_hosts

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
        {"key": "hosts", "label": "Servers", "icon": "bi-hdd-network"},
        {"key": "oracle", "label": "Oracle", "icon": "bi-database"},
        {"key": "postgresql", "label": "PostgreSQL", "icon": "bi-database-fill"},
        {"key": "sqlserver", "label": "SQLServer", "icon": "bi-server"},
    ]
    section_titles = {
        "overview": "SUMMARY OVERVIEW",
        "hosts": "SERVERS OVERVIEW",
        "databases": "DATABASE ASSETS INVENTORY",
        "clusters": "HA/DR CLUSTERS INVENTORY",
        **{key: config["title"] for key, config in DB_TYPE_VIEWS.items()},
    }
    section_subtitles = {
        "overview": (
            f"{counts['servers']} servers, Oracle {db_family_server_counts['Oracle']}, "
            f"PostgreSQL {db_family_server_counts['PostgreSQL']}, SQLServer {db_family_server_counts['SQLServer']}"
        ),
        "hosts": f"{len(filtered_server_hosts)} servers in current view",
        "databases": f"{len(database_assets)} DB assets in current view",
        "clusters": f"{len(clusters)} clusters in current view",
        **{
            key: f"{len(display_hosts) if key == current_view else 0} records in current view"
            for key in DB_TYPE_VIEWS
        },
    }
    if db_type_view:
        section_subtitles[current_view] = (
            f"{len(type_database_assets)} databases, {len(type_server_assets)} servers from Zabbix"
        )

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
            "current_asset_view": current_asset_view,
            "db_family_counts": db_family_counts,
            "db_family_server_counts": db_family_server_counts,
            "platform_counts": platform_counts,
            "host_db_labels": host_db_labels,
            "host_platform_labels": host_platform_labels,
            "host_asset_kinds": host_asset_kinds,
            "host_virtual_labels": host_virtual_labels,
            "host_os_labels": host_os_labels,
            "host_model_labels": host_model_labels,
            "host_core_labels": host_core_labels,
            "host_ram_labels": host_ram_labels,
            "server_db_type_options": ["PostgreSQL", "SQLServer", "Oracle"],
            "active_server_db_type": requested_db_type,
            "database_assets": database_assets,
            "server_assets": server_assets,
            "type_database_assets": type_database_assets,
            "type_server_assets": type_server_assets,
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
