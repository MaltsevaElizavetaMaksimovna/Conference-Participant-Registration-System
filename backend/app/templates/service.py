"""Шаблоны наклеек (B2-07, PR-01, PR-04, ER-02): CRUD, копирование, защита от удаления."""

from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.conferences.service import conference_not_found
from app.core.errors import AppError
from app.models.conference import Conference, LabelTemplate
from app.templates.schemas import TemplateElement, TemplateIn, TemplateOut
from app.templates.validation import check_geometry, edge_warnings

# Поля конференции, через которые она использует шаблон
_BINDINGS = (
    Conference.front_template_id,
    Conference.back_template_id,
    Conference.changed_template_id,
    Conference.changed_back_template_id,
)


def template_not_found() -> AppError:
    return AppError("template_not_found", "Шаблон не найден", 404)


def _mm(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


def _db_values(body: TemplateIn) -> dict[str, Any]:
    return {
        "name": body.name,
        "kind": body.kind,
        "width_mm": _mm(body.width_mm),
        "height_mm": _mm(body.height_mm),
        "gap_mm": _mm(body.gap_mm),
        "elements": [el.model_dump(mode="json") for el in body.elements],
    }


def template_out(tpl: LabelTemplate, margin_mm: float) -> TemplateOut:
    elements = [TemplateElement.model_validate(el) for el in tpl.elements]
    width, height = float(tpl.width_mm), float(tpl.height_mm)
    return TemplateOut(
        id=tpl.id,
        conference_id=tpl.conference_id,
        name=tpl.name,
        kind=tpl.kind,  # type: ignore[arg-type]  # CHECK в БД гарантирует значение
        width_mm=width,
        height_mm=height,
        gap_mm=float(tpl.gap_mm),
        elements=elements,
        version=tpl.version,
        updated_at=tpl.updated_at,
        warnings=edge_warnings(width, height, elements, margin_mm),
    )


async def _require_conference(session: AsyncSession, conference_id: int) -> None:
    if await session.get(Conference, conference_id) is None:
        raise conference_not_found()


async def get_template(
    session: AsyncSession, conference_id: int, template_id: int
) -> LabelTemplate:
    tpl = await session.get(LabelTemplate, template_id)
    if tpl is None or tpl.conference_id != conference_id:
        await _require_conference(session, conference_id)
        raise template_not_found()
    return tpl


async def list_templates(
    session: AsyncSession, conference_id: int, limit: int, offset: int
) -> tuple[list[LabelTemplate], int]:
    await _require_conference(session, conference_id)
    where = LabelTemplate.conference_id == conference_id
    total = await session.scalar(select(func.count()).select_from(LabelTemplate).where(where))
    rows = await session.scalars(
        select(LabelTemplate).where(where).order_by(LabelTemplate.id).limit(limit).offset(offset)
    )
    return list(rows), total or 0


async def create_template(
    session: AsyncSession, conference_id: int, body: TemplateIn
) -> LabelTemplate:
    check_geometry(body)
    await _require_conference(session, conference_id)
    tpl = LabelTemplate(conference_id=conference_id, **_db_values(body))
    session.add(tpl)
    await session.commit()
    await session.refresh(tpl)
    return tpl


async def update_template(
    session: AsyncSession, conference_id: int, template_id: int, body: TemplateIn
) -> LabelTemplate:
    """Полная замена. `version` растёт на стороне БД: два одновременных PUT дают +2."""
    check_geometry(body)
    tpl = await get_template(session, conference_id, template_id)
    await session.execute(
        update(LabelTemplate)
        .where(LabelTemplate.id == tpl.id)
        .values(**_db_values(body), version=LabelTemplate.version + 1, updated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    await session.refresh(tpl)
    return tpl


async def _bound_conference(session: AsyncSession, template_id: int) -> int | None:
    return await session.scalar(
        select(Conference.id)
        .where(or_(*(col == template_id for col in _BINDINGS)))
        .order_by(Conference.id)
        .limit(1)
    )


def _in_use(conference_id: int) -> AppError:
    return AppError(
        "template_in_use",
        "Шаблон используется в конференции. Сначала отвяжите его",
        409,
        {"conference_id": conference_id},
    )


async def delete_template(session: AsyncSession, conference_id: int, template_id: int) -> None:
    tpl = await get_template(session, conference_id, template_id)
    if (bound := await _bound_conference(session, template_id)) is not None:
        raise _in_use(bound)
    await session.delete(tpl)
    try:
        await session.commit()
    except IntegrityError:  # шаблон успели привязать между проверкой и удалением
        await session.rollback()
        bound = await _bound_conference(session, template_id)
        raise _in_use(bound or conference_id) from None


async def copy_template(
    session: AsyncSession, conference_id: int, template_id: int, target_conference_id: int
) -> LabelTemplate:
    """Копия с теми же настройками в другой конференции (PR-01); версия копии — 1."""
    source = await get_template(session, conference_id, template_id)
    await _require_conference(session, target_conference_id)
    copy = LabelTemplate(
        conference_id=target_conference_id,
        name=source.name,
        kind=source.kind,
        width_mm=source.width_mm,
        height_mm=source.height_mm,
        gap_mm=source.gap_mm,
        elements=list(source.elements),
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)
    return copy
