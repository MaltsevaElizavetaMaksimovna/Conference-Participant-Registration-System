"""Заглушки шаблонов: подгонка (B2-10), предпросмотр, overflow, пробная печать (B2-09)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.common import STUB_TAG, PrintJobRefOut, err
from app.api.deps import staff
from app.api.stubs import PNG_1X1, T0
from app.templates.schemas import (
    OverflowItem,
    OverflowOut,
    ResizeIn,
    TemplateElement,
    TemplateOut,
    TemplateTestPrintIn,
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


def _overflow() -> list[OverflowItem]:
    return [
        OverflowItem(
            participant_id=17,
            full_name="Иванов Пётр Сергеевич",
            field="organization",
            value="Общество с ограниченной ответственностью «Ромашка»",
        )
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


@router.get(
    _BASE + "/{template_id}/preview.png",
    operation_id="templates_preview",
    summary="Предпросмотр шаблона",
    description=(
        "Разрешение: `conferences.manage`. PNG с данными участника `participant_id` или "
        "образцом. Заглушка отдаёт пиксель 1×1."
    ),
    response_class=Response,
    responses={
        200: {
            "description": "Предпросмотр наклейки",
            "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
        },
        **err(401, 403, 404),
    },
    dependencies=staff(_PERM),
)
async def templates_preview(
    conference_id: int,
    template_id: int,
    participant_id: Annotated[
        int | None, Query(description="Чьими данными рисовать; без него — образец")
    ] = None,
) -> Response:
    return Response(content=PNG_1X1, media_type="image/png")


@router.get(
    _BASE + "/{template_id}/overflow",
    operation_id="templates_overflow",
    summary="Участники, которые не помещаются в шаблон",
    description=(
        "Разрешение: `conferences.manage`. Данные не помещаются даже минимальным кеглем (PR-03)."
    ),
    response_model=OverflowOut,
    dependencies=staff(_PERM),
    responses=err(401, 403, 404),
)
async def templates_overflow(conference_id: int, template_id: int) -> OverflowOut:
    return OverflowOut(items=_overflow())


@router.post(
    _BASE + "/{template_id}/test-print",
    operation_id="templates_test_print",
    summary="Пробная печать шаблона",
    description=(
        "Разрешение: `conferences.manage`. Пробная печать без регистрации участника (PR-02). "
        "Статус — `GET /api/print-jobs/{id}`."
    ),
    response_model=PrintJobRefOut,
    dependencies=staff(_PERM, write=True),
    responses=err(401, 403, 404, 422),
)
async def templates_test_print(
    conference_id: int, template_id: int, body: TemplateTestPrintIn
) -> PrintJobRefOut:
    return PrintJobRefOut(print_job_id=504)
