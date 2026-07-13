from functools import lru_cache
from os import getenv

from dotenv import load_dotenv

load_dotenv()


class Settings:
    app_name: str = getenv("APP_NAME", "DBA Inventory")
    app_env: str = getenv("APP_ENV", "local")
    database_url: str = getenv(
        "DATABASE_URL",
        "postgresql+psycopg://dba_inventory:dba_inventory@localhost:5432/dba_inventory",
    )
    static_dir: str = getenv("STATIC_DIR", "app/static")
    templates_dir: str = getenv("TEMPLATES_DIR", "app/templates")


@lru_cache
def get_settings() -> Settings:
    return Settings()
