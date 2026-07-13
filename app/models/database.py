from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class DatabaseInstance(TimestampMixin, Base):
    __tablename__ = "database_instances"

    id: Mapped[int] = mapped_column(primary_key=True)
    host_id: Mapped[int] = mapped_column(ForeignKey("hosts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    db_type: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[str | None] = mapped_column(String(80))
    port: Mapped[int | None] = mapped_column(Integer)
    environment: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(80), index=True)
    service_name: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)

    powa_repository: Mapped[str | None] = mapped_column(String(255))
    powa_server_name: Mapped[str | None] = mapped_column(String(255), index=True)
    powa_database_name: Mapped[str | None] = mapped_column(String(255))
    last_snapshot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), index=True, default="unknown")

    host: Mapped["Host"] = relationship(back_populates="databases")
    cluster_memberships: Mapped[list["ClusterMember"]] = relationship(
        back_populates="database_instance",
        cascade="all, delete-orphan",
    )
