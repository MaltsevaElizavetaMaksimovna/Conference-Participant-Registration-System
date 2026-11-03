"""Шаблоны наклеек (PR-01, PR-04, ER-02): поля шаблона, CRUD и копирование (B2-07)."""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Limit, Offset, Page, err
from app.api.deps import staff
from app.core.config import Settings
from app.core.db import get_session
from app.templates import fields, service, stub_router
from app.templates.schemas import TemplateFieldOut, TemplateIn, TemplateOut, TemplateSaveOut

# Заглушки (тег `stub`) — в stub_router.py; `router` оставлен здесь для app.main
router = stub_router.router
# Реальные эндпоинты модуля (без тега `stub`)
fields_router = APIRouter(prefix="/admin/conferences", tags=["admin: templates"])

_PERM = "conferences.manage"
_BASE = "/{conference_id}/templates"


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


_TPL_404 = (404, "`conference_not_found`: конференции нет; `template_not_found`: шаблона нет")
_KINDS = (
    "Виды: `front`/`back` — лицевая и оборотная сторона (PR-04), `changed`/`changed_back` — "
    "для участников с пометкой «Данные изменены» (ER-02). Элементы — в мм от левого верхнего "
    "угла, целиком внутри наклейки, иначе `422`, ключ ошибки `elements.<индекс>`. Элемент "
    "ближе `RS_TEMPLATE_SAFE_MARGIN_MM` (3 мм) к краю — предупреждение в `warnings`, "
    "сохранение проходит."
)


def _margin(request: Request) -> float:
    settings: Settings = request.app.state.settings
    return settings.template_safe_margin_mm


@fields_router.get(
    _BASE,
    operation_id="templates_list",
    summary="Шаблоны конференции",
    description="Разрешение: `conferences.manage`. По возрастанию `id`.",
    response_model=Page[TemplateOut],
    dependencies=staff(_PERM),
    responses=err(401, 403, (404, "`conference_not_found`: конференции нет")),
)
async def templates_list(
    request: Request,
    conference_id: int,
    limit: Limit = 50,
    offset: Offset = 0,
    session: AsyncSession = Depends(get_session),
) -> Page[TemplateOut]:
    rows, total = await service.list_templates(session, conference_id, limit, offset)
    margin = _margin(request)
    return Page[TemplateOut](items=[service.template_out(t, margin) for t in rows], total=total)


@fields_router.post(
    _BASE,
    operation_id="templates_create",
    summary="Создать шаблон",
    description="Разрешение: `conferences.manage`. " + _KINDS,
    status_code=201,
    response_model=TemplateOut,
    dependencies=staff(_PERM, write=True),
    responses=err(401, 403, (404, "`conference_not_found`: конференции нет"), 422),
)
async def templates_create(
    request: Request,
    conference_id: int,
    body: TemplateIn,
    session: AsyncSession = Depends(get_session),
) -> TemplateOut:
    tpl = await service.create_template(session, conference_id, body)
    return service.template_out(tpl, _margin(request))


@fields_router.get(
    _BASE + "/{template_id}",
    operation_id="templates_get",
    summary="Шаблон",
    description="Разрешение: `conferences.manage`.",
    response_model=TemplateOut,
    dependencies=staff(_PERM),
    responses=err(401, 403, _TPL_404),
)
async def templates_get(
    request: Request,
    conference_id: int,
    template_id: int,
    session: AsyncSession = Depends(get_session),
) -> TemplateOut:
    tpl = await service.get_template(session, conference_id, template_id)
    return service.template_out(tpl, _margin(request))


@fields_router.put(
    _BASE + "/{template_id}",
    operation_id="templates_update",
    summary="Сохранить шаблон",
    description=(
        "Разрешение: `conferences.manage`. Полная замена; `version` растёт, изменения "
        "применяются со следующей печати. В ответе поля шаблона и `overflow` — участники, "
        "которые не помещаются даже минимальным кеглем (PR-03); тот же список отдаёт "
        "`GET .../overflow`. Пока расчёт не готов (B2-09), `overflow` пустой. " + _KINDS
    ),
    response_model=TemplateSaveOut,
    dependencies=staff(_PERM, write=True),
    responses=err(401, 403, _TPL_404, 422),
)
async def templates_update(
    request: Request,
    conference_id: int,
    template_id: int,
    body: TemplateIn,
    session: AsyncSession = Depends(get_session),
) -> TemplateSaveOut:
    tpl = await service.update_template(session, conference_id, template_id, body)
    out = service.template_out(tpl, _margin(request))
    return TemplateSaveOut(**out.model_dump(), overflow=[])


@fields_router.delete(
    _BASE + "/{template_id}",
    operation_id="templates_delete",
    summary="Удалить шаблон",
    description=(
        "Разрешение: `conferences.manage`. Шаблон, привязанный к конференции (`front_template_id` "
        "и др.), удалить нельзя: `409 template_in_use`, `details.conference_id`; сначала "
        "отвяжите его."
    ),
    status_code=204,
    response_class=Response,
    dependencies=staff(_PERM, write=True),
    responses=err(
        401,
        403,
        _TPL_404,
        (409, "`template_in_use`: шаблон привязан к конференции, сначала отвяжите его"),
    ),
)
async def templates_delete(
    conference_id: int, template_id: int, session: AsyncSession = Depends(get_session)
) -> Response:
    await service.delete_template(session, conference_id, template_id)
    return Response(status_code=204)


@fields_router.post(
    _BASE + "/{template_id}/copy-to/{target_conference_id}",
    operation_id="templates_copy_to",
    summary="Скопировать шаблон в другую конференцию",
    description=(
        "Разрешение: `conferences.manage`. Копия с теми же настройками и `version = 1` в "
        "конференции `target_conference_id` (PR-01). Нет целевой конференции — "
        "`404 conference_not_found`."
    ),
    status_code=201,
    response_model=TemplateOut,
    dependencies=staff(_PERM, write=True),
    responses=err(401, 403, _TPL_404),
)
async def templates_copy_to(
    request: Request,
    conference_id: int,
    template_id: int,
    target_conference_id: int,
    session: AsyncSession = Depends(get_session),
) -> TemplateOut:
    copy = await service.copy_template(session, conference_id, template_id, target_conference_id)
    return service.template_out(copy, _margin(request))
