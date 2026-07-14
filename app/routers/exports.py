from io import BytesIO
from typing import Iterable

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import DatabaseInstance, Host
from app.routers.common import apply_database_filters, apply_host_filters
from app.services.zabbix_refresh import maybe_refresh_zabbix_cache

router = APIRouter(prefix="/exports", tags=["exports"])


def apply_sheet_style(ws, headers: Iterable[str]) -> None:
    header_fill = PatternFill("solid", fgColor="E9EEF5")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for index, header in enumerate(headers, start=1):
        ws.column_dimensions[ws.cell(row=1, column=index).column_letter].width = max(14, len(header) + 2)


def workbook_response(workbook: Workbook, filename: str) -> StreamingResponse:
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/hosts.xlsx")
def export_hosts(
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
    db: Session = Depends(get_db),
):
    maybe_refresh_zabbix_cache(db)
    stmt = select(Host).options(selectinload(Host.databases)).order_by(Host.hostname)
    stmt = apply_host_filters(stmt, db_type, environment, role, monitoring_status)
    hosts = db.scalars(stmt).all()

    headers = [
        "hostname",
        "fqdn",
        "ip_address",
        "environment",
        "db_type",
        "os_name",
        "location",
        "owner_team",
        "database_instance_types",
        "zabbix_hostid",
        "zabbix_host_name",
        "zabbix_url",
        "zabbix_agent_availability",
        "problem_count",
        "zabbix_last_sync_at",
        "monitoring_status",
    ]
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Servers"
    ws.append(headers)
    for host in hosts:
        ws.append(
            [
                host.hostname,
                host.fqdn,
                host.ip_address,
                host.environment,
                host.db_type,
                host.os_name,
                host.location,
                host.owner_team,
                ", ".join(sorted({database.db_type for database in host.databases})),
                host.zabbix_hostid,
                host.zabbix_host_name,
                host.zabbix_url,
                host.zabbix_agent_availability,
                host.problem_count,
                host.zabbix_last_sync_at,
                host.monitoring_status,
            ]
        )
    apply_sheet_style(ws, headers)
    return workbook_response(workbook, "dba_inventory_hosts.xlsx")


@router.get("/databases.xlsx")
def export_databases(
    db_type: str | None = None,
    environment: str | None = None,
    role: str | None = None,
    monitoring_status: str | None = None,
    db: Session = Depends(get_db),
):
    maybe_refresh_zabbix_cache(db)
    stmt = (
        select(DatabaseInstance)
        .options(selectinload(DatabaseInstance.host))
        .order_by(DatabaseInstance.db_type, DatabaseInstance.name)
    )
    stmt = apply_database_filters(stmt, db_type, environment, role, monitoring_status)
    databases = db.scalars(stmt).all()

    headers = [
        "db_type",
        "name",
        "host",
        "environment",
        "version",
        "port",
        "service_name",
        "status",
        "powa_repository",
        "powa_server_name",
        "powa_database_name",
        "last_snapshot",
        "monitoring_status",
    ]
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Databases"
    ws.append(headers)
    for database in databases:
        ws.append(
            [
                database.db_type,
                database.name,
                database.host.hostname,
                database.environment,
                database.version,
                database.port,
                database.service_name,
                database.status,
                database.powa_repository,
                database.powa_server_name,
                database.powa_database_name,
                database.last_snapshot,
                database.host.monitoring_status,
            ]
        )
    apply_sheet_style(ws, headers)
    return workbook_response(workbook, "dba_inventory_databases.xlsx")
