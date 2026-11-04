"""Предпросмотр, переполнение и пробная печать шаблона (B2-09, PR-02, PR-03)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import PrintJobRefOut, err
from app.api.deps import staff
from app.auth.deps import CurrentStaff, get_current_staff
from app.core.config import Settings
from app.core.db import get_session
from app.templates import preview
from app.templates.schemas import OverflowOut, TemplateTestPrintIn

router = APIRouter()

_PERM = "conferences.manage"
_BASE = "/{conference_id}/templates/{template_id}"
_TPL_404 = (404, "`conference_not_found`: конференции нет; `template_not_found`: шаблона нет")


@router.get(
    _BASE + "/preview.png",
    operation_id="templates_preview",
    summary="Предпросмотр шаблона",
    description=(
        "Разрешение: `conferences.manage`. 1-битный PNG 203 dpi — ровно то, что уйдёт на "
        "принтер: данные участника `participant_id` (любого участника конференции) или "
        "образец. QR — действующий код участника; если участник ещё не зарегистрирован, "
        "образец (предпросмотр код не выдаёт). Участника нет в этой конференции — "
        "`404 participant_not_found`."
    ),
    response_class=Response,
    responses={
        200: {
            "description": "Предпросмотр наклейки",
            "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
        },
        **err(
            401,
            403,
            (404, "`conference_not_found`, `template_not_found`, `participant_not_found`"),
            422,
        ),
    },
    dependencies=staff(_PERM),
)
async def templates_preview(
    request: Request,
    conference_id: int,
    template_id: int,
    participant_id: Annotated[
        int | None, Query(description="Чьими данными рисовать; без него — образец")
    ] = None,
    session: AsyncSession = Depends(get_session),
) -> Response:
    settings: Settings = request.app.state.settings
    png = await preview.preview_png(session, settings, conference_id, template_id, participant_id)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get(
    _BASE + "/overflow",
    operation_id="templates_overflow",
    summary="Участники, которые не помещаются в шаблон",
    description=(
        "Разрешение: `conferences.manage`. Данные участников конференции, которые не "
        "помещаются в поле даже минимальным кеглем с учётом `max_lines` (PR-03), по алфавиту. "
        "Тот же список приходит в `overflow` при сохранении шаблона. Постоянный текст не "
        "проверяется."
    ),
    response_model=OverflowOut,
    dependencies=staff(_PERM),
    responses=err(401, 403, _TPL_404),
)
async def templates_overflow(
    conference_id: int, template_id: int, session: AsyncSession = Depends(get_session)
) -> OverflowOut:
    return OverflowOut(items=await preview.template_overflow(session, conference_id, template_id))


@router.post(
    _BASE + "/test-print",
    operation_id="templates_test_print",
    summary="Пробная печать шаблона",
    description=(
        "Разрешение: `conferences.manage`. Пробная печать по этому шаблону (PR-02): данными "
        "участника `participant_id` или образцом (`null`). Участника не регистрирует и его "
        "статус не меняет. Статус задания — `GET /api/print-jobs/{id}`. "
        "`404 participant_not_found` — участника нет в этой конференции; "
        "`404 printer_not_found` — принтера нет."
    ),
    response_model=PrintJobRefOut,
    dependencies=staff(_PERM, write=True),
    responses=err(
        401,
        403,
        (
            404,
            "`conference_not_found`, `template_not_found`, `participant_not_found`, "
            "`printer_not_found`",
        ),
        422,
    ),
)
async def templates_test_print(
    conference_id: int,
    template_id: int,
    body: TemplateTestPrintIn,
    current: CurrentStaff = Depends(get_current_staff),
    session: AsyncSession = Depends(get_session),
) -> PrintJobRefOut:
    job_id = await preview.create_test_print(
        session, conference_id, template_id, body, current.user_id
    )
    return PrintJobRefOut(print_job_id=job_id)
