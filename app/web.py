from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.ui_texts import ui_text_map

settings = get_settings()
templates = Jinja2Templates(directory=settings.templates_dir)


def status_class(value: str | None) -> str:
    normalized = (value or "unknown").lower()
    if normalized in {"ok", "healthy", "online", "active", "sync", "available"}:
        return "success"
    if normalized in {"warning", "degraded", "lagging", "problem"}:
        return "warning"
    if normalized in {"critical", "down", "failed", "error", "unavailable"}:
        return "danger"
    if normalized in {"maintenance", "paused", "disabled"}:
        return "info"
    return "secondary"


def date_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    try:
        timezone = ZoneInfo(settings.app_timezone)
    except ZoneInfoNotFoundError:
        timezone = UTC
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(timezone)
    return value.strftime("%Y-%m-%d %H:%M")


def load_request_ui_texts() -> dict[str, str]:
    try:
        with SessionLocal() as db:
            return ui_text_map(db)
    except SQLAlchemyError:
        return {}


def ui_text(request, key: str, default: str) -> str:
    values = getattr(request.state, "ui_texts", {})
    return values.get(key, default)


def ui_text_value(request, key: str, default: str) -> str:
    return ui_text(request, key, default)


templates.env.filters["status_class"] = status_class
templates.env.filters["date_time"] = date_time
templates.env.globals["ui_text"] = ui_text
