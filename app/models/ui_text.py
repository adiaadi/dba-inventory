from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin


class UiText(TimestampMixin, Base):
    __tablename__ = "ui_texts"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(160))
    default_value: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
