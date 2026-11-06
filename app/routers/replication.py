from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.services.replication import get_snapshot
from app.web import templates

router = APIRouter(prefix="/replication", tags=["replication"])


@router.get("", response_class=HTMLResponse)
def replication(request: Request):
    return templates.TemplateResponse(request, "replication.html", {"request": request})


@router.get("/api")
def replication_data():
    return JSONResponse(get_snapshot(), headers={"Cache-Control": "no-store"})
