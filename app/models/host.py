from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Host(TimestampMixin, Base):
    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(primary_key=True)
    hostname: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    fqdn: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    environment: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(80), index=True)
    db_type: Mapped[str | None] = mapped_column(String(60), index=True)
    os_name: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(120))
    owner_team: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)

    zabbix_hostid: Mapped[str | None] = mapped_column(String(80), index=True)
    zabbix_host_name: Mapped[str | None] = mapped_column(String(255))
    zabbix_url: Mapped[str | None] = mapped_column(String(500))
    zabbix_agent_availability: Mapped[str] = mapped_column(String(40), index=True, default="unknown")
    problem_count: Mapped[int] = mapped_column(Integer, default=0)
    zabbix_last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monitoring_status: Mapped[str] = mapped_column(String(40), index=True, default="unknown")

    databases: Mapped[list["DatabaseInstance"]] = relationship(
        back_populates="host",
        cascade="all, delete-orphan",
    )
