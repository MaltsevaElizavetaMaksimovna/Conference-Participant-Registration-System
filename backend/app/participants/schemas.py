"""Схемы участников (RG-02, RG-03, RG-06, RG-07, ER-03)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# TODO: заменить на общие enum (app/core/enums.py)
ParticipantStatus = Literal["not_registered", "registered", "registered_no_sticker"]
ParticipantFlag = Literal[
    "error_reported", "sticker_not_printed", "data_changed", "manual_added", "foreign_code"
]
ParticipantFilter = Literal["all", "registered", "not_registered", "flagged"]
ParticipantSort = Literal["name", "registered_at", "-registered_at"]
RegistrationSource = Literal["terminal", "desk"]
EventType = Literal[
    "scan_not_found",
    "scan_rescan",
    "error_reported",
    "registered",
    "print_ok",
    "print_error",
    "reprint",
    "foreign_code",
    "data_changed",
    "manual_added",
]


class ParticipantShort(BaseModel):
    """Строка списка и поиска."""

    id: int = Field(examples=[17])
    full_name: str = Field(examples=["Иванов Пётр Сергеевич"])
    organization: str | None = Field(examples=["ООО Ромашка"])
    status: ParticipantStatus
    flags: list[ParticipantFlag] = Field(
        description="Пометки для значков в списке", examples=[["data_changed"]]
    )


class ExtraField(BaseModel):
    key: str = Field(examples=["section"])
    label: str = Field(description="Заголовок столбца из файла", examples=["Секция"])
    value: str | None = Field(examples=["A"])


class RegistrationInfo(BaseModel):
    at: datetime = Field(examples=["2026-11-20T09:15:03+03:00"])
    source: RegistrationSource = Field(description="Где зарегистрирован: терминал или стойка")
    terminal_name: str | None = Field(examples=["Терминал 2"])
    user_login: str | None = Field(description="Регистратор, если со стойки", examples=[None])


class FlagInfo(BaseModel):
    code: ParticipantFlag
    at: datetime = Field(examples=["2026-11-20T09:20:00+03:00"])
    by: str | None = Field(description="Логин сотрудника, поставившего пометку", examples=[None])


class HistoryItem(BaseModel):
    """Запись журнала изменений данных (ER-03)."""

    field: str = Field(examples=["organization"])
    old: str | None = Field(examples=["Ромашка"])
    new: str | None = Field(examples=["ООО Ромашка"])
    source: Literal["manual", "import"]
    user_login: str | None = Field(examples=["reg1"])
    at: datetime = Field(examples=["2026-11-20T09:00:00+03:00"])


class EventItem(BaseModel):
    type: EventType = Field(examples=["scan_rescan"])
    at: datetime = Field(examples=["2026-11-20T09:30:00+03:00"])
    terminal_name: str | None = Field(examples=["Терминал 1"])
    user_login: str | None = Field(examples=[None])


class ParticipantActions(BaseModel):
    """Что можно делать с участником. Вычисляет бэкенд с учётом прав и состояния."""

    can_register: bool
    can_reprint: bool
    can_edit: bool
    can_foreign_code: bool
    reasons: dict[str, str] = Field(
        description="Почему действие недоступно: ключ — имя флага, значение — подсказка",
        examples=[{"can_register": "Уже зарегистрирован 20.11 09:15, Терминал 2"}],
    )


class ParticipantCard(BaseModel):
    id: int = Field(examples=[17])
    external_id: str | None = Field(
        description="ID из файла/Битрикс; null у добавленных вручную", examples=["B24-1001"]
    )
    last_name: str = Field(examples=["Иванов"])
    first_name: str = Field(examples=["Пётр"])
    middle_name: str | None = Field(examples=["Сергеевич"])
    position: str | None = Field(examples=["Инженер"])
    organization: str | None = Field(examples=["ООО Ромашка"])
    last_name_en: str | None = None
    first_name_en: str | None = None
    middle_name_en: str | None = None
    position_en: str | None = None
    organization_en: str | None = None
    extra: list[ExtraField] = Field(description="Дополнительные поля из файла")
    status: ParticipantStatus
    registration: RegistrationInfo | None = Field(description="null, если не зарегистрирован")
    flags: list[FlagInfo]
    photo_url: str | None = Field(examples=["/api/participants/17/photo"])
    profile_url: str | None = Field(examples=["https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4"])
    print_count: int = Field(examples=[1])
    rescan_count: int = Field(description="Сколько раз код предъявляли повторно", examples=[2])
    history: list[HistoryItem]
    events: list[EventItem]
    actions: ParticipantActions


class ParticipantStats(BaseModel):
    registered: int = Field(examples=[120])
    total: int = Field(examples=[300])


def _not_blank(v: str | None, message: str) -> str | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        raise ValueError(message)
    return v


class ParticipantUpdateIn(BaseModel):
    """Правка данных (RG-06, ER-03). Передавайте только изменённые поля.

    Пробелы считаются пустым значением; фамилия и имя обязательны.
    """

    last_name: str | None = Field(default=None, max_length=100, examples=["Иванов"])
    first_name: str | None = Field(default=None, max_length=100, examples=["Пётр"])
    middle_name: str | None = Field(default=None, max_length=100)
    position: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200, examples=["ООО Ромашка"])
    last_name_en: str | None = Field(default=None, max_length=100)
    first_name_en: str | None = Field(default=None, max_length=100)
    middle_name_en: str | None = Field(default=None, max_length=100)
    position_en: str | None = Field(default=None, max_length=200)
    organization_en: str | None = Field(default=None, max_length=200)

    # Валидаторы вызываются только для переданных полей: явный null фамилии/имени — ошибка
    @field_validator("last_name")
    @classmethod
    def _last(cls, v: str | None) -> str | None:
        return _not_blank(v if v is not None else "", "Укажите фамилию")

    @field_validator("first_name")
    @classmethod
    def _first(cls, v: str | None) -> str | None:
        return _not_blank(v if v is not None else "", "Укажите имя")

    @field_validator(
        "middle_name",
        "position",
        "organization",
        "last_name_en",
        "first_name_en",
        "middle_name_en",
        "position_en",
        "organization_en",
    )
    @classmethod
    def _optional(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class CheckDuplicatesIn(BaseModel):
    last_name: str = Field(max_length=100, examples=["Иванов"])
    first_name: str = Field(max_length=100, examples=["Пётр"])

    @field_validator("last_name")
    @classmethod
    def _last(cls, v: str) -> str:
        return _not_blank(v, "Укажите фамилию") or ""

    @field_validator("first_name")
    @classmethod
    def _first(cls, v: str) -> str:
        return _not_blank(v, "Укажите имя") or ""


class DuplicatesOut(BaseModel):
    items: list[ParticipantShort] = Field(description="Участники с похожими ФИО")


class ParticipantCreateIn(BaseModel):
    """Добавление участника на месте с немедленной регистрацией (RG-07).

    Пробелы считаются пустым значением; фамилия и имя обязательны.
    """

    last_name: str = Field(max_length=100, examples=["Кузнецов"])
    first_name: str = Field(max_length=100, examples=["Алексей"])
    middle_name: str | None = Field(default=None, max_length=100)
    position: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    with_sticker: bool = Field(default=True, description="Печатать ли наклейку сразу")

    @field_validator("last_name")
    @classmethod
    def _last(cls, v: str) -> str:
        return _not_blank(v, "Укажите фамилию") or ""

    @field_validator("first_name")
    @classmethod
    def _first(cls, v: str) -> str:
        return _not_blank(v, "Укажите имя") or ""

    @field_validator("middle_name", "position", "organization")
    @classmethod
    def _optional(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        return v or None


class ParticipantCreatedOut(BaseModel):
    participant: ParticipantCard
    print_job_id: int | None = Field(
        description="null, если наклейка не печаталась", examples=[501]
    )
