"""Принтеры наклеек и терминалы самообслуживания."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Numeric, SmallInteger, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TRUE, ZERO, created_at, fk, pk


class Printer(Base):
    __tablename__ = "printer"
    __table_args__ = (
        CheckConstraint("density BETWEEN 0 AND 15", name="density"),
        CheckConstraint("speed BETWEEN 1 AND 6", name="speed"),
    )

    id: Mapped[int] = pk()
    name: Mapped[str] = mapped_column(unique=True)
    # sha256 hex токена агента печати
    agent_token_hash: Mapped[str | None] = mapped_column(unique=True)
    windows_printer_name: Mapped[str | None]
    dpi: Mapped[int] = mapped_column(server_default=text("203"))
    # Калибровка (по результатам печати на XP-360B)
    offset_x_mm: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), server_default=ZERO
    )  # может быть < 0
    offset_y_mm: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=ZERO)
    density: Mapped[int] = mapped_column(SmallInteger, server_default=text("10"))
    speed: Mapped[int] = mapped_column(SmallInteger, server_default=text("3"))
    status: Mapped[str] = mapped_column(server_default=text("'unknown'"))
    last_seen_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()


class Terminal(Base):
    __tablename__ = "terminal"

    id: Mapped[int] = pk()
    name: Mapped[str] = mapped_column(unique=True)
    # sha256 hex токена терминала
    token_hash: Mapped[str | None] = mapped_column(unique=True)
    printer_id: Mapped[int | None] = fk("printer.id", nullable=True)
    is_enabled: Mapped[bool] = mapped_column(server_default=TRUE)
    last_seen_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
