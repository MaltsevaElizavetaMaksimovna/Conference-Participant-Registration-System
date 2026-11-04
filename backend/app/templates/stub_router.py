"""Заглушка шаблонов: подгонка под ленту (B2-10)."""

from fastapi import APIRouter

from app.api.common import STUB_TAG, err
from app.api.deps import staff
from app.api.stubs import T0
from app.templates.schemas import (
    ResizeIn,
    TemplateElement,
    TemplateOut,
)

router = APIRouter(prefix="/admin/conferences", tags=["admin: templates", STUB_TAG])

_PERM = "conferences.manage"
_BASE = "/{conference_id}/templates"


def _elements() -> list[TemplateElement]:
    return [
        TemplateElement(
            type="field",
            field="last_name",
            x_mm=3,
            y_mm=3,
            w_mm=54,
            h_mm=10,
            font_size=14,
            min_font_size=8,
            max_lines=2,
            align="left",
            bold=True,
        ),
        TemplateElement(
            type="field",
            field="organization",
            x_mm=3,
            y_mm=15,
            w_mm=54,
            h_mm=8,
            font_size=10,
            min_font_size=7,
            max_lines=2,
        ),
        TemplateElement(type="qr", x_mm=40, y_mm=24, w_mm=15, h_mm=15),
    ]


def _template(conference_id: int, template_id: int) -> TemplateOut:
    return TemplateOut(
        id=template_id,
        conference_id=conference_id,
        name="Лицевая сторона" if template_id == 1 else f"Шаблон {template_id}",
        kind="front",
        width_mm=60,
        height_mm=40,
        gap_mm=2,
        elements=_elements(),
        version=3,
        updated_at=T0,
    )


@router.post(
    _BASE + "/{template_id}/resize",
    operation_id="templates_resize",
    summary="Изменить размер наклейки",
    description=(
        "Разрешение: `conferences.manage`. Меняет размер и пропорционально пересчитывает "
        "элементы (PR-05). Возвращает обновлённый шаблон."
    ),
    response_model=TemplateOut,
    dependencies=staff(_PERM, write=True),
    responses=err(401, 403, 404, 422),
)
async def templates_resize(conference_id: int, template_id: int, body: ResizeIn) -> TemplateOut:
    return _template(conference_id, template_id).model_copy(
        update={"width_mm": body.width_mm, "height_mm": body.height_mm, "version": 4}
    )
