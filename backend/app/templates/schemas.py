"""Схемы шаблонов наклеек (PR-01..PR-05)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TemplateKind = Literal["front", "back", "changed", "changed_back"]
ElementType = Literal["field", "text", "qr"]
Align = Literal["left", "center", "right"]


class TemplateElement(BaseModel):
    type: ElementType = Field(description="`field` — поле участника, `text` — надпись, `qr` — QR")
    field: str | None = Field(
        default=None,
        description="Для type=field: `last_name`, `organization`, … или `extra.<ключ>`",
        examples=["last_name"],
    )
    text: str | None = Field(default=None, description="Для type=text", examples=[None])
    x_mm: float = Field(examples=[3])
    y_mm: float = Field(examples=[3])
    w_mm: float = Field(gt=0, examples=[54])
    h_mm: float = Field(gt=0, examples=[10])
    font_size: float = Field(default=14, gt=0, description="Кегль, pt", examples=[14])
    min_font_size: float = Field(
        default=8, gt=0, description="Минимальный кегль при автоуменьшении", examples=[8]
    )
    max_lines: int = Field(default=1, ge=1, examples=[2])
    align: Align = "left"
    bold: bool = False


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Лицевая сторона"])
    kind: TemplateKind = Field(
        description="`front`/`back` — лицо и оборот; `changed*` — для флага «Данные изменены»"
    )
    width_mm: float = Field(gt=0, le=200, examples=[60])
    height_mm: float = Field(gt=0, le=200, examples=[40])
    gap_mm: float = Field(
        default=2, ge=0, le=20, description="Зазор между наклейками", examples=[2]
    )
    elements: list[TemplateElement] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Укажите название шаблона")
        return v


class TemplateOut(TemplateIn):
    id: int = Field(examples=[1])
    conference_id: int = Field(examples=[1])
    version: int = Field(description="Растёт при каждом сохранении", examples=[3])
    updated_at: datetime = Field(examples=["2026-11-19T12:00:00+03:00"])


class ResizeIn(BaseModel):
    width_mm: float = Field(gt=0, le=200, examples=[58])
    height_mm: float = Field(gt=0, le=200, examples=[40])


class OverflowItem(BaseModel):
    participant_id: int = Field(examples=[17])
    full_name: str = Field(examples=["Иванов Пётр Сергеевич"])
    field: str = Field(
        description="Поле шаблона, которое не поместилось", examples=["organization"]
    )
    value: str = Field(
        description="Значение поля, которое не поместилось",
        examples=["Общество с ограниченной ответственностью «Ромашка»"],
    )


class TemplateTestPrintIn(BaseModel):
    participant_id: int | None = Field(
        default=None, description="Чьими данными печатать; null — образцом", examples=[17]
    )
    printer_id: int = Field(examples=[1])


class TemplateSaveOut(TemplateOut):
    """Ответ на сохранение шаблона: сам шаблон и участники, которые в него не помещаются (PR-03)."""

    overflow: list[OverflowItem] = Field(
        description="Данные, которые не помещаются даже минимальным кеглем; пусто — всё влезает"
    )


class OverflowOut(BaseModel):
    """Ответ `GET .../overflow`: тот же список, что в `overflow` при сохранении."""

    items: list[OverflowItem]


TemplateFieldGroup = Literal["standard", "english", "extra", "special"]


class TemplateFieldOut(BaseModel):
    """Поле, которое можно поставить в элемент шаблона (`elements[].field`)."""

    key: str = Field(
        description="Значение для `elements[].field`; доп. поля — `extra.<ключ>`",
        examples=["last_name"],
    )
    label: str = Field(description="Название для выпадающего списка", examples=["Фамилия"])
    group: TemplateFieldGroup = Field(
        description=(
            "`standard` — стандартные поля участника, `english` — их английские версии "
            "(`_en`), `extra` — дополнительные поля конференции, `special` — `full_name`, "
            "`qr` и `text`"
        ),
        examples=["standard"],
    )
