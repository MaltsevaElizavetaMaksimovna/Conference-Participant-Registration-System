"""Схемы терминала самообслуживания и админки терминалов (TR-01..TR-09, NF-05, AD-02)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.common import BadgeType, PrintJobStatus


class PingConference(BaseModel):
    title: str = Field(examples=["Конференция «Инновации-2026»"])
    badge_type: BadgeType


class TerminalSettings(BaseModel):
    idle_timeout_s: int = Field(description="Возврат на экран ожидания, с", examples=[60])
    result_screen_s: int = Field(
        description="Сколько показывать экран результата, с", examples=[10]
    )


class PingOut(BaseModel):
    terminal_name: str = Field(examples=["Терминал 2"])
    enabled: bool
    conference: PingConference | None = Field(description="null, если нет активной конференции")
    printer_online: bool
    server_time: datetime
    settings: TerminalSettings


class ScanIn(BaseModel):
    raw: str = Field(
        min_length=1,
        max_length=2000,
        description="Строка от сканера как есть: бэкенд сам исправляет раскладку и достаёт токен",
        examples=["https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4"],
    )


class ScanParticipant(BaseModel):
    id: int = Field(examples=[17])
    full_name: str = Field(examples=["Иванов Пётр Сергеевич"])
    position: str = Field(description="«не указано», если пусто", examples=["не указано"])
    organization: str = Field(examples=["ООО Ромашка"])


class ScanFound(BaseModel):
    result: Literal["found"]
    scan_id: str = Field(
        description="Передайте в confirm и report-error", examples=["scan_8f14e45f"]
    )
    participant: ScanParticipant


class ScanNotFound(BaseModel):
    result: Literal["not_found"]
    message: str = Field(examples=["Участник не найден. Обратитесь к стойке регистрации"])


class ScanAlreadyRegistered(BaseModel):
    result: Literal["already_registered"]
    message: str = Field(
        examples=[
            "Вы уже зарегистрированы (20.11, 09:15). "
            "Если вы не получили бейдж — обратитесь к стойке регистрации"
        ]
    )


ScanOut = Annotated[ScanFound | ScanNotFound | ScanAlreadyRegistered, Field(discriminator="result")]


class ConfirmIn(BaseModel):
    participant_id: int = Field(examples=[17])
    scan_id: str = Field(examples=["scan_8f14e45f"])


class ConfirmOut(BaseModel):
    result: Literal["registered", "already_registered"]
    print_job_id: int | None = Field(
        default=None, description="Есть только при result=registered", examples=[501]
    )
    message: str = Field(examples=["Заберите наклейку из принтера"])


class ReportErrorIn(BaseModel):
    participant_id: int = Field(examples=[17])
    scan_id: str = Field(examples=["scan_8f14e45f"])


class ReportErrorOut(BaseModel):
    message: str = Field(examples=["Спасибо, мы передали информацию. Обратитесь к стойке"])


class TerminalPrintJobOut(BaseModel):
    status: PrintJobStatus
    message: str = Field(description="Текст для экрана терминала (в т.ч. TR-08)")


class TerminalOut(BaseModel):
    id: int = Field(examples=[2])
    name: str = Field(examples=["Терминал 2"])
    enabled: bool
    printer_id: int | None = Field(description="Принтер, привязанный к терминалу", examples=[1])
    last_seen_at: datetime | None
    token_set: bool = Field(description="Выдан ли токен терминалу")


class TerminalIn(BaseModel):
    """Создание и изменение. В `PUT` меняются только переданные поля (кроме `name`)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Название терминала; попадает в отметку о регистрации. Уникально",
        examples=["Терминал 2"],
    )
    enabled: bool = Field(
        default=True, description="false — терминал не принимает коды (423 terminal_disabled)"
    )
    printer_id: int | None = Field(
        default=None,
        description="Принтер терминала: терминал печатает только на него. null — не привязан",
    )


class TerminalTokenOut(BaseModel):
    id: int = Field(examples=[2])
    token: str = Field(
        description="Токен для `Authorization: Terminal <token>`. Показывается один раз!",
        examples=["trm_Zk3x9QnS7Vb2LmT4Zk3x9QnS7Vb2LmT4"],
    )
