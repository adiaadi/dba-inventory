from __future__ import annotations

import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Host
from app.services.zabbix import ZabbixApiError, ZabbixClient

DEFAULT_GROUPS = [
    "Oracle Database",
    "Oracle Server",
    "PostgreSQL Database",
    "PostgreSQL Server",
    "SQLServer Database",
]


def db_type_from_groups(group_names: list[str]) -> str | None:
    joined = " ".join(group_names).lower()
    if "postgres" in joined:
        return "PostgreSQL"
    if "oracle" in joined:
        return "Oracle"
    if "sqlserver" in joined or "sql server" in joined:
        return "SQL Server"
    return None


def role_from_groups(group_names: list[str]) -> str:
    joined = " ".join(group_names).lower()
    if "database" in joined and "server" not in joined:
        return "database"
    if "server" in joined:
        return "database server"
    return "database"


def environment_from_name(name: str) -> str:
    normalized = name.lower()
    if any(marker in normalized for marker in ("-prod", "_prod", "prod-", "prod_", "production")):
        return "prod"
    if any(marker in normalized for marker in ("-test", "_test", "test-", "test_", "tst")):
        return "test"
    if any(marker in normalized for marker in ("-dev", "_dev", "dev-", "dev_")):
        return "dev"
    if any(marker in normalized for marker in ("-dr", "_dr", "drdb")):
        return "dr"
    return "unknown"


def owner_team_from_db_type(db_type: str | None) -> str:
    if db_type:
        return "DBA"
    return "Unknown"


def normalize_group_names(raw_groups: list[dict]) -> list[str]:
    return sorted({group.get("name") for group in raw_groups if group.get("name")})


def normalize_inventory(raw_inventory) -> dict:
    if isinstance(raw_inventory, dict):
        return {key: value for key, value in raw_inventory.items() if value}
    return {}


def upsert_host(db, zabbix_host: dict, client: ZabbixClient) -> tuple[Host, bool]:
    hostid = str(zabbix_host["hostid"])
    inventory_hostname = zabbix_host.get("host") or zabbix_host.get("name") or f"zabbix-{hostid}"
    display_name = zabbix_host.get("name") or inventory_hostname
    group_names = normalize_group_names(zabbix_host.get("groups") or [])
    inventory = normalize_inventory(zabbix_host.get("inventory"))
    db_type = db_type_from_groups(group_names)
    state = client.host_state_from_host(zabbix_host)

    host = db.scalar(select(Host).where(Host.zabbix_hostid == hostid))
    created = False
    if host is None:
        host = db.scalar(select(Host).where(Host.hostname == inventory_hostname))
    if host is None:
        created = True
        host = Host(
            hostname=inventory_hostname,
            environment=environment_from_name(inventory_hostname),
            role=role_from_groups(group_names),
            owner_team=owner_team_from_db_type(db_type),
            monitoring_status="unknown",
        )
        db.add(host)

    host.hostname = inventory_hostname
    host.fqdn = zabbix_host.get("host")
    host.ip_address = client.primary_interface_address(zabbix_host)
    host.environment = environment_from_name(f"{inventory_hostname} {display_name}")
    host.role = role_from_groups(group_names)
    host.db_type = db_type
    host.os_name = inventory.get("os_full") or inventory.get("os") or host.os_name
    host.location = inventory.get("location") or host.location
    host.owner_team = owner_team_from_db_type(db_type)
    inventory_text = ", ".join(f"{key}: {value}" for key, value in sorted(inventory.items()))
    notes = [f"Imported from Zabbix groups: {', '.join(group_names)}"]
    if inventory_text:
        notes.append(f"Zabbix inventory: {inventory_text}")
    host.notes = "; ".join(notes)
    host.zabbix_hostid = hostid
    host.zabbix_host_name = display_name
    host.zabbix_url = state.url
    host.zabbix_agent_availability = state.agent_availability
    host.problem_count = state.problem_count
    host.monitoring_status = state.monitoring_status
    host.zabbix_last_sync_at = datetime.now(UTC)
    return host, created


def import_zabbix_hosts(group_names: list[str] | None = None) -> tuple[int, int]:
    settings = get_settings()
    if not settings.zabbix_url or not settings.zabbix_api_token:
        raise RuntimeError("ZABBIX_URL and ZABBIX_API_TOKEN must be set")

    requested_groups = group_names or DEFAULT_GROUPS
    client = ZabbixClient(
        settings.zabbix_url,
        settings.zabbix_api_token,
        verify_ssl=settings.zabbix_verify_ssl,
        ca_file=settings.zabbix_ca_file,
    )
    zabbix_groups = client.get_host_groups_by_names(requested_groups)
    found_group_names = {group["name"] for group in zabbix_groups}
    missing_group_names = sorted(set(requested_groups) - found_group_names)
    if missing_group_names:
        print(f"Zabbix groups not found: {', '.join(missing_group_names)}")

    groupids = [str(group["groupid"]) for group in zabbix_groups]
    zabbix_hosts = client.get_hosts_by_groupids(groupids)
    if not zabbix_hosts:
        print("No Zabbix hosts found for selected groups.")
        return 0, 0

    db = SessionLocal()
    created = 0
    updated = 0
    seen_hostids: set[str] = set()
    try:
        for zabbix_host in zabbix_hosts:
            hostid = str(zabbix_host["hostid"])
            if hostid in seen_hostids:
                continue
            seen_hostids.add(hostid)
            host, was_created = upsert_host(db, zabbix_host, client)
            if was_created:
                created += 1
                action = "created"
            else:
                updated += 1
                action = "updated"
            print(
                f"{action}: {host.hostname} hostid={host.zabbix_hostid} "
                f"status={host.monitoring_status} problems={host.problem_count}"
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return created, updated


def main() -> None:
    group_names = sys.argv[1:] or None
    try:
        created, updated = import_zabbix_hosts(group_names)
    except ZabbixApiError as exc:
        raise SystemExit(f"Zabbix import failed: {exc}") from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Zabbix import complete. Created: {created}. Updated: {updated}.")


if __name__ == "__main__":
    main()
