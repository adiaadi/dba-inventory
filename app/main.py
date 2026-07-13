from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.routers import clusters, dashboard, databases, exports, hosts

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

app.include_router(dashboard.router)
app.include_router(hosts.router)
app.include_router(databases.router)
app.include_router(clusters.router)
app.include_router(exports.router)
