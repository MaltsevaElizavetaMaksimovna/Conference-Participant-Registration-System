"""Схемы импорта участников из Excel и Битрикс24 (IM-01..IM-04)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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
    started_at: datetime = Field(examples=["2026-11-19T18:00:00+03:00"])
    finished_at: datetime | None = Field(examples=["2026-11-19T18:00:07+03:00"])
