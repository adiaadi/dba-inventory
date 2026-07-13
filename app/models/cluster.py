from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin


class Cluster(TimestampMixin, Base):
    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    cluster_type: Mapped[str] = mapped_column(String(80), index=True)
    environment: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True, default="unknown")
    primary_node: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)

    members: Mapped[list["ClusterMember"]] = relationship(
        back_populates="cluster",
        cascade="all, delete-orphan",
    )


class ClusterMember(TimestampMixin, Base):
    __tablename__ = "cluster_members"
    __table_args__ = (
        UniqueConstraint("cluster_id", "database_instance_id", name="uq_cluster_member_instance"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    database_instance_id: Mapped[int] = mapped_column(
        ForeignKey("database_instances.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(80), index=True)
    sync_state: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[int | None] = mapped_column()

    cluster: Mapped["Cluster"] = relationship(back_populates="members")
    database_instance: Mapped["DatabaseInstance"] = relationship(back_populates="cluster_memberships")
