from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.routers import admin, clusters, dashboard, databases, exports, hosts
from app.web import load_request_ui_texts

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")


@app.middleware("http")
async def add_ui_texts(request, call_next):
    if not request.url.path.startswith("/static"):
        request.state.ui_texts = load_request_ui_texts()
    return await call_next(request)


app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(hosts.router)
app.include_router(databases.router)
app.include_router(clusters.router)
app.include_router(exports.router)
