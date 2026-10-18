"""Задания печати и записи идемпотентности."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, SmallInteger, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import PrintJobKind, PrintJobStatus
from app.models.base import ZERO, created_at, fk, in_check, pk


class PrintJob(Base):
    __tablename__ = "print_job"
    __table_args__ = (
        in_check("kind", PrintJobKind, "kind"),
        in_check("status", PrintJobStatus, "status"),
        CheckConstraint("sides IN (1, 2)", name="sides"),
        Index("ix_print_job_printer_status_created", "printer_id", "status", "created_at"),
    )

    id: Mapped[int] = pk()
    conference_id: Mapped[int] = fk("conference.id")
    # NULL у пробной печати
    participant_id: Mapped[int | None] = fk("participant.id", nullable=True)
    badge_token_id: Mapped[int | None] = fk("badge_token.id", nullable=True)
    printer_id: Mapped[int] = fk("printer.id")
    kind: Mapped[str]
    sides: Mapped[int] = mapped_column(SmallInteger)
    # Только для пробной печати: шаблон и картинка выбираются при выдаче задания агенту (PR-05)
    template_id: Mapped[int | None] = fk("label_template.id", nullable=True)
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    error: Mapped[str | None]
    attempts: Mapped[int] = mapped_column(server_default=ZERO)
    idempotency_key: Mapped[str | None] = mapped_column(unique=True)
    created_by_user_id: Mapped[int | None] = fk("staff_user.id", nullable=True)
    created_by_terminal_id: Mapped[int | None] = fk("terminal.id", nullable=True)
    created_at: Mapped[datetime] = created_at()
    sent_at: Mapped[datetime | None]
    done_at: Mapped[datetime | None]


class IdempotencyRecord(Base):
    """Повторный ответ на confirm с тем же `Idempotency-Key`."""

    __tablename__ = "idempotency_record"

    key: Mapped[str] = mapped_column(primary_key=True)
    scope: Mapped[str]
    response: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
