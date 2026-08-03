from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.session import get_db
from app.models import Host
from app.routers.common import active_filters, apply_host_filters, get_filter_options
from app.services.zabbix import ZabbixApiError, ZabbixClient
from app.web import templates

router = APIRouter(prefix="/hosts", tags=["hosts"])

HOST_TABS = [
    ("performance-summary", "Performance Summary"),
    ("system", "System"),
    ("cpu", "CPU"),
    ("memory", "Memory"),
    ("network", "Network"),
    ("storage", "Storage"),
]

SUMMARY_COMPONENTS = ("cpu", "memory", "network")
COMPONENT_LABELS = {
    "system": "System",
    "cpu": "CPU",
    "memory": "Memory",
    "network": "Network",
    "storage": "Storage",
}
CHART_COLORS = ("#e30613", "#111827", "#64748b", "#2563eb", "#16a34a", "#f59e0b")
SYSTEM_INFO_ITEMS = (
    ("system.boottime", "System boot time"),
    ("system.uname", "System description"),
    ("system.localtime", "System local time"),
    ("system.hostname", "System name"),
    ("system.uptime", "System uptime"),
    ("agent.ping", "Zabbix agent ping"),
)


def metric_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def compact_metric_value(value: float | str | None, units: str | None = None) -> str:
    if value in (None, ""):
        return "-"
    parsed = metric_float(value)
    if parsed is None:
        return str(value)
    if abs(parsed) >= 100:
        label = f"{parsed:,.0f}"
    elif abs(parsed) >= 10:
        label = f"{parsed:,.1f}".rstrip("0").rstrip(".")
    else:
        label = f"{parsed:,.2f}".rstrip("0").rstrip(".")
    return f"{label} {units}".strip() if units else label


def metric_time_label(clock: int, timezone_name: str) -> str:
    try:
        tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tzinfo = timezone.utc
    return datetime.fromtimestamp(clock, tzinfo).strftime("%H:%M")


def datetime_label_from_epoch(value: Any, timezone_name: str) -> str:
    timestamp = metric_float(value)
    if timestamp is None:
        return str(value) if value not in (None, "") else "-"
    try:
        tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tzinfo = timezone.utc
    return datetime.fromtimestamp(int(timestamp), tzinfo).strftime("%Y-%m-%d %I:%M:%S %p")


def uptime_label(value: Any) -> str:
    seconds = metric_float(value)
    if seconds is None:
        return str(value) if value not in (None, "") else "-"
    total_seconds = int(seconds)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds_left = divmod(remainder, 60)
    if days:
        return f"{days} days, {hours:02d}:{minutes:02d}:{seconds_left:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds_left:02d}"


def system_info_value_label(key: str, value: Any, timezone_name: str) -> str:
    if value in (None, ""):
        return "-"
    if key in {"system.boottime", "system.localtime"}:
        return datetime_label_from_epoch(value, timezone_name)
    if key == "system.uptime":
        return uptime_label(value)
    if key == "agent.ping":
        return "Up (1)" if str(value) == "1" else f"Down ({value})"
    return str(value)


def item_display_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("key_") or item.get("itemid") or "Metric")


def metric_points(history: list[dict[str, Any]]) -> list[tuple[int, float]]:
    points: list[tuple[int, float]] = []
    for row in history:
        clock = row.get("clock")
        value = metric_float(row.get("value"))
        if clock is None or value is None:
            continue
        points.append((int(clock), value))
    return points


def make_metric_row(
    component: str,
    counter: str,
    instance: str,
    points: list[tuple[int, float]],
    current_value: Any,
    units: str | None,
) -> dict[str, Any]:
    values = [value for _, value in points]
    current = values[-1] if values else current_value
    return {
        "object": COMPONENT_LABELS.get(component, component.title()),
        "counter": counter,
        "instance": instance,
        "max_value": compact_metric_value(max(values), units) if values else "-",
        "min_value": compact_metric_value(min(values), units) if values else "-",
        "avg_value": compact_metric_value(sum(values) / len(values), units) if values else "-",
        "total": compact_metric_value(sum(values), units) if values else "-",
        "sample_count": len(values),
        "current_value": compact_metric_value(current, units),
        "status": "ok",
    }


def make_chart(
    chart_id: str,
    title: str,
    datasets: list[dict[str, Any]],
    timezone_name: str,
) -> dict[str, Any] | None:
    clocks = sorted({clock for dataset in datasets for clock, _ in dataset["points"]})
    if not clocks:
        return None
    labels = [metric_time_label(clock, timezone_name) for clock in clocks]
    chart_datasets = []
    for index, dataset in enumerate(datasets):
        values_by_clock = {clock: value for clock, value in dataset["points"]}
        chart_datasets.append(
            {
                "label": dataset["label"],
                "data": [values_by_clock.get(clock) for clock in clocks],
                "borderColor": CHART_COLORS[index % len(CHART_COLORS)],
                "backgroundColor": "rgba(227, 6, 19, 0.12)" if index == 0 else "rgba(17, 24, 39, 0.08)",
                "fill": len(datasets) == 1,
                "tension": 0.22,
            }
        )
    return {
        "id": chart_id,
        "title": title,
        "labels": labels,
        "datasets": chart_datasets,
    }


def average_component_points(client: ZabbixClient, items: list[dict[str, Any]]) -> list[tuple[int, float]]:
    buckets: dict[int, list[float]] = defaultdict(list)
    for item in items[:8]:
        history = client.get_recent_item_history(
            str(item["itemid"]),
            str(item["value_type"]),
            seconds=3600,
            limit=180,
        )
        for clock, value in metric_points(history):
            buckets[clock - (clock % 60)].append(value)
    return [
        (clock, sum(values) / len(values))
        for clock, values in sorted(buckets.items())
        if values
    ]


def load_zabbix_metric_view(
    host: Host,
    active_tab: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    if not host.zabbix_hostid:
        return [], [], "This host has no linked Zabbix hostid."

    settings = get_settings()
    if not settings.zabbix_url or not settings.zabbix_api_token:
        return [], [], "ZABBIX_URL and ZABBIX_API_TOKEN must be set."

    try:
        client = ZabbixClient(
            settings.zabbix_url,
            settings.zabbix_api_token,
            verify_ssl=settings.zabbix_verify_ssl,
            ca_file=settings.zabbix_ca_file,
        )
        timezone_name = settings.app_timezone
        if active_tab == "performance-summary":
            datasets = []
            rows = []
            for component in SUMMARY_COMPONENTS:
                items = client.get_numeric_items_by_tag(host.zabbix_hostid, "component", component)
                points = average_component_points(client, items)
                if points:
                    label = COMPONENT_LABELS[component]
                    datasets.append({"label": label, "points": points})
                    rows.append(
                        make_metric_row(
                            component,
                            f"{label} summary",
                            host.zabbix_host_name or host.hostname,
                            points,
                            points[-1][1],
                            None,
                        )
                    )
            chart = make_chart("serverMetricChart0", "Performance Summary", datasets, timezone_name)
            return ([chart] if chart else []), rows, None

        component = active_tab
        items = client.get_numeric_items_by_tag(host.zabbix_hostid, "component", component)
        charts = []
        rows = []
        for item in items[:8]:
            history = client.get_recent_item_history(
                str(item["itemid"]),
                str(item["value_type"]),
                seconds=3600,
                limit=180,
            )
            points = metric_points(history)
            label = item_display_name(item)
            units = item.get("units") or None
            chart = make_chart(
                f"serverMetricChart{len(charts)}",
                label,
                [{"label": label, "points": points}],
                timezone_name,
            )
            if chart:
                charts.append(chart)
            rows.append(
                make_metric_row(
                    component,
                    label,
                    str(item.get("key_") or "-"),
                    points,
                    item.get("lastvalue"),
                    units,
                )
            )
        return charts, rows, None
    except (ZabbixApiError, ValueError) as exc:
        return [], [], f"Cannot load Zabbix metrics: {exc}"


def load_zabbix_system_info(host: Host) -> list[dict[str, str]]:
    settings = get_settings()
    values: dict[str, Any] = {}
    if host.zabbix_hostid and settings.zabbix_url and settings.zabbix_api_token:
        try:
            client = ZabbixClient(
                settings.zabbix_url,
                settings.zabbix_api_token,
                verify_ssl=settings.zabbix_verify_ssl,
                ca_file=settings.zabbix_ca_file,
            )
            values = client.get_latest_item_values(
                host.zabbix_hostid,
                tuple(key for key, _ in SYSTEM_INFO_ITEMS),
            )
        except (ZabbixApiError, ValueError):
            values = {}

    return [
        {
            "label": label,
            "value": system_info_value_label(key, values.get(key), settings.app_timezone),
        }
        for key, label in SYSTEM_INFO_ITEMS
    ]


@router.get("", response_class=HTMLResponse)
def hosts(
    request: Request,
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Host).options(selectinload(Host.databases)).order_by(Host.hostname)
    stmt = apply_host_filters(stmt, db_type, environment, role, monitoring_status)
    hosts_list = db.scalars(stmt).all()

    return templates.TemplateResponse(
        request,
        "hosts.html",
        {
            "request": request,
            "active_page": "hosts",
            "hosts": hosts_list,
            "filters": active_filters(db_type, environment, role, monitoring_status),
            "filter_options": get_filter_options(db),
        },
    )


@router.get("/{host_id}", response_class=HTMLResponse)
def host_detail(
    host_id: int,
    request: Request,
    tab: str = "performance-summary",
    db: Session = Depends(get_db),
):
    host = db.scalar(
        select(Host)
        .options(selectinload(Host.databases))
        .where(Host.id == host_id)
    )
    if host is None:
        raise HTTPException(status_code=404, detail="Host not found")

    db_label = host.db_type or ", ".join(sorted({database.db_type for database in host.databases})) or "-"

    host_tabs = HOST_TABS
    active_tab = tab if tab in {slug for slug, _ in host_tabs} else "performance-summary"
    metric_charts, metric_rows, zabbix_metrics_error = load_zabbix_metric_view(host, active_tab)
    system_info_rows = load_zabbix_system_info(host)

    return templates.TemplateResponse(
        request,
        "host_detail.html",
        {
            "request": request,
            "active_page": "hosts",
            "host": host,
            "db_label": db_label,
            "metric_charts": metric_charts,
            "metric_rows": metric_rows,
            "system_info_rows": system_info_rows,
            "host_tabs": host_tabs,
            "active_tab": active_tab,
            "zabbix_metrics_error": zabbix_metrics_error,
        },
    )
