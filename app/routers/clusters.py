from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Cluster, ClusterMember, DatabaseInstance
from app.routers.common import active_filters, apply_cluster_filters, get_filter_options
from app.web import templates

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("", response_class=HTMLResponse)
def clusters(
    request: Request,
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = (
        select(Cluster)
        .options(
            selectinload(Cluster.members)
            .selectinload(ClusterMember.database_instance)
            .selectinload(DatabaseInstance.host)
        )
        .order_by(Cluster.cluster_type, Cluster.name)
    )
    stmt = apply_cluster_filters(stmt, db_type, environment, role, monitoring_status)
    cluster_list = db.scalars(stmt).all()

    return templates.TemplateResponse(
        "clusters.html",
        {
            "request": request,
            "active_page": "clusters",
            "clusters": cluster_list,
            "filters": active_filters(db_type, environment, role, monitoring_status),
            "filter_options": get_filter_options(db),
        },
    )
