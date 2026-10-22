"""Шаблоны наклеек (PR-01..PR-05). ЗАГЛУШКИ (B2-06, B2-07)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import STUB_TAG, Limit, Offset, Page, PrintJobRefOut, err
from app.api.deps import staff
from app.api.stubs import PNG_1X1, T0
from app.core.db import get_session
from app.core.errors import AppError
from app.templates import fields
from app.templates.schemas import (
    OverflowItem,
    OverflowOut,
    ResizeIn,
    TemplateElement,
    TemplateFieldOut,
    TemplateIn,
    TemplateOut,
    TemplateSaveOut,
    TemplateTestPrintIn,
)

router = APIRouter(prefix="/admin/conferences", tags=["admin: templates", STUB_TAG])
# Реальные эндпоинты модуля (без тега `stub`)
fields_router = APIRouter(prefix="/admin/conferences", tags=["admin: templates"])

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


@router.get(
    _BASE,
    operation_id="templates_list",
    summary="Шаблоны конференции",
    description="Разрешение: `conferences.manage`.",
    response_model=Page[TemplateOut],
    dependencies=staff(_PERM),
    responses=err(401, 403, 404),
)
async def templates_list(
    conference_id: int, limit: Limit = 50, offset: Offset = 0
) -> Page[TemplateOut]:
    items = [_template(conference_id, 1), _template(conference_id, 2)]
    return Page[TemplateOut](items=items[offset : offset + limit], total=len(items))


@router.post(
    _BASE,
    operation_id="templates_create",
    summary="Создать шаблон",
    description="Разрешение: `conferences.manage`.",
    status_code=201,
    response_model=TemplateOut,
    dependencies=staff(_PERM, write=True),
    responses=err(401, 403, 404, 422),
)
async def templates_create(conference_id: int, body: TemplateIn) -> TemplateOut:
    return TemplateOut(
        **body.model_dump(), id=3, conference_id=conference_id, version=1, updated_at=T0
    )


@router.get(
    _BASE + "/{template_id}",
    operation_id="templates_get",
    summary="Шаблон",
    description="Разрешение: `conferences.manage`.",
    response_model=TemplateOut,
    dependencies=staff(_PERM),
    responses=err(401, 403, 404),
)
async def templates_get(conference_id: int, template_id: int) -> TemplateOut:
    return _template(conference_id, template_id)


@router.put(
    _BASE + "/{template_id}",
    operation_id="templates_update",
    summary="Сохранить шаблон",
    description=(
        "Разрешение: `conferences.manage`. Полная замена; `version` растёт. В ответе поля "
        "шаблона и `overflow` — участники, которые не помещаются даже минимальным кеглем "
        "(PR-03); тот же список отдаёт `GET .../overflow`. Заглушка всегда возвращает "
        "один пример."
    ),
    response_model=TemplateSaveOut,
    dependencies=staff(_PERM, write=True),
    responses=err(401, 403, 404, 422),
)
async def templates_update(
    conference_id: int, template_id: int, body: TemplateIn
) -> TemplateSaveOut:
    return TemplateSaveOut(
        **body.model_dump(),
        id=template_id,
        conference_id=conference_id,
        version=4,
        updated_at=T0,
        overflow=_overflow(),
    )


@router.delete(
    _BASE + "/{template_id}",
    operation_id="templates_delete",
    summary="Удалить шаблон",
    description=(
        "Разрешение: `conferences.manage`. Шаблон, привязанный к конференции (`front_template_id` "
        "и др.), удалить нельзя: `409 template_in_use`, сначала отвяжите его. "
        "Заглушка: шаблон 1 «привязан» (409), остальные удаляются (204)."
    ),
    status_code=204,
    response_class=Response,
    dependencies=staff(_PERM, write=True),
    responses=err(
        401,
        403,
        404,
        (409, "`template_in_use`: шаблон привязан к конференции, сначала отвяжите его"),
    ),
)
async def templates_delete(conference_id: int, template_id: int) -> Response:
    if template_id == 1:
        raise AppError(
            "template_in_use",
            "Шаблон используется в конференции. Сначала отвяжите его",
            409,
            {"conference_id": conference_id},
        )
    return Response(status_code=204)


@router.post(
    _BASE + "/{template_id}/copy-to/{target_conference_id}",
    operation_id="templates_copy_to",
    summary="Скопировать шаблон в другую конференцию",
    description="Разрешение: `conferences.manage`. Возвращает созданную копию (PR-01).",
    status_code=201,
    response_model=TemplateOut,
    dependencies=staff(_PERM, write=True),
    responses=err(401, 403, 404),
)
async def templates_copy_to(
    conference_id: int, template_id: int, target_conference_id: int
) -> TemplateOut:
    return _template(conference_id, template_id).model_copy(
        update={"id": 10, "conference_id": target_conference_id, "version": 1}
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


@fields_router.get(
    "/{conference_id}/template-fields",
    operation_id="templates_fields",
    summary="Поля, доступные в шаблоне",
    description=(
        "Разрешение: `conferences.manage`. Что можно поставить в `elements[].field`: "
        "стандартные поля участника (`standard`), их английские версии (`english`), "
        "дополнительные поля конференции из загруженного файла (`extra`, ключ "
        "`extra.<ключ>`) и особые значения (`special`: `full_name`, `qr`, `text`). "
        "Порядок: standard, english, extra, special."
    ),
    response_model=list[TemplateFieldOut],
    dependencies=staff(_PERM),
    responses=err(401, 403, (404, "`conference_not_found`: конференции нет")),
)
async def templates_fields(
    conference_id: int, session: AsyncSession = Depends(get_session)
) -> list[TemplateFieldOut]:
    return await fields.list_template_fields(session, conference_id)
