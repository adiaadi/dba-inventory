from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Host
from app.services.zabbix import ZabbixApiError, ZabbixClient


def sync_zabbix() -> int:
    settings = get_settings()
    if not settings.zabbix_url or not settings.zabbix_api_token:
        raise RuntimeError("ZABBIX_URL and ZABBIX_API_TOKEN must be set")

    client = ZabbixClient(
        settings.zabbix_url,
        settings.zabbix_api_token,
        verify_ssl=settings.zabbix_verify_ssl,
        ca_file=settings.zabbix_ca_file,
    )
    db = SessionLocal()
    updated = 0
    try:
        hosts = db.scalars(select(Host).order_by(Host.hostname)).all()
        for host in hosts:
            lookup_names = [host.hostname, host.zabbix_host_name, host.fqdn]
            state = None
            for lookup_name in dict.fromkeys(name for name in lookup_names if name):
                state = client.get_host_state(lookup_name)
                if state is not None:
                    break
            now = datetime.now(UTC)
            if state is None:
                host.monitoring_status = "not_found"
                host.problem_count = 0
                host.zabbix_agent_availability = "unknown"
                host.zabbix_last_sync_at = now
                print(f"{host.hostname}: not found in Zabbix")
            else:
                host.zabbix_hostid = state.hostid
                host.zabbix_host_name = state.host_name
                host.zabbix_url = state.url
                host.zabbix_agent_availability = state.agent_availability
                host.problem_count = state.problem_count
                host.monitoring_status = state.monitoring_status
                host.zabbix_last_sync_at = now
                print(
                    f"{host.hostname}: hostid={state.hostid} "
                    f"availability={state.agent_availability} "
                    f"problems={state.problem_count} status={state.monitoring_status}"
                )
            updated += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return updated


def main() -> None:
    try:
        updated = sync_zabbix()
    except ZabbixApiError as exc:
        raise SystemExit(f"Zabbix sync failed: {exc}") from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Zabbix sync complete. Hosts processed: {updated}")


if __name__ == "__main__":
    main()
