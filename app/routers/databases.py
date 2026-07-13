from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import DatabaseInstance
from app.routers.common import active_filters, apply_database_filters, get_filter_options
from app.web import templates

router = APIRouter(prefix="/databases", tags=["databases"])


@router.get("", response_class=HTMLResponse)
def databases(
    request: Request,
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = (
        select(DatabaseInstance)
        .options(selectinload(DatabaseInstance.host))
        .order_by(DatabaseInstance.db_type, DatabaseInstance.name)
    )
    stmt = apply_database_filters(stmt, db_type, environment, role, monitoring_status)
    database_list = db.scalars(stmt).all()

    return templates.TemplateResponse(
        "databases.html",
        {
            "request": request,
            "active_page": "databases",
            "databases": database_list,
            "filters": active_filters(db_type, environment, role, monitoring_status),
            "filter_options": get_filter_options(db),
        },
    )
