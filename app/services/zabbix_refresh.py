from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Host
from app.services.zabbix import ZabbixApiError
from app.services.zabbix_inventory import refresh_zabbix_inventory

_refresh_lock = Lock()
_last_attempt_at: datetime | None = None
_last_error: str | None = None


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_stale(last_sync_at: datetime | None, now: datetime, ttl_seconds: int) -> bool:
    last_sync_at = _aware_utc(last_sync_at)
    if last_sync_at is None:
        return True
    return now - last_sync_at >= timedelta(seconds=ttl_seconds)


def maybe_refresh_zabbix_cache(db: Session, force: bool = False) -> str | None:
    settings = get_settings()
    if (
        not settings.zabbix_url
        or not settings.zabbix_api_token
        or settings.zabbix_auto_refresh_seconds <= 0
    ):
        return None

    now = datetime.now(UTC)
    last_sync_at = db.scalar(select(func.max(Host.zabbix_last_sync_at)))
    if not force and not _is_stale(last_sync_at, now, settings.zabbix_auto_refresh_seconds):
        return None

    global _last_attempt_at, _last_error
    retry_floor = min(settings.zabbix_auto_refresh_seconds, 60)
    if not force and _last_attempt_at and now - _last_attempt_at < timedelta(seconds=retry_floor):
        return _last_error

    if not _refresh_lock.acquire(blocking=False):
        return None

    try:
        _last_attempt_at = now
        created, updated, deleted = refresh_zabbix_inventory(verbose=False)
        db.expire_all()
        if created + updated + deleted == 0:
            _last_error = "Zabbix refresh returned 0 hosts for configured groups."
        else:
            _last_error = None
    except (RuntimeError, ZabbixApiError) as exc:
        _last_error = str(exc)
    finally:
        _refresh_lock.release()

    return _last_error
