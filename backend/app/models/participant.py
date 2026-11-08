"""Участники, коды бейджей, журнал изменений и журнал событий."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import BadgeTokenStatus, ChangeSource, ParticipantStatus, RegSource
from app.models.base import (
    FALSE,
    JSONB_OBJECT,
    TEXT_ARRAY_EMPTY,
    ZERO,
    created_at,
    fk,
    in_check,
    pk,
    updated_at,
)


class Participant(Base):
    __tablename__ = "participant"
    __table_args__ = (
        UniqueConstraint("conference_id", "external_id", name="uq_participant_external_id"),
        in_check("status", ParticipantStatus, "status"),
        in_check("reg_source", RegSource, "reg_source"),
        # Статус «не зарегистрирован» <=> нет времени регистрации
        CheckConstraint(
            "(status = 'not_registered') = (registered_at IS NULL)",
            name="status_registered_at",
        ),
        Index("ix_participant_conference_status", "conference_id", "status"),
        # Поиск по ФИО: префиксный LIKE по нормализованной строке (без pg_trgm)
        Index(
            "ix_participant_conference_search_norm",
            "conference_id",
            "search_norm",
            postgresql_ops={"search_norm": "text_pattern_ops"},
        ),
    )

    id: Mapped[int] = pk()
    conference_id: Mapped[int] = fk("conference.id")
    # NULL — участник добавлен вручную
    external_id: Mapped[str | None]

    last_name: Mapped[str]
    first_name: Mapped[str]
    middle_name: Mapped[str | None]
    position: Mapped[str | None]
    organization: Mapped[str | None]
    last_name_en: Mapped[str | None]
    first_name_en: Mapped[str | None]
    middle_name_en: Mapped[str | None]
    position_en: Mapped[str | None]
    organization_en: Mapped[str | None]

    # Дополнительные поля из файла
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=JSONB_OBJECT)
    # Последние импортированные значения стандартных и доп. полей
    source_data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=JSONB_OBJECT)
    # Поля, исправленные вручную: импорт их не перезаписывает
    manual_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=TEXT_ARRAY_EMPTY)
    is_manual_added: Mapped[bool] = mapped_column(server_default=FALSE)
    photo_path: Mapped[str | None]
    photo_sha256: Mapped[str | None]
    # normalize_search(f"{last} {first} {middle}"); считает приложение при каждой записи ФИО
    search_norm: Mapped[str]

    # Регистрация (меняет только registration.service)
    status: Mapped[str] = mapped_column(server_default=text("'not_registered'"))
    registered_at: Mapped[datetime | None]
    reg_source: Mapped[str | None]
    reg_terminal_id: Mapped[int | None] = fk("terminal.id", nullable=True)
    reg_user_id: Mapped[int | None] = fk("staff_user.id", nullable=True)

    # Пометки
    error_reported_at: Mapped[datetime | None]
    sticker_not_printed: Mapped[bool] = mapped_column(server_default=FALSE)
    foreign_code_at: Mapped[datetime | None]
    foreign_code_by: Mapped[int | None] = fk("staff_user.id", nullable=True)
    print_count: Mapped[int] = mapped_column(server_default=ZERO)
    rescan_count: Mapped[int] = mapped_column(server_default=ZERO)

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class BadgeToken(Base):
    """Код бейджа. Токен хранится открытым текстом: при повторной печати нужен тот же QR."""

    __tablename__ = "badge_token"
    __table_args__ = (
        in_check("status", BadgeTokenStatus, "status"),
        # У участника не больше одного действующего кода
        Index(
            "uq_badge_token_participant_active",
            "participant_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = pk()
    participant_id: Mapped[int] = fk("participant.id")
    token: Mapped[str] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    created_at: Mapped[datetime] = created_at()
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[int | None] = fk("staff_user.id", nullable=True)


class ChangeLog(Base):
    """Журнал изменений данных (ER-03). Только добавление: UPDATE/DELETE запрещены триггером."""

    __tablename__ = "change_log"
    __table_args__ = (
        in_check("source", ChangeSource, "source"),
        Index("ix_change_log_participant_created", "participant_id", "created_at"),
    )

    id: Mapped[int] = pk()
    participant_id: Mapped[int] = fk("participant.id")
    field: Mapped[str]
    old_value: Mapped[str | None]
    new_value: Mapped[str | None]
    source: Mapped[str]
    user_id: Mapped[int | None] = fk("staff_user.id", nullable=True)
    import_batch_id: Mapped[int | None] = fk("import_batch.id", nullable=True)
    created_at: Mapped[datetime] = created_at()


class EventLog(Base):
    """Журнал событий; из него строятся отчёты (RP-02). Типы — `EventType`."""

    __tablename__ = "event_log"
    __table_args__ = (
        Index("ix_event_log_participant_created", "participant_id", "created_at"),
        Index("ix_event_log_conference_type_created", "conference_id", "type", "created_at"),
    )

    id: Mapped[int] = pk()
    conference_id: Mapped[int | None] = fk("conference.id", nullable=True)
    participant_id: Mapped[int | None] = fk("participant.id", nullable=True)
    type: Mapped[str]
    terminal_id: Mapped[int | None] = fk("terminal.id", nullable=True)
    user_id: Mapped[int | None] = fk("staff_user.id", nullable=True)
    raw_code: Mapped[str | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=JSONB_OBJECT)
    created_at: Mapped[datetime] = created_at()
