from fastapi import APIRouter, Depends, Request
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
