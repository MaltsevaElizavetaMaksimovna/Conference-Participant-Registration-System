"""Действия на стойке: регистрация, повторная печать (B2-15, RG-05, RG-08, RG-09, DP-02),
чужой код (B2-14, QR-03), статус печати (B2-11, TR-08)."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import PrintJobRefOut, PrintJobStatus, err
from app.api.deps import staff
from app.auth.deps import CurrentStaff, get_current_staff
from app.core.db import get_session
from app.models.printing import PrintJob
from app.printing.queue import print_job_not_found
from app.registration.desk import register_at_desk, reprint_at_desk
from app.registration.foreign_code import register_foreign_code
from app.registration.schemas import PrintJobOut, RegisterIn, RegisterOut

router = APIRouter(tags=["desk"])


@router.post(
    "/participants/{participant_id}/register",
    operation_id="desk_register",
    summary="Зарегистрировать участника со стойки",
    description=(
        "Разрешение: `registration.desk` (+ `stickers.print` при печати). "
        "По умолчанию запрашивается наклейка. Без выбранного принтера регистрация "
        "сохраняется с пометкой об ошибке печати и `print_job_id=null`. "
        "Если участник уже зарегистрирован, `409 already_registered`; в `details` данные "
        "первой регистрации (`registered_at`, `source`, `terminal_name`, `user_login`)."
    ),
    response_model=RegisterOut,
    dependencies=staff("registration.desk", write=True),
    responses=err(
        401,
        403,
        (404, "`participant_not_found`"),
        422,
        (409, "`already_registered`: в `details` данные первой регистрации"),
    ),
)
async def desk_register(
    participant_id: int,
    request: Request,
    body: RegisterIn | None = None,
    session: AsyncSession = Depends(get_session),
    current: CurrentStaff = Depends(get_current_staff),
) -> RegisterOut:
    return await register_at_desk(
        session,
        participant_id,
        current,
        with_sticker=(body or RegisterIn()).with_sticker,
        settings=request.app.state.settings,
    )


@router.post(
    "/participants/{participant_id}/reprint",
    operation_id="desk_reprint",
    summary="Повторно напечатать наклейку",
    description=(
        "Разрешение: `stickers.print`. Только для зарегистрированных: иначе "
        "`409 not_registered`. QR на наклейке тот же (QR-01). "
        "Новый ключ на каждое нажатие. Повтор запроса сотрудника для того же участника "
        "с тем же ключом возвращает прежнее задание."
    ),
    response_model=PrintJobRefOut,
    dependencies=staff("stickers.print", write=True),
    responses=err(
        401,
        403,
        (404, "`participant_not_found`"),
        422,
        (409, "`not_registered`, `printer_not_selected`, `no_badge`"),
    ),
)
async def desk_reprint(
    participant_id: int,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ] = None,
    session: AsyncSession = Depends(get_session),
    current: CurrentStaff = Depends(get_current_staff),
) -> PrintJobRefOut:
    job_id = await reprint_at_desk(
        session, participant_id, current.user_id, idempotency_key=idempotency_key
    )
    return PrintJobRefOut(print_job_id=job_id)


@router.post(
    "/participants/{participant_id}/foreign-code",
    operation_id="desk_foreign_code",
    summary="Зарегистрировать по чужому коду",
    description=(
        "Разрешение: `registration.foreign_code`. Только для зарегистрированного участника "
        "активной конференции; **фронт обязан сначала спросить подтверждение**. Старая ссылка "
        "с наклейки аннулируется навсегда, выдаётся новый QR, на принтер, выбранный в панели, "
        "ставится наклейка (статус — `GET /api/print-jobs/{id}`). Пометка «Зарегистрирован по "
        "чужому коду» с временем и логином; время и место первой регистрации не меняются (QR-03). "
        "`409 participant_not_registered` — участник не зарегистрирован; "
        "`409 printer_not_selected` — в панели не выбран принтер; `409 no_badge` — конференция "
        "без бейджа (во всех этих случаях ничего не изменено)."
    ),
    response_model=PrintJobRefOut,
    dependencies=staff("registration.foreign_code", write=True),
    responses=err(
        401,
        403,
        (404, "`participant_not_found`"),
        (409, "`participant_not_registered`, `printer_not_selected`, `no_badge`"),
    ),
)
async def desk_foreign_code(
    participant_id: int,
    session: AsyncSession = Depends(get_session),
    current: CurrentStaff = Depends(get_current_staff),
) -> PrintJobRefOut:
    job_id = await register_foreign_code(session, participant_id, current.user_id)
    return PrintJobRefOut(print_job_id=job_id)


@router.get(
    "/print-jobs/{print_job_id}",
    operation_id="print_jobs_get",
    summary="Статус задания печати",
    description=(
        "Любой вошедший сотрудник. Статус задания: `pending → sent → done | error`; "
        "`error` — причина (`timeout`, `not_picked_up`, `template_not_set`, текст агента…)."
    ),
    response_model=PrintJobOut,
    dependencies=staff(),
    responses=err(401, (404, "`print_job_not_found`: задания нет")),
)
async def print_jobs_get(
    print_job_id: int, session: AsyncSession = Depends(get_session)
) -> PrintJobOut:
    job = await session.get(PrintJob, print_job_id)
    if job is None:
        raise print_job_not_found()
    return PrintJobOut(id=job.id, status=cast(PrintJobStatus, job.status), error=job.error)
