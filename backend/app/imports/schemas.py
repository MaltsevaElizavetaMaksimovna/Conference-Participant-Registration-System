"""Схемы импорта участников из Excel и Битрикс24 (IM-01..IM-04)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

ImportSource = Literal["file", "bitrix"]
ImportStatus = Literal["running", "done", "failed"]


class ImportAcceptedOut(BaseModel):
    batch_id: int = Field(
        description="Идентификатор загрузки; отчёт — GET .../imports/{batch_id}", examples=[12]
    )


class ImportRowError(BaseModel):
    row: int | None = Field(
        description="Номер строки файла (заголовки — строка 1); null для общих ошибок",
        examples=[15],
    )
    reason: str = Field(description="Причина пропуска", examples=["не указана фамилия"])
    message: str = Field(
        description="Готовый текст для показа", examples=["Строка 15: не указана фамилия"]
    )


class ImportConflict(BaseModel):
    """Расхождение: поле исправлено регистратором, файл содержит другое значение (IM-02)."""

    participant_id: int = Field(examples=[17])
    external_id: str = Field(examples=["P-1001"])
    field: str = Field(
        description="Поле участника; доп. поля — `extra.<key>`", examples=["position"]
    )
    system_value: str | None = Field(
        description="Значение в системе (осталось)", examples=["Инженер"]
    )
    file_value: str | None = Field(
        description="Значение в файле (не применено)", examples=["Ведущий инженер"]
    )


class ImportMissing(BaseModel):
    """Участник есть в системе, но отсутствует в новом файле (не удаляется)."""

    participant_id: int = Field(examples=[18])
    external_id: str = Field(examples=["P-1002"])
    full_name: str = Field(examples=["Петрова Анна Ивановна"])


class ImportPhotosOut(BaseModel):
    total: int = Field(0, description="Сколько фото нужно скачать")
    loaded: int = Field(0, description="Сколько загружено")
    failed: int = Field(0, description="Сколько не удалось (предупреждения в warnings)")
    pending: int = Field(0, description="Сколько ещё качается; 0 — загрузка фото закончена")


class ImportReportOut(BaseModel):
    batch_id: int = Field(examples=[12])
    conference_id: int = Field(examples=[1])
    source: ImportSource
    file_name: str | None = Field(examples=["participants.xlsx"])
    status: ImportStatus = Field(
        description="Пока `running` — отчёт неполный, опрашивайте повторно"
    )
    summary: str = Field(
        description="Итог одной строкой", examples=["Загружено: 300, пропущено: 0"]
    )
    total_rows: int = Field(description="Непустых строк данных в файле", examples=[300])
    loaded: int = Field(description="Добавлено новых участников", examples=[300])
    updated: int = Field(
        description="Существующих участников, у которых что-то изменилось", examples=[0]
    )
    unchanged: int = Field(description="Существующих участников без изменений", examples=[0])
    skipped: int = Field(description="Строк, которые не загружены (см. errors)", examples=[0])
    errors: list[ImportRowError] = Field(description="Пропущенные строки и причины")
    conflicts: list[ImportConflict] = Field(
        description="Расхождения с данными, исправленными вручную: из файла они не применяются"
    )
    missing: list[ImportMissing] = Field(
        description="Участники, которых нет в файле (остаются в системе)"
    )
    warnings: list[str] = Field(description="Замечания, не мешающие загрузке")
    photos: ImportPhotosOut = Field(
        default_factory=ImportPhotosOut, description="Загрузка фото участников по ссылкам"
    )
    started_at: datetime = Field(examples=["2026-11-19T18:00:00+03:00"])
    finished_at: datetime | None = Field(examples=["2026-11-19T18:00:07+03:00"])


class ImportBatchShort(BaseModel):
    """Строка списка загрузок; полный отчёт — `GET .../imports/{id}`."""

    id: int = Field(examples=[12])
    source: ImportSource
    file_name: str | None = Field(
        description="Имя файла; у загрузки из Битрикс24 — null", examples=["participants.xlsx"]
    )
    status: ImportStatus
    created_at: datetime = Field(
        description="Когда загрузка началась", examples=["2026-11-19T18:00:00+03:00"]
    )
    finished_at: datetime | None = Field(examples=["2026-11-19T18:00:07+03:00"])
    user_login: str | None = Field(
        description="Кто запустил; null, если сотрудник удалён или загрузка по расписанию",
        examples=["admin"],
    )
    loaded: int = Field(description="Добавлено новых участников", examples=[300])
    updated: int = Field(description="Обновлено существующих участников", examples=[0])
    skipped: int = Field(description="Пропущено строк", examples=[0])


BitrixEntity = Literal["contact", "deal", "smart_process"]


class BitrixSettingsIn(BaseModel):
    """Настройки загрузки из Битрикс24. URL вебхука сюда не входит: он задаётся в окружении."""

    entity: BitrixEntity = Field(
        description="Откуда брать участников: контакты, сделки или смарт-процесс",
        examples=["contact"],
    )
    entity_type_id: int | None = Field(
        default=None,
        description="Идентификатор типа смарт-процесса; обязателен при `entity=smart_process`",
        examples=[None],
        validate_default=True,
    )
    filter: dict[str, Any] = Field(
        default_factory=dict,
        description="Фильтр выборки в формате Битрикс24 (`crm.*.list`)",
        examples=[{"=SOURCE_ID": "WEB"}],
    )
    field_map: dict[str, str] = Field(
        default_factory=dict,
        description="Соответствие «системное поле: поле Битрикс24»",
        examples=[{"last_name": "LAST_NAME", "first_name": "NAME", "external_id": "ID"}],
    )

    @field_validator("entity_type_id")
    @classmethod
    def _smart_process_needs_type(cls, v: int | None, info: ValidationInfo) -> int | None:
        if v is None and info.data.get("entity") == "smart_process":
            raise ValueError("Укажите тип смарт-процесса")
        return v


class BitrixSettingsOut(BitrixSettingsIn):
    webhook_configured: bool = Field(
        description=(
            "Задан ли вебхук Битрикс24 на сервере (`RS_BITRIX_WEBHOOK_URL`). "
            "Сам адрес API никогда не отдаёт и не принимает"
        ),
        examples=[True],
    )
