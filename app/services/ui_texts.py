from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UiText


DEFAULT_UI_TEXTS = [
    {"key": "page.title", "category": "Header", "label": "Browser title", "default": "Database Inventory"},
    {"key": "brand.title", "category": "Header", "label": "Header title", "default": "DATABASE INVENTORY"},
    {"key": "external.zabbix", "category": "Header", "label": "Zabbix link", "default": "ZABBIX"},
    {"key": "external.powa", "category": "Header", "label": "PoWA link", "default": "PoWA"},
    {"key": "external.oem", "category": "Header", "label": "OEM link", "default": "OEM"},
    {"key": "nav.overview", "category": "Navigation", "label": "Overview nav item", "default": "Overview"},
    {"key": "nav.servers", "category": "Navigation", "label": "Servers nav item", "default": "Servers"},
    {"key": "nav.oracle", "category": "Navigation", "label": "Oracle nav item", "default": "Oracle"},
    {"key": "nav.postgresql", "category": "Navigation", "label": "PostgreSQL nav item", "default": "PostgreSQL"},
    {"key": "nav.sqlserver", "category": "Navigation", "label": "SQLServer nav item", "default": "SQLServer"},
    {"key": "nav.admin", "category": "Navigation", "label": "Admin nav item", "default": "Admin"},
    {"key": "nav.logout", "category": "Navigation", "label": "Logout button", "default": "Logout"},
    {"key": "sidebar.page_navigator", "category": "Sidebar", "label": "Page navigator caption", "default": "Page Navigator"},
    {"key": "sidebar.filters", "category": "Sidebar", "label": "Filters caption", "default": "Filters"},
    {"key": "filter.environment", "category": "Filters", "label": "Environment filter", "default": "Environment"},
    {"key": "filter.db_type", "category": "Filters", "label": "DB Type filter", "default": "DB Type"},
    {"key": "filter.all", "category": "Filters", "label": "All option", "default": "All"},
    {"key": "filter.apply", "category": "Filters", "label": "Apply button", "default": "Apply"},
    {"key": "filter.reset", "category": "Filters", "label": "Reset button", "default": "Reset"},
    {"key": "action.refresh_zabbix", "category": "Actions", "label": "Refresh Zabbix button", "default": "Refresh Zabbix"},
    {"key": "action.export_servers", "category": "Actions", "label": "Export servers button", "default": "Export Servers"},
    {"key": "action.export_dbs", "category": "Actions", "label": "Export DBs button", "default": "Export DBs"},
    {"key": "action.explore_servers", "category": "Actions", "label": "Explore servers button", "default": "Explore Servers"},
    {"key": "action.save", "category": "Actions", "label": "Save button", "default": "Save"},
    {"key": "section.overview.title", "category": "Sections", "label": "Overview page title", "default": "SUMMARY OVERVIEW"},
    {"key": "section.hosts.title", "category": "Sections", "label": "Servers page title", "default": "SERVERS OVERVIEW"},
    {"key": "section.databases.title", "category": "Sections", "label": "Database assets title", "default": "DATABASE ASSETS INVENTORY"},
    {"key": "section.clusters.title", "category": "Sections", "label": "Clusters title", "default": "HA/DR CLUSTERS INVENTORY"},
    {"key": "section.oracle.title", "category": "Sections", "label": "Oracle page title", "default": "ORACLE"},
    {"key": "section.postgresql.title", "category": "Sections", "label": "PostgreSQL page title", "default": "POSTGRESQL"},
    {"key": "section.sqlserver.title", "category": "Sections", "label": "SQL Server page title", "default": "SQL SERVER"},
    {"key": "panel.database_estate", "category": "Panels", "label": "Database estate panel", "default": "Database Estate"},
    {"key": "panel.database_estate_note", "category": "Panels", "label": "Database estate note", "default": "from Zabbix database assets"},
    {"key": "panel.datacenter_footprint", "category": "Panels", "label": "Datacenter footprint panel", "default": "Datacenter Footprint"},
    {"key": "panel.datacenter_note", "category": "Panels", "label": "Datacenter note", "default": "MAIN / DR sites"},
    {"key": "panel.infrastructure_mix", "category": "Panels", "label": "Infrastructure mix panel", "default": "Infrastructure Mix"},
    {"key": "panel.infrastructure_note", "category": "Panels", "label": "Infrastructure mix note", "default": "Virtual / Physical"},
    {"key": "panel.monitoring_health", "category": "Panels", "label": "Monitoring health panel", "default": "Monitoring Health"},
    {"key": "panel.database_size", "category": "Panels", "label": "Database size panel", "default": "Database Size"},
    {"key": "panel.database_size_note", "category": "Panels", "label": "Database size note", "default": "3D view - PostgreSQL / SQLServer primary only"},
    {"key": "panel.physical_support", "category": "Panels", "label": "Physical support panel", "default": "Physical Servers Support"},
    {"key": "panel.open_problem_queue", "category": "Panels", "label": "Open problem queue panel", "default": "Open Problem Queue"},
    {"key": "panel.server_summary", "category": "Panels", "label": "Server summary panel", "default": "Server Summary"},
    {"key": "panel.database_assets", "category": "Panels", "label": "Database assets panel", "default": "Database Assets"},
    {"key": "panel.cluster_health", "category": "Panels", "label": "Cluster health panel", "default": "Cluster Health"},
    {"key": "label.last_zabbix_sync", "category": "Labels", "label": "Last Zabbix sync label", "default": "Last Zabbix sync"},
    {"key": "label.records", "category": "Labels", "label": "Records label", "default": "records"},
    {"key": "label.records_from_zabbix", "category": "Labels", "label": "Records from Zabbix label", "default": "records from Zabbix"},
    {"key": "label.requires_attention", "category": "Labels", "label": "Requires attention label", "default": "requires attention"},
    {"key": "label.physical_servers", "category": "Labels", "label": "Physical servers label", "default": "physical servers"},
    {"key": "label.databases", "category": "Labels", "label": "Databases label", "default": "Databases"},
    {"key": "label.servers", "category": "Labels", "label": "Servers label", "default": "Servers"},
    {"key": "label.total", "category": "Labels", "label": "Total label", "default": "Total"},
    {"key": "label.virtual", "category": "Labels", "label": "Virtual label", "default": "Virtual"},
    {"key": "label.physical", "category": "Labels", "label": "Physical label", "default": "Physical"},
    {"key": "label.unknown", "category": "Labels", "label": "Unknown label", "default": "Unknown"},
    {"key": "label.oracle", "category": "Labels", "label": "Oracle label", "default": "Oracle"},
    {"key": "label.postgresql", "category": "Labels", "label": "PostgreSQL label", "default": "PostgreSQL"},
    {"key": "label.sqlserver", "category": "Labels", "label": "SQLServer label", "default": "SQLServer"},
    {"key": "label.oracle_databases", "category": "Labels", "label": "Oracle databases label", "default": "Oracle Databases"},
    {"key": "label.postgresql_databases", "category": "Labels", "label": "PostgreSQL databases label", "default": "PostgreSQL Databases"},
    {"key": "label.sqlserver_databases", "category": "Labels", "label": "SQLServer databases label", "default": "SQLServer Databases"},
    {"key": "label.db_assets", "category": "Labels", "label": "DB assets label", "default": "DB assets"},
    {"key": "label.db_type", "category": "Table", "label": "DB Type column", "default": "DB Type"},
    {"key": "label.server", "category": "Table", "label": "Server column", "default": "Server"},
    {"key": "label.instance_name", "category": "Table", "label": "Instance name column", "default": "Instance Name"},
    {"key": "label.ip", "category": "Table", "label": "IP column", "default": "IP"},
    {"key": "label.environment", "category": "Table", "label": "Environment column", "default": "Environment"},
    {"key": "label.server_model", "category": "Table", "label": "Server model column", "default": "Server model"},
    {"key": "label.server_vendor", "category": "Table", "label": "Server vendor column", "default": "Server vendor"},
    {"key": "label.core", "category": "Table", "label": "Core column", "default": "Core"},
    {"key": "label.ram", "category": "Table", "label": "RAM column", "default": "RAM"},
    {"key": "label.operating_system", "category": "Table", "label": "Operating system column", "default": "Operating system"},
    {"key": "label.monitoring", "category": "Table", "label": "Monitoring column", "default": "Monitoring"},
    {"key": "label.problems", "category": "Table", "label": "Problems column", "default": "Problems"},
    {"key": "label.model", "category": "Table", "label": "Model column", "default": "Model"},
    {"key": "label.vendor", "category": "Table", "label": "Vendor column", "default": "Vendor"},
    {"key": "label.datacenter", "category": "Table", "label": "Datacenter column", "default": "Datacenter"},
    {"key": "label.support_end", "category": "Table", "label": "Support end column", "default": "Support end"},
    {"key": "label.status", "category": "Table", "label": "Status column", "default": "Status"},
    {"key": "empty.no_physical_servers", "category": "Empty states", "label": "No physical servers", "default": "No physical servers found."},
    {"key": "empty.no_servers", "category": "Empty states", "label": "No servers", "default": "No servers found."},
    {"key": "empty.no_instances", "category": "Empty states", "label": "No instances", "default": "No instances found."},
    {"key": "empty.no_size_data", "category": "Empty states", "label": "No size data", "default": "No size data from Zabbix"},
    {"key": "admin.login_title", "category": "Admin", "label": "Login title", "default": "Admin Login"},
    {"key": "admin.texts_title", "category": "Admin", "label": "Texts page title", "default": "Editable Texts"},
    {"key": "admin.support_title", "category": "Admin", "label": "Support page title", "default": "Physical Servers Support"},
]


def ensure_ui_texts(db: Session) -> None:
    existing_keys = set(db.scalars(select(UiText.key)).all())
    changed = False
    for item in DEFAULT_UI_TEXTS:
        if item["key"] in existing_keys:
            continue
        db.add(
            UiText(
                key=item["key"],
                category=item["category"],
                label=item["label"],
                default_value=item["default"],
                value=item["default"],
            )
        )
        changed = True
    if changed:
        db.commit()


def ui_text_rows(db: Session) -> list[UiText]:
    ensure_ui_texts(db)
    return list(db.scalars(select(UiText).order_by(UiText.category, UiText.label)).all())


def ui_text_map(db: Session) -> dict[str, str]:
    return {
        row.key: row.value
        for row in db.scalars(select(UiText)).all()
    }
