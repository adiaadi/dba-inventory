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
    clusters = db.scalars(select(Cluster).order_by(Cluster.name)).all()
    recent_snapshots = db.scalars(
        select(DatabaseInstance)
        .options(selectinload(DatabaseInstance.host))
        .where(DatabaseInstance.last_snapshot.is_not(None))
        .order_by(desc(DatabaseInstance.last_snapshot))
        .limit(6)
    ).all()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "active_page": "dashboard",
            "counts": counts,
            "monitoring_counts": monitoring_counts,
            "db_type_counts": db_type_counts,
            "clusters": clusters,
            "recent_snapshots": recent_snapshots,
        },
    )
