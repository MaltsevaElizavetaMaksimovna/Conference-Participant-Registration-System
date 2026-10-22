"""Схемы конференций (AD-01)."""

import re
from datetime import date, datetime

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.api.common import BadgeType


class ConferenceIn(BaseModel):
    title: str = Field(min_length=1, max_length=200, examples=["Конференция «Инновации-2026»"])
    date_from: date = Field(examples=["2026-11-20"])
    date_to: date = Field(examples=["2026-11-21"])
    badge_type: BadgeType = Field(
        default="single",
        description="`single` — односторонний бейдж, `double` — двусторонний, `none` — без бейджа",
    )
    front_template_id: int | None = Field(default=None, description="Шаблон лицевой стороны")
    back_template_id: int | None = Field(default=None, description="Шаблон оборотной стороны")
    changed_template_id: int | None = Field(
        default=None, description="Шаблон лица для флага «Данные изменены»"
    )
    changed_back_template_id: int | None = Field(
        default=None, description="Шаблон оборота для флага «Данные изменены»"
    )
    invite_id_regex: str | None = Field(
        default=None,
        description="Регулярка для извлечения ID из ссылки приглашения; null — общая настройка",
        examples=[r"id=(B\d+-\d+)"],
    )

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Укажите название конференции")
        return v

    @field_validator("invite_id_regex")
    @classmethod
    def _regex_valid(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if len(v) > 500:
            raise ValueError("Регулярка длиннее 500 символов")
        try:
            groups = re.compile(v).groups
        except re.error as e:
            raise ValueError(f"Некорректная регулярка: {e}") from e
        if groups < 1:
            raise ValueError("В регулярке нужна группа (...), которая выделяет ID")
        return v

    @field_validator("date_to")
    @classmethod
    def _dates_order(cls, v: date, info: ValidationInfo) -> date:
        start = info.data.get("date_from")
        if start is not None and v < start:
            raise ValueError("Дата окончания раньше даты начала")
        return v


class ConferenceOut(ConferenceIn):
    id: int = Field(examples=[3])
    is_active: bool = Field(description="Активна ровно одна конференция", examples=[True])
    participants_total: int = Field(examples=[300])
    created_at: datetime = Field(examples=["2026-10-01T12:00:00+03:00"])
