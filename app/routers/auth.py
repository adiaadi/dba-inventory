from hmac import compare_digest
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import get_settings
from app.web import templates

router = APIRouter(tags=["auth"])
settings = get_settings()


def safe_next_url(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


async def parsed_form(request: Request) -> dict[str, list[str]]:
    body = (await request.body()).decode("utf-8")
    return parse_qs(body, keep_blank_values=True)


def first_value(form_data: dict[str, list[str]], key: str) -> str:
    return (form_data.get(key) or [""])[0]


def is_portal_request(request: Request) -> bool:
    return request.session.get("portal_user") == settings.portal_username


@router.get("/login", response_class=HTMLResponse)
def login(request: Request, error: str | None = None, next: str = "/"):
    next_url = safe_next_url(next)
    if is_portal_request(request):
        return RedirectResponse(next_url, status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "error": error,
            "next_url": next_url,
        },
    )


@router.post("/login")
async def login_post(request: Request):
    form_data = await parsed_form(request)
    username = first_value(form_data, "username").strip()
    password = first_value(form_data, "password")
    next_url = safe_next_url(first_value(form_data, "next"))

    if compare_digest(username, settings.portal_username) and compare_digest(password, settings.portal_password):
        request.session["portal_user"] = username
        return RedirectResponse(next_url, status_code=303)

    return RedirectResponse(f"/login?error=1&next={quote(next_url, safe='')}", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
