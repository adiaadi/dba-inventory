from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Cluster, DatabaseInstance, Host
from app.web import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    counts = {
        "hosts": db.scalar(select(func.count(Host.id))) or 0,
        "databases": db.scalar(select(func.count(DatabaseInstance.id))) or 0,
        "clusters": db.scalar(select(func.count(Cluster.id))) or 0,
    }
    host_db_assets = db.scalar(select(func.count(Host.id)).where(Host.db_type.is_not(None), Host.db_type != "")) or 0
    if host_db_assets:
        counts["databases"] = host_db_assets
    monitoring_counts = db.execute(
        select(Host.monitoring_status, func.count(Host.id))
        .group_by(Host.monitoring_status)
        .order_by(Host.monitoring_status)
    ).all()
    db_type_counts = db.execute(
        select(Host.db_type, func.count(Host.id))
        .where(Host.db_type.is_not(None), Host.db_type != "")
        .group_by(Host.db_type)
        .order_by(Host.db_type)
    ).all()
    if not db_type_counts:
        db_type_counts = db.execute(
            select(DatabaseInstance.db_type, func.count(DatabaseInstance.id))
            .group_by(DatabaseInstance.db_type)
            .order_by(DatabaseInstance.db_type)
        ).all()
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
    clusters = db.scalars(select(Cluster).order_by(Cluster.name)).all()
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
    }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "active_page": "dashboard",
            "counts": counts,
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
        },
    )
