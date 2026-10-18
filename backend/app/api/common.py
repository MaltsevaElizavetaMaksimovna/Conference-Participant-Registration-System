"""Общие схемы и хелперы контракта API."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Query
from pydantic import BaseModel, Field

STUB_TAG = "stub"

PrinterStatus = Literal["unknown", "online", "offline", "error", "paper_out"]
PrintJobStatus = Literal["pending", "sent", "done", "error"]
BadgeType = Literal["single", "double", "none"]


class ErrorOut(BaseModel):
    """Единый формат ошибки для всех 4xx/5xx."""

    code: str = Field(
        description="Машинный код ошибки, на него опирается логика фронта",
        examples=["already_registered"],
    )
    message: str = Field(
        description="Готовый текст для пользователя",
        examples=["Вы уже зарегистрированы (20.11, 09:15)."],
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Доп. данные; при validation_error: details.fields = {поле: сообщение}",
    )


class Page[T](BaseModel):
    """Страница списка: `?limit=50&offset=0`."""

    items: list[T]
    total: int = Field(description="Сколько всего записей подходит под фильтр", examples=[123])


Limit = Annotated[int, Query(ge=1, le=200, description="Размер страницы")]
Offset = Annotated[int, Query(ge=0, description="Сколько записей пропустить")]


class PrinterOut(BaseModel):
    id: int = Field(examples=[1])
    name: str = Field(examples=["Принтер 1"])
    status: PrinterStatus = Field(description="Последний статус, присланный агентом печати")
    last_seen_at: datetime | None = Field(
        description="Последний heartbeat агента", examples=["2026-11-20T09:15:03+03:00"]
    )


class PrintJobRefOut(BaseModel):
    print_job_id: int = Field(
        description="Идентификатор задания печати; статус — GET /api/print-jobs/{id}",
        examples=[501],
    )


_DEFAULT_ERRORS: dict[int, str] = {
    401: "`unauthenticated`: нет действующей сессии / токена",
    403: "`forbidden`: не хватает разрешения",
    404: "`not_found`: объект не найден",
    409: "`conflict`: конфликт состояния",
    422: "`validation_error`: `details.fields = {поле: сообщение}`",
    423: "`terminal_disabled`: терминал отключён администратором",
    429: "`too_many_requests`: слишком частые запросы",
}


def err(*items: int | tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    """Описание ошибочных ответов для `responses=` (всегда модель `ErrorOut`).

    `err(401, 403, (409, "`role_in_use`: роль назначена пользователям"))`
    """
    result: dict[int | str, dict[str, Any]] = {}
    for item in items:
        status, text = item if isinstance(item, tuple) else (item, _DEFAULT_ERRORS[item])
        result[status] = {"model": ErrorOut, "description": text}
    return result
