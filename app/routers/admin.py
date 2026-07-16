from collections import defaultdict
from datetime import date
from hmac import compare_digest
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import Host, UiText
from app.routers.dashboard import (
    datacenter_label,
    detected_server_platform,
    is_zabbix_server_asset,
    server_model_label,
    server_vendor_label,
    support_status_label,
    unique_hosts,
)
from app.services.ui_texts import ui_text_rows
from app.web import templates

router = APIRouter(prefix="/admin", tags=["admin"])
settings = get_settings()


def is_admin_request(request: Request) -> bool:
    return request.session.get("admin_user") == settings.admin_username


def admin_redirect() -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=303)


async def parsed_form(request: Request) -> dict[str, list[str]]:
    body = (await request.body()).decode("utf-8")
    return parse_qs(body, keep_blank_values=True)


def first_value(form_data: dict[str, list[str]], key: str) -> str:
    return (form_data.get(key) or [""])[0]


def physical_support_rows(db: Session) -> list[dict]:
    hosts = db.scalars(select(Host).order_by(Host.hostname)).all()
    server_hosts = unique_hosts([host for host in hosts if is_zabbix_server_asset(host)])
    rows = [
        {
            "host": host,
            "model": server_model_label(host),
            "vendor": server_vendor_label(host),
            "datacenter": datacenter_label(host),
            "support_status": support_status_label(host.support_end_date),
        }
        for host in server_hosts
        if detected_server_platform(host) == "Physical"
    ]
    return sorted(rows, key=lambda row: (row["vendor"], row["model"], row["host"].hostname))


@router.get("/", response_class=HTMLResponse)
def admin_home(request: Request):
    if not is_admin_request(request):
        return admin_redirect()
    return RedirectResponse("/admin/texts", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def admin_login(request: Request, error: str | None = None):
    if is_admin_request(request):
        return RedirectResponse("/admin/texts", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin_login.html",
        {
            "request": request,
            "error": error,
        },
    )


@router.post("/login")
async def admin_login_post(request: Request):
    form_data = await parsed_form(request)
    username = first_value(form_data, "username").strip()
    password = first_value(form_data, "password")
    if compare_digest(username, settings.admin_username) and compare_digest(password, settings.admin_password):
        request.session["admin_user"] = username
        return RedirectResponse("/admin/texts", status_code=303)
    return RedirectResponse("/admin/login?error=1", status_code=303)


@router.post("/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@router.get("/texts", response_class=HTMLResponse)
def admin_texts(request: Request, saved: bool = False, db: Session = Depends(get_db)):
    if not is_admin_request(request):
        return admin_redirect()
    rows_by_category: dict[str, list[UiText]] = defaultdict(list)
    for row in ui_text_rows(db):
        rows_by_category[row.category].append(row)
    return templates.TemplateResponse(
        request,
        "admin_texts.html",
        {
            "request": request,
            "active_admin_page": "texts",
            "rows_by_category": dict(rows_by_category),
            "saved": saved,
        },
    )


@router.post("/texts")
async def admin_texts_save(request: Request, db: Session = Depends(get_db)):
    if not is_admin_request(request):
        return admin_redirect()
    form_data = await parsed_form(request)
    rows = ui_text_rows(db)
    for row in rows:
        form_key = f"text_{row.key}"
        if form_key in form_data:
            row.value = first_value(form_data, form_key).strip()
    db.commit()
    return RedirectResponse("/admin/texts?saved=1", status_code=303)


@router.get("/support", response_class=HTMLResponse)
def admin_support(request: Request, saved: bool = False, db: Session = Depends(get_db)):
    if not is_admin_request(request):
        return admin_redirect()
    return templates.TemplateResponse(
        request,
        "admin_support.html",
        {
            "request": request,
            "active_admin_page": "support",
            "rows": physical_support_rows(db),
            "saved": saved,
        },
    )


@router.post("/support")
async def admin_support_save(request: Request, db: Session = Depends(get_db)):
    if not is_admin_request(request):
        return admin_redirect()
    form_data = await parsed_form(request)
    for host_id_text in form_data.get("host_ids", []):
        try:
            host_id = int(host_id_text)
        except ValueError:
            continue
        host = db.get(Host, host_id)
        if host is None:
            continue
        raw_value = first_value(form_data, f"support_end_date_{host_id}").strip()
        if raw_value:
            try:
                host.support_end_date = date.fromisoformat(raw_value)
            except ValueError:
                continue
        else:
            host.support_end_date = None
    db.commit()
    return RedirectResponse("/admin/support?saved=1", status_code=303)
