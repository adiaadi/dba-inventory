"""Read-only replication monitoring using explicitly mapped Zabbix items."""
from __future__ import annotations

import logging
import json
import re
import math
import time
from pathlib import Path
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import get_settings
from app.services.zabbix import ZabbixApiError, ZabbixClient

log = logging.getLogger(__name__)

# label, unit, warning, critical, allowed healthy text values (None means numeric).
METRICS = {
    "oracle": {
        "archived_seq": ("Last archived sequence", "", None, None, None),
        "copied_seq": ("Last copied sequence", "", None, None, None),
        "applied_seq": ("Last applied sequence", "", None, None, None),
        "archive_gap": ("Archive gap", "logs", 1, 10, None),
        "pending_apply": ("Pending apply", "logs", 1, 10, None),
        "last_success_age": ("Last success age", "s", 600, 1800, None),
        "transfer_job": ("Cron transfer job", "", None, None, {"success"}),
        "apply_job": ("RMAN apply job", "", None, None, {"success"}),
    },
    "postgresql": {
        "wal_backlog": ("WAL backlog", "bytes", 104857600, 1073741824, None),
        "replay_lag": ("Replay lag", "s", 10, 60, None),
        "stream_state": ("Stream state", "", None, None, {"streaming"}),
        "sync_state": ("Replication mode", "", None, None, {"sync", "async", "quorum", "potential"}),
        "leader_lock": ("Patroni leader lock", "", None, None, {"held"}),
        "replica_state": ("Patroni replica state", "", None, None, {"running", "streaming"}),
        "patroni_nodes": ("Healthy Patroni nodes", "", None, None, None),
    },
    "sqlserver": {
        "backup_age": ("Backup age", "s", 900, 1800, None),
        "copy_age": ("Copy age", "s", 900, 1800, None),
        "restore_age": ("Restore age", "s", 1800, 5400, None),
        "pending_files": ("Pending files", "files", 1, 10, None),
        "backup_job": ("Backup job", "", None, None, {"success"}),
        "copy_job": ("Copy job", "", None, None, {"success"}),
        "restore_job": ("Restore job", "", None, None, {"success"}),
    },
}
TRENDS = {"oracle": "archive_gap", "postgresql": "replay_lag", "sqlserver": "restore_age"}
TITLES = {"oracle": "Oracle · Archive Log Replication", "postgresql": "PostgreSQL · Streaming Replication", "sqlserver": "SQL Server · Log Shipping"}


class ItemMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    itemid: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    key: str | None = Field(default=None, min_length=1)
    factor: float = Field(default=1, gt=0, allow_inf_nan=False)
    values: dict[str, str] = Field(default_factory=dict)
    warning: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    critical: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_source(self):
        if (self.itemid is None) == (self.key is None):
            raise ValueError("Specify exactly one of itemid or key")
        return self


class ReplicationPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    engine: Literal["oracle", "postgresql", "sqlserver"]
    primary: str = Field(min_length=1, max_length=160)
    standby: str = Field(min_length=1, max_length=160)
    zabbix_host: str | None = Field(default=None, min_length=1)
    environment: str = "production"
    schedule: str = ""
    stale_after_seconds: int = Field(default=180, ge=30, le=86400)
    expected_patroni_nodes: int = Field(default=2, ge=1)
    metrics: dict[str, ItemMapping]

    @model_validator(mode="after")
    def validate_metrics(self):
        for key, mapping in self.metrics.items():
            if mapping.key is not None and not self.zabbix_host:
                raise ValueError("zabbix_host is required for key mappings")
            if self.engine == 'oracle' and key in ('archive_file', 'transfer_stats'):
                if mapping.factor != 1 or mapping.values or mapping.warning is not None or mapping.critical is not None:
                    raise ValueError('archive_file does not support thresholds or value mapping')
                continue
            if key not in METRICS[self.engine]:
                raise ValueError(f"Unknown {self.engine} metric: {key}")
            _, _, warn, crit, healthy = METRICS[self.engine][key]
            warn = mapping.warning if mapping.warning is not None else warn
            crit = mapping.critical if mapping.critical is not None else crit
            if warn is not None and crit is not None and warn > crit:
                raise ValueError(f"{key}: warning must not exceed critical")
            if healthy is not None and mapping.factor != 1:
                raise ValueError(f"{key}: factor applies only to numeric metrics")
        return self


class ReplicationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairs: list[ReplicationPair] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({p.id for p in self.pairs}) != len(self.pairs):
            raise ValueError("Pair IDs must be unique")
        return self


def read_config(path: str) -> ReplicationConfig:
    if not path:
        return ReplicationConfig()
    return ReplicationConfig.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))


def metric_value(key, definition, mapping, item, now, stale_after):
    label, unit, warn, crit, healthy = definition
    result = {"key": key, "label": label, "unit": unit, "value": None, "status": "unknown", "reason": "Item not configured", "clock": None}
    if not mapping:
        return result
    result["reason"] = "Item missing, disabled or unsupported"
    if not item or str(item.get("status")) != "0" or str(item.get("state")) != "0":
        return result
    try:
        clock = int(item.get("lastclock", 0))
        if clock <= 0 or clock > now + 60:
            raise ValueError("Invalid timestamp")
        raw = str(item["lastvalue"]).strip()
        value = mapping.values.get(raw, raw).strip().lower() if healthy is not None else float(raw) * mapping.factor
        if healthy is None and (not math.isfinite(value) or value < 0):
            raise ValueError("Invalid number")
        if healthy is not None and not value:
            raise ValueError("Empty state")
    except (ValueError, TypeError, KeyError, OverflowError):
        result["reason"] = "Invalid value or timestamp"
        return result
    result.update(value=value, clock=clock, reason="", status="healthy")
    if now - clock > stale_after:
        result.update(status="stale", reason="Source measurement is stale")
    elif healthy is not None:
        if value in {"failed", "error", "stopped", "disconnected", "lost", "down"}:
            result.update(status="critical", reason="Unhealthy state")
        elif value not in healthy:
            result.update(status="unknown", reason="Unrecognized state; configure values mapping")
    else:
        warn = mapping.warning if mapping.warning is not None else warn
        crit = mapping.critical if mapping.critical is not None else crit
        if crit is not None and value >= crit:
            result.update(status="critical", reason="Critical threshold reached")
        elif warn is not None and value >= warn:
            result.update(status="warning", reason="Warning threshold reached")
    return result


def pair_status(metrics):
    statuses = {m["status"] for m in metrics}
    # Never hide a known failure behind a missing unrelated measurement.
    return next((s for s in ("critical", "stale", "unknown", "warning") if s in statuses), "healthy")


def archive_file_info(pair, items, now):
    mapping = pair.metrics.get('archive_file')
    item = items.get(mapping.itemid) if mapping else None
    if not item or str(item.get('status')) != '0' or str(item.get('state')) != '0':
        return None
    try:
        if not 0 <= now - int(item['lastclock']) <= pair.stale_after_seconds:
            return None
        data = json.loads(item['lastvalue'])
        if not isinstance(data, dict) or not re.fullmatch(r'(?:1_[0-9]+_[0-9]+\.dbf|[0-9]+_1_[0-9]+\.arc)', data.get('name', '')):
            return None
        if type(data.get('size_bytes')) is not int or data['size_bytes'] <= 0:
            return None
        return {'name': data['name'], 'size_bytes': data['size_bytes']}
    except (ValueError, TypeError, KeyError):
        return None


def transfer_stats_info(pair, items, now):
    mapping = pair.metrics.get('transfer_stats')
    item = items.get(mapping.itemid) if mapping else None
    if not item or str(item.get('status')) != '0' or str(item.get('state')) != '0':
        return None
    try:
        if not 0 <= now - int(item['lastclock']) <= pair.stale_after_seconds:
            return None
        data = json.loads(item['lastvalue'])
        for key in ('bytes_received', 'duration_seconds', 'attempts', 'completed_at'):
            if type(data[key]) not in (int, float) or not math.isfinite(data[key]) or data[key] < 0:
                return None
        if not 0 <= now - data['completed_at'] <= pair.stale_after_seconds:
            return None
        if type(data['attempts']) is not int or type(data['bytes_received']) is not int:
            return None
        if data['attempts'] and data['duration_seconds'] <= 0:
            return None
        return dict(bytes_received=data['bytes_received'], duration_seconds=data['duration_seconds'],
                    bytes_per_second=data['bytes_received']/data['duration_seconds'] if data['attempts'] else None,
                    attempts=data['attempts'], completed_at=data['completed_at'])
    except (ValueError, TypeError, KeyError):
        return None


def build_pair(pair, items, now):
    metrics = [metric_value(key, definition, pair.metrics.get(key), items.get(pair.metrics[key].itemid) if key in pair.metrics else None, now, pair.stale_after_seconds) for key, definition in METRICS[pair.engine].items()]
    for metric in metrics:
        if metric["key"] == "patroni_nodes" and metric["status"] == "healthy" and metric["value"] < pair.expected_patroni_nodes:
            metric.update(status="critical", reason="Fewer healthy Patroni nodes than expected")
    clocks = [m["clock"] for m in metrics if m["clock"] is not None]
    return {"id": pair.id, "name": pair.name, "engine": pair.engine, "title": TITLES[pair.engine], "primary": pair.primary, "standby": pair.standby, "environment": pair.environment, "schedule": pair.schedule, "stale_after_seconds": pair.stale_after_seconds, "status": pair_status(metrics), "metrics": metrics, "oldest_measurement": min(clocks) if clocks else None, "trend": [], "trend_key": TRENDS[pair.engine], "trend_error": None, "archive_file": archive_file_info(pair, items, now), "transfer_stats": transfer_stats_info(pair, items, now)}


_lock = Lock()
_cached = None
_cached_at = 0.0


def resolve_items(config, client):
    """Resolve exact host/key pairs on a copy, retaining IDs for history queries."""
    config = config.model_copy(deep=True)
    ids = sorted({m.itemid for p in config.pairs for m in p.metrics.values() if m.itemid})
    items = {str(i["itemid"]): i for i in client.get_replication_items(ids)} if ids else {}
    hosts = {}
    for pair in config.pairs:
        for mapping in pair.metrics.values():
            if mapping.key:
                hosts.setdefault(pair.zabbix_host, set()).add(mapping.key)
    resolved = {}
    for host, keys in hosts.items():
        for item in client.get_replication_items_by_keys(host, sorted(keys)):
            lookup = (host, item["key_"])
            if lookup in resolved:
                raise ZabbixApiError("Ambiguous replication host/key mapping")
            resolved[lookup] = str(item["itemid"])
            items[str(item["itemid"])] = item
    for pair in config.pairs:
        for mapping in pair.metrics.values():
            if mapping.key:
                mapping.itemid = resolved.get((pair.zabbix_host, mapping.key))
    return config, items


def get_snapshot(history_hours=1):
    """A bounded, per-worker cache shares polls across portal viewers."""
    global _cached, _cached_at
    if history_hours not in (1, 3, 6, 12, 24):
        raise ValueError('Unsupported history period')
    history_seconds = history_hours * 3600
    settings = get_settings()
    with _lock:
        if _cached is not None and _cached.get('history_seconds') == history_seconds and time.monotonic() - _cached_at < 30:
            return _cached
        now = int(time.time())
        snapshot = {"fetched_at": now, "poll_seconds": 30, "pairs": [], "error": None, "history_seconds": history_seconds}
        try:
            config = read_config(settings.replication_config_file)
        except (OSError, ValueError):
            log.exception("Invalid replication configuration")
            snapshot["error"] = "Replication configuration is invalid. Check server configuration and logs."
            config = ReplicationConfig()
        items = {}
        client = None
        if config.pairs:
            if not settings.zabbix_url or not settings.zabbix_api_token:
                snapshot["error"] = "Zabbix connection is not configured."
            else:
                try:
                    client = ZabbixClient(settings.zabbix_url, settings.zabbix_api_token, timeout=8, verify_ssl=settings.zabbix_verify_ssl, ca_file=settings.zabbix_ca_file)
                    config, items = resolve_items(config, client)
                except (ZabbixApiError, OSError, ValueError):
                    log.exception("Replication items fetch failed")
                    snapshot["error"] = "Cannot read replication metrics from Zabbix."
                    client = None
        snapshot["pairs"] = [build_pair(p, items, now) for p in config.pairs]
        # Batch numeric history by Zabbix value type, avoiding one request per pair.
        history = {}
        if client:
            try:
                for value_type in ("0", "3"):
                    ids = sorted({p.metrics[TRENDS[p.engine]].itemid for p in config.pairs if TRENDS[p.engine] in p.metrics and str(items.get(p.metrics[TRENDS[p.engine]].itemid, {}).get("value_type")) == value_type})
                    if ids:
                        rows = client.get_replication_history(ids, value_type, now - history_seconds, now)
                        for row in rows:
                            history.setdefault(str(row["itemid"]), []).append(row)
            except (ZabbixApiError, OSError, ValueError):
                log.exception("Replication history fetch failed")
                for result in snapshot["pairs"]:
                    result["trend_error"] = "History unavailable"
        for pair, result in zip(config.pairs, snapshot["pairs"]):
            mapping = pair.metrics.get(TRENDS[pair.engine])
            if mapping:
                for row in history.get(mapping.itemid, []):
                    try:
                        value = float(row["value"]) * mapping.factor
                        clock = int(row["clock"])
                        if math.isfinite(value) and value >= 0 and now - history_seconds <= clock <= now:
                            result["trend"].append({"clock": clock, "value": value})
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
                result["trend"].sort(key=lambda point: point["clock"])
        _cached, _cached_at = snapshot, time.monotonic()
        return snapshot
