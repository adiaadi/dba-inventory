from collections import Counter
from datetime import UTC, date, datetime
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.session import get_db
from app.models import Cluster, ClusterMember, DatabaseInstance, Host
from app.routers.common import (
    active_filters,
    apply_cluster_filters,
    apply_host_filters,
    get_filter_options,
)
from app.services.zabbix_items import (
    operating_system_item_label,
    parse_zabbix_item_values,
    server_model_item_label,
    server_vendor_item_label,
)
from app.services.zabbix_refresh import maybe_refresh_zabbix_cache
from app.web import templates, ui_text_value

router = APIRouter()
settings = get_settings()

DB_TYPE_VIEWS = {
    "oracle": {
        "label": "Oracle",
        "title": "ORACLE",
        "db_types": ["Oracle"],
        "logo": "/static/img/oracle.png",
        "database_group": "Oracle Database",
        "server_group": "Oracle Server",
    },
    "postgresql": {
        "label": "PostgreSQL",
        "title": "POSTGRESQL",
        "db_types": ["PostgreSQL"],
        "logo": "/static/img/postgresql.png",
        "database_group": "PostgreSQL Database",
        "server_group": "PostgreSQL Server",
    },
    "sqlserver": {
        "label": "SQLServer",
        "title": "SQL SERVER",
        "db_types": ["SQL Server", "SQLServer"],
        "logo": "/static/img/sqlserver.png",
        "database_group": "SQLServer Database",
        "server_group": "SQLServer",
    },
}

DB_FAMILIES = ("Oracle", "PostgreSQL", "SQLServer")

DATABASE_SIZE_TAG_NAMES = (
    "db_size",
    "database_size",
    "database size",
    "size",
    "used_size",
    "data_size",
)

DATABASE_SIZE_ITEM_MARKERS = (
    "database size",
    "db size",
    "db.size",
    "pgsql.db.size",
    "oracle.db",
    "mssql",
    "sqlserver",
)

DATABASE_SIZE_EXCLUDE_MARKERS = (
    "vm.memory",
    "system.cpu",
    "filesystem",
    "vfs.fs",
    "disk",
    "tablespace",
)

REPLICA_MARKERS = (
    "standby",
    "replica",
    "replication",
    "secondary",
    "slave",
    "mirror",
    "mirroring",
    "log shipping",
    "drdb",
    "dr-db",
    "readonly",
    "read only",
)

ZABBIX_DATABASE_GROUPS = {
    "Oracle": ("Oracle Database", "Oracle Databases"),
    "PostgreSQL": ("PostgreSQL Database", "PostgreSQL Databases"),
    "SQLServer": ("SQLServer Database", "SQLServer Databases", "SQL Server Database", "SQL Server Databases"),
}

ZABBIX_SERVER_GROUPS = {
    "Oracle": ("Oracle Server", "Oracle Servers"),
    "PostgreSQL": ("PostgreSQL Server", "PostgreSQL Servers"),
    "SQLServer": (
        "SQLServer",
        "SQL Server",
        "SQLServer Server",
        "SQLServer Servers",
        "SQL Server Server",
        "SQL Server Servers",
    ),
}

ZABBIX_SERVER_SUMMARY_GROUPS = tuple(
    group_name
    for group_names in ZABBIX_SERVER_GROUPS.values()
    for group_name in group_names
)


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


def imported_zabbix_items(host: Host) -> dict[str, str]:
    return parse_zabbix_item_values(host.notes)


def first_tag_value(host: Host, tag_names: tuple[str, ...]) -> str | None:
    tags = imported_zabbix_tags(host)
    for tag_name in tag_names:
        values = tags.get(tag_name)
        if values:
            return values[0]
    return None


def has_tag_value(host: Host, tag_name: str, expected_value: str) -> bool:
    tags = imported_zabbix_tags(host)
    normalized_expected = expected_value.strip().lower()
    return any(value.strip().lower() == normalized_expected for value in tags.get(tag_name, []))


def has_tag_name(host: Host, tag_name: str) -> bool:
    return bool(imported_zabbix_tags(host).get(tag_name))


def has_tag_db_family(host: Host, tag_name: str, family: str) -> bool:
    tags = imported_zabbix_tags(host)
    return any(normalized_db_type(value) == family for value in tags.get(tag_name, []))


def class_tag_values(host: Host) -> set[str]:
    return {value.strip().lower() for value in imported_zabbix_tags(host).get("class", [])}


def has_database_marker(host: Host) -> bool:
    class_values = class_tag_values(host)
    if class_values:
        return "database" in class_values
    return has_tag_name(host, "database")


def has_os_marker(host: Host) -> bool:
    class_values = class_tag_values(host)
    if class_values:
        return "os" in class_values
    return has_tag_name(host, "server")


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
    return has_os_marker(host)


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


def detected_server_platform_from_values(vendor: str | None, model: str | None, fallback_text: str = "") -> str:
    vendor_model_parts = [value for value in (vendor, model) if value and value != "-"]
    text = " ".join(vendor_model_parts).lower() or fallback_text
    virtual_markers = (
        "qemu",
        "kvm",
        "vmware",
        "virtualbox",
        "virtual machine",
        "hyper-v",
        "hyperv",
        "proxmox",
        "xen",
        "bochs",
        "virtual",
        "parallels",
        "openstack",
        "cloud",
        "rhev",
        "ovirt",
        "-vm",
        "_vm",
    )
    physical_markers = (
        "dell",
        "dell inc",
        "hpe",
        "hewlett packard",
        "hewlett-packard",
        " hp ",
        "lenovo",
        "ibm",
        "cisco",
        "supermicro",
        "super micro",
        "fujitsu",
        "oracle corporation",
        "huawei",
        "inspur",
        "bare metal",
        "baremetal",
    )
    if any(marker in text for marker in virtual_markers):
        return "Virtual"
    if any(marker in text for marker in physical_markers):
        return "Physical"
    return "Unknown"


def detected_server_platform(host: Host) -> str:
    return detected_server_platform_from_values(
        server_vendor_label(host),
        server_model_label(host),
        host_search_text(host),
    )


def virtual_status_label(platform: str | None) -> str:
    if platform == "Virtual":
        return "YES"
    if platform == "Physical":
        return "NO"
    return "-"


def normalized_virtual_filter(value: str | None) -> str | None:
    normalized = (value or "").strip().upper()
    if normalized in {"YES", "NO"}:
        return normalized
    return None


def is_virtual_server(host: Host) -> bool:
    explicit_value = first_tag_value(host, ("virtual", "is_virtual", "vm"))
    if explicit_value:
        return explicit_value.lower() in {"1", "true", "yes", "y", "virtual", "vm"}
    type_value = first_tag_value(host, ("type", "server_type", "platform"))
    if type_value and type_value.lower() in {"virtual", "vm", "vmware", "hyper-v", "hyperv", "kvm"}:
        return True
    return detected_server_platform(host) == "Virtual"


def operating_system_label(host: Host) -> str:
    item_values = imported_zabbix_items(host)
    inventory = imported_zabbix_inventory(host)
    fallback = host.os_name or inventory.get("os_full") or inventory.get("os") or inventory.get("os_short")
    return operating_system_item_label(item_values, fallback) or "-"


def operating_system_family_label(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if not normalized or normalized == "-":
        return "Unknown"
    if "ubuntu" in normalized:
        return "Ubuntu"
    if "oracle linux" in normalized or "oracle enterprise linux" in normalized or normalized.startswith("oel"):
        return "OEL"
    if "red hat" in normalized or "rhel" in normalized:
        return "RHEL"
    if "rocky" in normalized:
        return "Rocky Linux"
    if "alma" in normalized:
        return "AlmaLinux"
    if "centos" in normalized:
        return "CentOS"
    if "debian" in normalized:
        return "Debian"
    if "suse" in normalized or "sles" in normalized:
        return "SUSE"
    if "windows" in normalized or "microsoft" in normalized:
        return "Windows"
    if "linux" in normalized:
        return "Linux"
    return value.strip()


def server_model_label(host: Host) -> str:
    item_values = imported_zabbix_items(host)
    item_label = server_model_item_label(item_values)
    if item_label:
        return item_label

    tag_value = first_tag_value(host, ("server_model", "model", "hardware_model"))
    if tag_value:
        return tag_value

    inventory = imported_zabbix_inventory(host)
    model = inventory.get("model")
    fallback = model or inventory.get("hardware_full") or inventory.get("hardware") or inventory.get("chassis")
    return server_model_item_label(item_values, fallback) or "-"


def server_vendor_label(host: Host) -> str:
    item_values = imported_zabbix_items(host)
    item_label = server_vendor_item_label(item_values)
    if item_label:
        return item_label

    tag_value = first_tag_value(host, ("server_vendor", "vendor", "hardware_vendor"))
    if tag_value:
        return tag_value
    inventory = imported_zabbix_inventory(host)
    return server_vendor_item_label(item_values, inventory.get("vendor")) or "-"


def server_core_label(host: Host) -> str:
    item_values = imported_zabbix_items(host)
    return (
        item_values.get("system.cpu.num")
        or first_tag_value(host, ("core", "cores", "cpu_core", "cpu_cores", "vcpu", "vcpus", "cpu"))
        or "-"
    )


def server_ram_label(host: Host) -> str:
    item_values = imported_zabbix_items(host)
    item_ram = format_memory_label(item_values.get("vm.memory.size[total]"))
    return item_ram or first_tag_value(host, ("ram", "memory", "mem", "ram_gb", "memory_gb")) or "-"


def format_memory_label(value: str | None) -> str | None:
    if not value:
        return None
    try:
        bytes_value = float(value)
    except ValueError:
        return value
    if bytes_value <= 0:
        return value
    gib = bytes_value / 1024**3
    if gib >= 1:
        return f"{gib:.1f} GB".replace(".0 GB", " GB")
    mib = bytes_value / 1024**2
    if mib >= 1:
        return f"{mib:.0f} MB"
    return f"{bytes_value:.0f} B"


def parse_core_count(value: str | None) -> int:
    if not value or value == "-":
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


def parse_memory_gb(value: str | None) -> float:
    if not value or value == "-":
        return 0
    text = value.strip().lower().replace(",", ".")
    number = None
    for part in text.split():
        try:
            number = float(part)
            break
        except ValueError:
            continue
    if number is None:
        return 0
    if "tb" in text:
        return number * 1024
    if "mb" in text:
        return number / 1024
    if "kb" in text:
        return number / 1024**2
    return number


def format_capacity_gb(value: float) -> str:
    if value >= 1024:
        return f"{value / 1024:.1f} TB".replace(".0 TB", " TB")
    return f"{value:.1f} GB".replace(".0 GB", " GB")


def parse_size_bytes(value: str | None) -> float | None:
    if not value or value == "-":
        return None
    text = value.strip().lower().replace(",", ".")
    number = None
    for part in text.split():
        try:
            number = float(part)
            break
        except ValueError:
            continue
    if number is None:
        try:
            number = float(text)
        except ValueError:
            return None
    if "tb" in text or "tib" in text:
        return number * 1024**4
    if "gb" in text or "gib" in text:
        return number * 1024**3
    if "mb" in text or "mib" in text:
        return number * 1024**2
    if "kb" in text or "kib" in text:
        return number * 1024
    return number


def format_size_bytes(value: float | None) -> str:
    if value is None or value <= 0:
        return "-"
    tib = value / 1024**4
    if tib >= 1:
        return f"{tib:.1f} TB".replace(".0 TB", " TB")
    gib = value / 1024**3
    if gib >= 1:
        return f"{gib:.1f} GB".replace(".0 GB", " GB")
    mib = value / 1024**2
    if mib >= 1:
        return f"{mib:.0f} MB"
    return f"{value:.0f} B"


def database_size_value(host: Host) -> tuple[float | None, str]:
    for tag_name in DATABASE_SIZE_TAG_NAMES:
        tag_value = first_tag_value(host, (tag_name,))
        if tag_value:
            parsed = parse_size_bytes(tag_value)
            return parsed, format_size_bytes(parsed) if parsed else tag_value

    candidates: list[tuple[float, str]] = []
    for key, value in imported_zabbix_items(host).items():
        key_text = key.lower()
        if any(marker in key_text for marker in DATABASE_SIZE_EXCLUDE_MARKERS):
            continue
        if "size" not in key_text:
            continue
        if not any(marker in key_text for marker in DATABASE_SIZE_ITEM_MARKERS):
            continue
        parsed = parse_size_bytes(value)
        if parsed:
            candidates.append((parsed, format_size_bytes(parsed)))
    if not candidates:
        return None, "-"
    return max(candidates, key=lambda item: item[0])


def database_size_label(host: Host) -> str:
    return database_size_value(host)[1]


def database_role_text(host: Host) -> str:
    tags = imported_zabbix_tags(host)
    values = [
        value
        for tag_name in ("role", "db_role", "replication_role", "cluster_role", "status")
        for value in tags.get(tag_name, [])
    ]
    values.extend([host.role or "", host.zabbix_host_name or "", host.hostname or ""])
    return " ".join(values).lower()


def is_primary_database_asset(host: Host) -> bool:
    role_text = database_role_text(host)
    return not any(marker in role_text for marker in REPLICA_MARKERS)


def datacenter_label(host: Host) -> str:
    tag_value = first_tag_value(host, ("datacenter", "data_center", "dc"))
    if tag_value:
        normalized = tag_value.strip().upper()
        if normalized in {"MAIN", "DR"}:
            return normalized
        return tag_value.strip()
    return "Unknown"


def support_status_label(support_end_date: date | None) -> str:
    if support_end_date is None:
        return "not set"
    today = datetime.now(UTC).date()
    if support_end_date < today:
        return "expired"
    if (support_end_date - today).days <= 180:
        return "expires soon"
    return "active"


def imported_zabbix_group_names(host: Host) -> list[str]:
    notes = host.notes or ""
    marker = "Imported from Zabbix groups:"
    if marker not in notes:
        return []
    group_text = notes.split(marker, 1)[1].split(";", 1)[0]
    return [group_name.strip() for group_name in group_text.split(",") if group_name.strip()]


def normalized_zabbix_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def host_has_zabbix_group(host: Host, group_names: tuple[str, ...]) -> bool:
    imported_groups = {
        normalized_zabbix_name(group_name)
        for group_name in imported_zabbix_group_names(host)
    }
    expected_groups = {normalized_zabbix_name(group_name) for group_name in group_names}
    return bool(imported_groups & expected_groups)


def is_family_database_asset(host: Host, family: str) -> bool:
    if host_has_zabbix_group(host, ZABBIX_DATABASE_GROUPS[family]):
        return True
    return has_database_marker(host) and has_tag_db_family(host, "database", family)


def has_server_group_marker(host: Host) -> bool:
    return any(is_server_group_name(group_name) for group_name in imported_zabbix_group_names(host))


def is_family_server_asset(host: Host, family: str) -> bool:
    if has_tag_db_family(host, "server", family):
        return True
    return host_has_zabbix_group(host, ZABBIX_SERVER_GROUPS[family])


def is_zabbix_database_asset(host: Host) -> bool:
    return any(is_family_database_asset(host, family) for family in DB_FAMILIES)


def is_zabbix_server_asset(host: Host) -> bool:
    return any(is_family_server_asset(host, family) for family in DB_FAMILIES) or (
        (has_os_marker(host) or has_server_group_marker(host))
        and host_has_zabbix_group(host, ZABBIX_SERVER_SUMMARY_GROUPS)
    )


def detected_db_type_by_zabbix_rules(host: Host) -> str | None:
    for family in DB_FAMILIES:
        if is_family_database_asset(host, family) or is_family_server_asset(host, family):
            return family
    return None


def is_database_group_name(group_name: str) -> bool:
    normalized = group_name.strip().lower()
    return normalized.endswith(" database") or normalized.endswith(" databases")


def is_server_group_name(group_name: str) -> bool:
    normalized = group_name.strip().lower()
    return (
        normalized in {"sqlserver", "sql server"}
        or normalized.endswith(" server")
        or normalized.endswith(" servers")
    )


def detected_zabbix_asset_kind(host: Host) -> str:
    if is_zabbix_database_asset(host):
        return "database"
    if is_zabbix_server_asset(host):
        return "server"

    tags = imported_zabbix_tags(host)
    if has_database_marker(host):
        return "database"
    if has_os_marker(host):
        return "server"
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


@router.post("/hosts/{host_id}/support-end-date")
async def update_host_support_end_date(
    host_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    if request.session.get("admin_user") != settings.admin_username:
        return RedirectResponse("/admin/login", status_code=303)

    body = (await request.body()).decode("utf-8")
    form_data = parse_qs(body)
    raw_value = (form_data.get("support_end_date") or [""])[0].strip()

    host = db.get(Host, host_id)
    if host is not None:
        if raw_value:
            try:
                host.support_end_date = date.fromisoformat(raw_value)
            except ValueError:
                host.support_end_date = None
        else:
            host.support_end_date = None
        db.commit()

    redirect_url = request.headers.get("referer") or "/?view=overview"
    return RedirectResponse(redirect_url, status_code=303)


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    view: str = "overview",
    asset_view: str = "databases",
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
    virtual: str | None = None,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    allowed_views = {"overview", "hosts", "databases", "clusters", *DB_TYPE_VIEWS.keys()}
    current_view = view if view in allowed_views else "overview"
    current_asset_view = asset_view if asset_view in {"databases", "servers"} else "databases"
    filters = active_filters(db_type, environment, role, monitoring_status)
    active_virtual_filter = normalized_virtual_filter(virtual)
    zabbix_refresh_error = maybe_refresh_zabbix_cache(db, force=refresh)
    counts = {
        "hosts": db.scalar(select(func.count(Host.id))) or 0,
        "databases": db.scalar(select(func.count(DatabaseInstance.id))) or 0,
        "clusters": db.scalar(select(func.count(Cluster.id))) or 0,
    }
    all_hosts = db.scalars(select(Host).options(selectinload(Host.databases)).order_by(Host.hostname)).all()
    host_db_labels = {
        host.id: detected_db_type_by_zabbix_rules(host) or detected_db_type(host)
        for host in all_hosts
    }
    host_asset_kinds = {host.id: detected_zabbix_asset_kind(host) for host in all_hosts}
    host_os_labels = {host.id: operating_system_label(host) for host in all_hosts}
    host_model_labels = {host.id: server_model_label(host) for host in all_hosts}
    host_vendor_labels = {host.id: server_vendor_label(host) for host in all_hosts}
    host_platform_labels = {
        host.id: detected_server_platform_from_values(
            host_vendor_labels.get(host.id),
            host_model_labels.get(host.id),
            host_search_text(host),
        )
        for host in all_hosts
    }
    host_virtual_labels = {
        host.id: virtual_status_label(host_platform_labels.get(host.id))
        for host in all_hosts
    }
    host_core_labels = {host.id: server_core_label(host) for host in all_hosts}
    host_ram_labels = {host.id: server_ram_label(host) for host in all_hosts}
    server_hosts = unique_hosts([host for host in all_hosts if is_zabbix_server_asset(host)])
    db_family_counts = {
        family: len(unique_hosts([host for host in all_hosts if is_family_database_asset(host, family)]))
        for family in DB_FAMILIES
    }
    db_family_server_counts = {
        family: len(unique_hosts([host for host in all_hosts if is_family_server_asset(host, family)]))
        for family in DB_FAMILIES
    }
    platform_counts = {
        "Virtual": sum(1 for host in server_hosts if host_platform_labels.get(host.id) == "Virtual"),
        "Physical": sum(1 for host in server_hosts if host_platform_labels.get(host.id) == "Physical"),
        "Unknown": sum(1 for host in server_hosts if host_platform_labels.get(host.id) == "Unknown"),
    }
    counts["databases"] = sum(db_family_counts.values())
    counts["servers"] = len(server_hosts)
    zabbix_inventory_warning = None
    if counts["hosts"] == 0:
        zabbix_inventory_warning = "No cached Zabbix hosts yet. Click Refresh Zabbix to load live data."
    elif counts["servers"] == 0 and counts["databases"] == 0:
        zabbix_inventory_warning = (
            f"{counts['hosts']} cached hosts found, but none matched inventory tags "
            "class/database/server."
        )
    monitoring_counter = Counter(host.monitoring_status or "unknown" for host in server_hosts)
    monitoring_counts = sorted(monitoring_counter.items())
    monitoring_summary = [
        {
            "label": status or "unknown",
            "count": count,
            "percent": round((count / counts["servers"]) * 100, 1) if counts["servers"] else 0,
        }
        for status, count in monitoring_counts
    ]
    visible_platform_counts = {
        label: platform_counts[label]
        for label in ("Virtual", "Physical")
    }
    platform_summary = [
        {
            "label": label,
            "count": count,
            "percent": round((count / counts["servers"]) * 100, 1) if counts["servers"] else 0,
        }
        for label, count in visible_platform_counts.items()
    ]
    os_family_counter = Counter(
        operating_system_family_label(host_os_labels.get(host.id))
        for host in server_hosts
    )
    os_family_counts = sorted(
        os_family_counter.items(),
        key=lambda item: (-item[1], item[0]),
    )
    db_type_counts = [(label, count) for label, count in db_family_server_counts.items()]
    environment_counter = Counter((host.environment or "UNKNOWN").upper() for host in server_hosts)
    environment_counts = sorted(environment_counter.items())
    environment_labels = sorted(environment_counter.keys())
    db_family_palette = {
        "Oracle": "#e30613",
        "PostgreSQL": "#111827",
        "SQLServer": "#64748b",
    }
    environment_matrix_datasets = [
        {
            "label": family,
            "data": [
                len(
                    unique_hosts(
                        [
                            host
                            for host in server_hosts
                            if (host.environment or "UNKNOWN").upper() == environment_label
                            and host_db_labels.get(host.id) == family
                        ]
                    )
                )
                for environment_label in environment_labels
            ],
            "backgroundColor": db_family_palette[family],
            "borderColor": db_family_palette[family],
        }
        for family in DB_FAMILIES
    ]
    capacity_by_db = []
    for family in DB_FAMILIES:
        family_hosts = unique_hosts(
            [host for host in server_hosts if host_db_labels.get(host.id) == family]
        )
        total_cores = sum(parse_core_count(host_core_labels.get(host.id)) for host in family_hosts)
        total_ram_gb = sum(parse_memory_gb(host_ram_labels.get(host.id)) for host in family_hosts)
        capacity_by_db.append(
            {
                "label": family,
                "servers": len(family_hosts),
                "cores": total_cores,
                "ram_label": format_capacity_gb(total_ram_gb) if total_ram_gb else "-",
            }
        )
    database_size_sections = []
    for family in DB_FAMILIES:
        family_database_hosts = unique_hosts(
            [host for host in all_hosts if is_family_database_asset(host, family)]
        )
        if family in {"PostgreSQL", "SQLServer"}:
            family_database_hosts = [
                host for host in family_database_hosts if is_primary_database_asset(host)
            ]
        rows = []
        for host in family_database_hosts:
            size_bytes, size_label = database_size_value(host)
            rows.append(
                {
                    "name": host.zabbix_host_name or host.hostname,
                    "server": host.hostname,
                    "ip": host.ip_address or "-",
                    "size": size_label,
                    "size_bytes": size_bytes or 0,
                    "monitoring": host.monitoring_status,
                    "problem_count": host.problem_count or 0,
                }
            )
        rows.sort(key=lambda row: row["size_bytes"], reverse=True)
        max_size = max((row["size_bytes"] for row in rows), default=0)
        total_size = sum(row["size_bytes"] for row in rows)
        for row in rows:
            row["percent"] = round((row["size_bytes"] / max_size) * 100, 1) if max_size else 0
        database_size_sections.append(
            {
                "label": "SQL Server" if family == "SQLServer" else family,
                "primary_only": family in {"PostgreSQL", "SQLServer"},
                "rows": rows,
                "total_size": format_size_bytes(total_size) if total_size else "-",
                "has_size_data": max_size > 0,
            }
        )
    datacenter_counts = {
        "MAIN": sum(1 for host in server_hosts if datacenter_label(host) == "MAIN"),
        "DR": sum(1 for host in server_hosts if datacenter_label(host) == "DR"),
    }
    physical_server_rows = [
        {
            "host": host,
            "model": host_model_labels.get(host.id) or "-",
            "vendor": host_vendor_labels.get(host.id) or "-",
            "datacenter": datacenter_label(host),
            "support_status": support_status_label(host.support_end_date),
        }
        for host in server_hosts
        if host_platform_labels.get(host.id) == "Physical"
    ]
    physical_server_rows.sort(key=lambda row: (row["vendor"], row["model"], row["host"].hostname))
    availability_counter = Counter(host.zabbix_agent_availability or "unknown" for host in server_hosts)
    availability_counts = sorted(availability_counter.items())
    problem_total = sum(host.problem_count or 0 for host in server_hosts)
    problem_average = round(problem_total / counts["servers"], 2) if counts["servers"] else 0
    last_sync_at = db.scalar(select(func.max(Host.zabbix_last_sync_at)))
    top_hosts = sorted(
        [
            host
            for host in server_hosts
            if (host.problem_count or 0) > 0 or (host.monitoring_status or "").lower() != "ok"
        ],
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
        type_database_assets = unique_hosts(
            [host for host in type_base_hosts if is_family_database_asset(host, db_type_view["label"])]
        )
        type_server_assets = unique_hosts(
            [host for host in type_base_hosts if is_family_server_asset(host, db_type_view["label"])]
        )
        if active_virtual_filter and current_asset_view == "servers":
            type_server_assets = [
                host
                for host in type_server_assets
                if host_virtual_labels.get(host.id) == active_virtual_filter
            ]
        display_hosts = type_database_assets if current_asset_view == "databases" else type_server_assets

    database_assets = unique_hosts([
        host
        for host in type_base_hosts
        if is_zabbix_database_asset(host)
    ])
    server_assets = unique_hosts([
        host
        for host in type_base_hosts
        if is_zabbix_server_asset(host)
    ])
    filtered_server_hosts = unique_hosts([host for host in hosts_list if is_zabbix_server_asset(host)])
    if active_virtual_filter:
        filtered_server_hosts = [
            host
            for host in filtered_server_hosts
            if host_virtual_labels.get(host.id) == active_virtual_filter
        ]
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
        "inventoryLabels": list(DB_FAMILIES),
        "inventoryServerValues": [db_family_server_counts[family] for family in DB_FAMILIES],
        "inventoryDatabaseValues": [db_family_counts[family] for family in DB_FAMILIES],
        "environmentLabels": [environment or "UNKNOWN" for environment, _ in environment_counts],
        "environmentValues": [count for _, count in environment_counts],
        "environmentMatrixLabels": environment_labels,
        "environmentMatrixDatasets": environment_matrix_datasets,
        "availabilityLabels": [availability or "unknown" for availability, _ in availability_counts],
        "availabilityValues": [count for _, count in availability_counts],
        "platformLabels": list(visible_platform_counts.keys()),
        "platformValues": list(visible_platform_counts.values()),
        "osLabels": [label for label, _ in os_family_counts],
        "osValues": [count for _, count in os_family_counts],
    }
    section_tabs = [
        {"key": "overview", "label": ui_text_value(request, "nav.overview", "Overview"), "icon": "bi-grid-1x2"},
        {"key": "hosts", "label": ui_text_value(request, "nav.servers", "Servers"), "icon": "bi-hdd-network"},
        {"key": "oracle", "label": ui_text_value(request, "nav.oracle", "Oracle"), "icon": "bi-database"},
        {"key": "postgresql", "label": ui_text_value(request, "nav.postgresql", "PostgreSQL"), "icon": "bi-database-fill"},
        {"key": "sqlserver", "label": ui_text_value(request, "nav.sqlserver", "SQLServer"), "icon": "bi-server"},
    ]
    section_titles = {
        "overview": ui_text_value(request, "section.overview.title", "SUMMARY OVERVIEW"),
        "hosts": ui_text_value(request, "section.hosts.title", "SERVERS OVERVIEW"),
        "databases": ui_text_value(request, "section.databases.title", "DATABASE ASSETS INVENTORY"),
        "clusters": ui_text_value(request, "section.clusters.title", "HA/DR CLUSTERS INVENTORY"),
        "oracle": ui_text_value(request, "section.oracle.title", DB_TYPE_VIEWS["oracle"]["title"]),
        "postgresql": ui_text_value(request, "section.postgresql.title", DB_TYPE_VIEWS["postgresql"]["title"]),
        "sqlserver": ui_text_value(request, "section.sqlserver.title", DB_TYPE_VIEWS["sqlserver"]["title"]),
    }
    servers_label = ui_text_value(request, "label.servers", "Servers")
    records_label = ui_text_value(request, "label.records", "records")
    section_subtitles = {
        "overview": (
            f"{counts['servers']} {servers_label}, Oracle DB {db_family_counts['Oracle']}, "
            f"PostgreSQL DB {db_family_counts['PostgreSQL']}, SQLServer DB {db_family_counts['SQLServer']}"
        ),
        "hosts": f"{len(filtered_server_hosts)} {servers_label} in current view",
        "databases": f"{len(database_assets)} DB assets in current view",
        "clusters": f"{len(clusters)} clusters in current view",
        **{
            key: f"{len(display_hosts) if key == current_view else 0} {records_label} in current view"
            for key in DB_TYPE_VIEWS
        },
    }
    if db_type_view:
        section_subtitles[current_view] = (
            f"{len(type_database_assets)} databases, {len(type_server_assets)} {servers_label} from Zabbix"
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
            "os_family_counts": os_family_counts,
            "host_db_labels": host_db_labels,
            "host_platform_labels": host_platform_labels,
            "host_asset_kinds": host_asset_kinds,
            "host_virtual_labels": host_virtual_labels,
            "host_os_labels": host_os_labels,
            "host_model_labels": host_model_labels,
            "host_vendor_labels": host_vendor_labels,
            "host_core_labels": host_core_labels,
            "host_ram_labels": host_ram_labels,
            "server_db_type_options": ["PostgreSQL", "SQLServer", "Oracle"],
            "active_server_db_type": requested_db_type,
            "active_virtual_filter": active_virtual_filter,
            "database_assets": database_assets,
            "server_assets": server_assets,
            "type_database_assets": type_database_assets,
            "type_server_assets": type_server_assets,
            "monitoring_counts": monitoring_counts,
            "monitoring_summary": monitoring_summary,
            "db_type_counts": db_type_counts,
            "environment_counts": environment_counts,
            "platform_summary": platform_summary,
            "capacity_by_db": capacity_by_db,
            "database_size_sections": database_size_sections,
            "datacenter_counts": datacenter_counts,
            "physical_server_rows": physical_server_rows,
            "availability_counts": availability_counts,
            "problem_total": problem_total,
            "problem_average": problem_average,
            "last_sync_at": last_sync_at,
            "zabbix_refresh_error": zabbix_refresh_error,
            "zabbix_inventory_warning": zabbix_inventory_warning,
            "top_hosts": top_hosts,
            "chart_data": chart_data,
            "clusters": clusters,
            "recent_snapshots": recent_snapshots,
            "filters": filters,
            "filter_options": get_filter_options(db),
        },
    )
