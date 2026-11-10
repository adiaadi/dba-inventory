from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from app.services.replication import get_snapshot
from app.web import templates

router = APIRouter(prefix="/replication", tags=["replication"])


@router.get("", response_class=HTMLResponse)
def replication(request: Request):
    return templates.TemplateResponse(request, "replication.html", {"request": request})


@router.get("/api")
def replication_data(history_hours: int = Query(default=1, ge=1, le=24)):
    if history_hours not in (1, 3, 6, 12, 24):
        raise HTTPException(status_code=422, detail='Choose 1, 3, 6, 12 or 24 hours')
    return JSONResponse(get_snapshot(history_hours), headers={"Cache-Control": "no-store"})
