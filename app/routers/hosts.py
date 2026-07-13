from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Host
from app.routers.common import active_filters, apply_host_filters, get_filter_options
from app.web import templates

router = APIRouter(prefix="/hosts", tags=["hosts"])


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
def host_detail(host_id: int, request: Request, db: Session = Depends(get_db)):
    host = db.scalar(
        select(Host)
        .options(selectinload(Host.databases))
        .where(Host.id == host_id)
    )
    if host is None:
        raise HTTPException(status_code=404, detail="Host not found")

    problem_count = host.problem_count or 0
    db_label = host.db_type or ", ".join(sorted({database.db_type for database in host.databases})) or "-"

    zabbix_base = ""
    if host.zabbix_url and "zabbix.php" in host.zabbix_url:
        zabbix_base = host.zabbix_url.split("zabbix.php", 1)[0]

    def zabbix_url(action: str, **params) -> str:
        if not zabbix_base or not host.zabbix_hostid:
            return "#"
        query = urlencode({"action": action, **params})
        return f"{zabbix_base}zabbix.php?{query}"

    zabbix_tabs = [
        ("Performance Summary", zabbix_url("host.dashboard.view", hostid=host.zabbix_hostid)),
        ("Performance", zabbix_url("charts.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_set": "1"})),
        ("Metrics", zabbix_url("latest.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_set": "1"})),
        ("Alerts", zabbix_url("problem.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_set": "1"})),
        ("Object Execution", zabbix_url("latest.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_name": "execution", "filter_set": "1"})),
        ("Slow Queries", zabbix_url("latest.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_name": "slow", "filter_set": "1"})),
        ("Waits", zabbix_url("latest.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_name": "wait", "filter_set": "1"})),
        ("Running Queries", zabbix_url("latest.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_name": "running", "filter_set": "1"})),
        ("Memory", zabbix_url("latest.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_name": "memory", "filter_set": "1"})),
        ("Top Queries", zabbix_url("latest.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_name": "query", "filter_set": "1"})),
        ("Forced Plans", zabbix_url("latest.view", **{"filter_hostids[0]": host.zabbix_hostid, "filter_name": "plan", "filter_set": "1"})),
    ]
    metric_rows = [
        {
            "object": "Zabbix",
            "counter": "Problems",
            "instance": host.zabbix_host_name or host.hostname,
            "max_value": problem_count,
            "min_value": 0,
            "avg_value": round(problem_count / 2, 2) if problem_count else 0,
            "total": problem_count,
            "sample_count": 1,
            "current_value": problem_count,
            "status": "problem" if problem_count else "ok",
        },
        {
            "object": "Agent",
            "counter": "Availability",
            "instance": host.zabbix_hostid or "-",
            "max_value": host.zabbix_agent_availability,
            "min_value": "-",
            "avg_value": "-",
            "total": "-",
            "sample_count": 1,
            "current_value": host.zabbix_agent_availability,
            "status": host.zabbix_agent_availability,
        },
        {
            "object": "Inventory",
            "counter": "DB type",
            "instance": host.environment,
            "max_value": db_label,
            "min_value": "-",
            "avg_value": "-",
            "total": len(host.databases) or (1 if host.db_type else 0),
            "sample_count": len(host.databases),
            "current_value": db_label,
            "status": host.monitoring_status,
        },
        {
            "object": "Ownership",
            "counter": "Role",
            "instance": host.owner_team or "-",
            "max_value": host.role,
            "min_value": "-",
            "avg_value": "-",
            "total": "-",
            "sample_count": 1,
            "current_value": host.role,
            "status": host.monitoring_status,
        },
    ]

    return templates.TemplateResponse(
        request,
        "host_detail.html",
        {
            "request": request,
            "active_page": "hosts",
            "host": host,
            "db_label": db_label,
            "metric_rows": metric_rows,
            "zabbix_tabs": zabbix_tabs,
        },
    )
