"""Поля, доступные в элементах шаблона конференции (PR-01, PR-04)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conferences.service import conference_not_found
from app.imports.columns import FIELD_BY_KEY
from app.models.conference import Conference, ExtraFieldDef
from app.templates.schemas import STANDARD_KEYS, TemplateFieldOut

# Не поля участника, а особые значения шаблона. `qr` и `text` совпадают с `elements[].type`.
SPECIAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("full_name", "ФИО полностью"),
    ("qr", "QR-код"),
    ("text", "Постоянный текст"),
)


def standard_fields() -> list[TemplateFieldOut]:
    return [
        TemplateFieldOut(key=key, label=FIELD_BY_KEY[key].title, group="standard")
        for key in STANDARD_KEYS
    ]


def english_fields() -> list[TemplateFieldOut]:
    return [
        TemplateFieldOut(key=f"{key}_en", label=FIELD_BY_KEY[f"{key}_en"].title, group="english")
        for key in STANDARD_KEYS
    ]


def special_fields() -> list[TemplateFieldOut]:
    return [TemplateFieldOut(key=k, label=label, group="special") for k, label in SPECIAL_FIELDS]


async def list_template_fields(session: AsyncSession, conference_id: int) -> list[TemplateFieldOut]:
    """Стандартные, английские, дополнительные (из `extra_field_def`) и специальные поля."""
    if await session.get(Conference, conference_id) is None:
        raise conference_not_found()
    extra = await session.scalars(
        select(ExtraFieldDef)
        .where(ExtraFieldDef.conference_id == conference_id)
        .order_by(ExtraFieldDef.sort_order, ExtraFieldDef.id)
    )
    return [
        *standard_fields(),
        *english_fields(),
        *(TemplateFieldOut(key=f"extra.{d.key}", label=d.label, group="extra") for d in extra),
        *special_fields(),
    ]
