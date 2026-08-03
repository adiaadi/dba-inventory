from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp

from app.core.config import Settings


class PortalAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self.public_paths = {"/login", "/favicon.ico"}
        self.public_prefixes = ("/static",)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self.public_paths or path.startswith(self.public_prefixes):
            return await call_next(request)

        if request.session.get("portal_user") == self.settings.portal_username:
            return await call_next(request)

        next_url = path
        if request.url.query:
            next_url = f"{next_url}?{request.url.query}"
        return RedirectResponse(f"/login?next={quote(next_url, safe='')}", status_code=303)
