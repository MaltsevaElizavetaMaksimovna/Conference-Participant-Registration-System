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
        description="Номер строки файла (с 1); null для общих ошибок", examples=[17]
    )
    field: str | None = Field(description="Столбец или поле с ошибкой", examples=["last_name"])
    message: str = Field(examples=["Не указана фамилия"])


class ImportReportOut(BaseModel):
    batch_id: int = Field(examples=[12])
    conference_id: int = Field(examples=[1])
    source: ImportSource
    file_name: str | None = Field(examples=["participants.xlsx"])
    status: ImportStatus = Field(
        description="Пока `running` — отчёт неполный, опрашивайте повторно"
    )
    total_rows: int = Field(examples=[300])
    created: int = Field(description="Добавлено новых участников", examples=[290])
    updated: int = Field(description="Обновлено существующих", examples=[8])
    unchanged: int = Field(description="Без изменений", examples=[0])
    failed: int = Field(description="Строк с ошибками (см. errors)", examples=[2])
    errors: list[ImportRowError]
    started_at: datetime = Field(examples=["2026-11-19T18:00:00+03:00"])
    finished_at: datetime | None = Field(examples=["2026-11-19T18:00:07+03:00"])
