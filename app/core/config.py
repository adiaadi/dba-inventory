from functools import lru_cache
from os import getenv

from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = True) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


class Settings:
    app_name: str = getenv("APP_NAME", "DBA Inventory")
    app_env: str = getenv("APP_ENV", "local")
    database_url: str = getenv(
        "DATABASE_URL",
        "postgresql+psycopg://dba_inventory:dba_inventory@localhost:5432/dba_inventory",
    )
    static_dir: str = getenv("STATIC_DIR", "app/static")
    templates_dir: str = getenv("TEMPLATES_DIR", "app/templates")
    zabbix_url: str | None = getenv("ZABBIX_URL")
    zabbix_api_token: str | None = getenv("ZABBIX_API_TOKEN")
    zabbix_verify_ssl: bool = env_bool("ZABBIX_VERIFY_SSL", True)
    zabbix_ca_file: str | None = getenv("ZABBIX_CA_FILE")


@lru_cache
def get_settings() -> Settings:
    return Settings()
