from datetime import datetime

from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

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
    return value.strftime("%Y-%m-%d %H:%M")


templates.env.filters["status_class"] = status_class
templates.env.filters["date_time"] = date_time
