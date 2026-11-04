"""Действия на стойке: регистрация, повторная печать, чужой код (заглушки B2-04, B2-10),
статус печати (B2-11, TR-08)."""

from enum import Enum
from typing import cast

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import STUB_TAG, PrintJobRefOut, PrintJobStatus, err
from app.api.deps import staff
from app.api.stubs import T0
from app.core.db import get_session
from app.core.errors import AppError
from app.models.printing import PrintJob
from app.participants.router import REGISTERED_AT_TEXT, sample_card
from app.participants.schemas import RegistrationInfo
from app.printing.queue import print_job_not_found
from app.registration.schemas import PrintJobOut, RegisterIn, RegisterOut

router = APIRouter(tags=["desk"])
_STUB: list[str | Enum] = [STUB_TAG]


@router.post(
    "/participants/{participant_id}/register",
    operation_id="desk_register",
    summary="Зарегистрировать участника со стойки",
    description=(
        "Разрешение: `registration.desk` (+ `stickers.print` при `with_sticker=true`). "
        "Если участник уже зарегистрирован, `409 already_registered`; в `details` данные "
        "первой регистрации (`registered_at`, `source`, `terminal_name`, `user_login`). "
        "Заглушка: участник 17 уже зарегистрирован, 18 и 19 регистрируются, остальные — 404."
    ),
    response_model=RegisterOut,
    tags=_STUB,
    dependencies=staff("registration.desk", write=True),
    responses=err(
        401,
        403,
        404,
        422,
        (409, "`already_registered`: в `details` данные первой регистрации"),
    ),
)
async def desk_register(participant_id: int, body: RegisterIn | None = None) -> RegisterOut:
    body = body or RegisterIn()
    card = sample_card(participant_id)
    if participant_id == 17:
        raise AppError(
            "already_registered",
            f"Участник уже зарегистрирован {REGISTERED_AT_TEXT}",
            409,
            {
                "registered_at": T0.isoformat(),
                "source": "terminal",
                "terminal_name": "Терминал 2",
                "user_login": None,
            },
        )
    status = "registered" if body.with_sticker else "registered_no_sticker"
    card = card.model_copy(
        update={
            "status": status,
            "registration": RegistrationInfo(
                at=T0, source="desk", terminal_name=None, user_login="reg1"
            ),
        }
    )
    return RegisterOut(participant=card, print_job_id=501 if body.with_sticker else None)


@router.post(
    "/participants/{participant_id}/reprint",
    operation_id="desk_reprint",
    summary="Повторно напечатать наклейку",
    description=(
        "Разрешение: `stickers.print`. Только для зарегистрированных: иначе "
        "`409 not_registered`. QR на наклейке тот же (QR-01). Заглушка: участник 18 не "
        "зарегистрирован."
    ),
    response_model=PrintJobRefOut,
    tags=_STUB,
    dependencies=staff("stickers.print", write=True),
    responses=err(401, 403, 404, (409, "`not_registered`: участник не зарегистрирован")),
)
async def desk_reprint(participant_id: int) -> PrintJobRefOut:
    card = sample_card(participant_id)
    if card.status == "not_registered":
        raise AppError("not_registered", "Участник ещё не зарегистрирован", 409)
    return PrintJobRefOut(print_job_id=502)


@router.post(
    "/participants/{participant_id}/foreign-code",
    operation_id="desk_foreign_code",
    summary="Зарегистрировать по чужому коду",
    description=(
        "Разрешение: `registration.foreign_code`. Ставит пометку «Зарегистрирован по чужому "
        "коду» и печатает новую наклейку с новым QR (QR-03). **Фронт обязан сначала "
        "спросить подтверждение у регистратора.**"
    ),
    response_model=PrintJobRefOut,
    tags=_STUB,
    dependencies=staff("registration.foreign_code", write=True),
    responses=err(401, 403, 404),
)
async def desk_foreign_code(participant_id: int) -> PrintJobRefOut:
    sample_card(participant_id)
    return PrintJobRefOut(print_job_id=503)


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
