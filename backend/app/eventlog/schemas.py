"""Схемы журнала событий."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.participants.schemas import EventType


class EventOut(BaseModel):
    """Событие из `event_log`: скан, регистрация, печать, правка данных и т. п."""

    id: int = Field(examples=[1024])
    type: EventType = Field(
        description=(
            "`scan_not_found`, `scan_rescan`, `error_reported`, `registered`, `print_ok`, "
            "`print_error`, `reprint`, `foreign_code`, `data_changed`, `manual_added`"
        ),
        examples=["scan_rescan"],
    )
    at: datetime = Field(examples=["2026-11-20T09:15:03+03:00"])
    participant_id: int | None = Field(
        description="null, если код не найден (`scan_not_found`)", examples=[17]
    )
    participant_name: str | None = Field(examples=["Иванов Пётр Сергеевич"])
    terminal_name: str | None = Field(
        description="Терминал, на котором произошло событие", examples=["Терминал 2"]
    )
    user_login: str | None = Field(
        description="Сотрудник, если действие совершено со стойки", examples=[None]
    )
    raw_code: str | None = Field(
        description="Строка от сканера как есть (для `scan_not_found`)", examples=[None]
    )
    payload: dict[str, Any] = Field(
        description="Подробности события; состав зависит от `type`", examples=[{}]
    )
