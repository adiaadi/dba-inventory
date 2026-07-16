from __future__ import annotations

import sys

from app.services.zabbix import ZabbixApiError
from app.services.zabbix_inventory import refresh_zabbix_inventory


def sync_zabbix(group_names: list[str] | None = None) -> tuple[int, int, int]:
    return refresh_zabbix_inventory(group_names=group_names, verbose=True)


def main() -> None:
    group_names = sys.argv[1:] or None
    try:
        created, updated, deleted = sync_zabbix(group_names)
    except ZabbixApiError as exc:
        raise SystemExit(f"Zabbix refresh failed: {exc}") from exc
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Zabbix refresh complete. Created: {created}. Updated: {updated}. Deleted: {deleted}.")


if __name__ == "__main__":
    main()
