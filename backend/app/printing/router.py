"""Принтеры и агент печати.

Админка принтеров, `GET /api/printers`, heartbeat агента (B2-01); очередь заданий агента
`jobs/next` (long-poll) и `jobs/{id}/result` (B2-11, логика — `queue.py`).
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Limit, Offset, Page, PrinterOut, err
from app.api.deps import agent, staff
from app.core.config import Settings
from app.core.db import get_session
from app.core.permissions import Permission
from app.models.device import Printer
from app.printing import queue, service
from app.printing.job_render import render_job
from app.printing.schemas import (
    AgentJob,
    AgentResultIn,
    HeartbeatIn,
    PrinterAdminOut,
    PrinterIn,
    PrinterTokenOut,
)
from app.terminals.deps import CurrentAgent, get_current_agent

printers_router = APIRouter(tags=["desk"])
admin_router = APIRouter(prefix="/admin/printers", tags=["admin: printers"])
agent_router = APIRouter(prefix="/agent", tags=["agent"])

Session = Annotated[AsyncSession, Depends(get_session)]

_INVALID_TOKEN = (401, "`invalid_device_token`: токен агента отсутствует или неверный")
_ADMIN = Permission.DEVICES_MANAGE


@printers_router.get(
    "/printers",
    operation_id="printers_list",
    summary="Принтеры для выбора в панели",
    description="Любой вошедший сотрудник (RG-05). `status`: `ready | offline | error | unknown`.",
    response_model=list[PrinterOut],
    dependencies=staff(),
    responses=err(401),
)
async def printers_list(session: Session) -> list[PrinterOut]:
    return [service.printer_out(p) for p in await service.list_printers(session)]


@admin_router.get(
    "",
    operation_id="admin_printers_list",
    summary="Принтеры (администрирование)",
    description="Разрешение: `devices.manage`.",
    response_model=Page[PrinterAdminOut],
    dependencies=staff(_ADMIN),
    responses=err(401, 403),
)
async def admin_printers_list(
    session: Session, limit: Limit = 50, offset: Offset = 0
) -> Page[PrinterAdminOut]:
    items, total = await service.list_printers_page(session, limit, offset)
    return Page[PrinterAdminOut](items=items, total=total)


@admin_router.post(
    "",
    operation_id="admin_printers_create",
    summary="Добавить принтер",
    description=(
        "Разрешение: `devices.manage`. Токен агента выдаётся отдельным запросом. "
        "Калибровка: `offset_x_mm`, `offset_y_mm` (±50 мм), `density` 0..15, `speed` 1..6."
    ),
    status_code=201,
    response_model=PrinterAdminOut,
    dependencies=staff(_ADMIN, write=True),
    responses=err(401, 403, 422, (409, "`name_taken`: принтер с таким именем уже есть")),
)
async def admin_printers_create(body: PrinterIn, session: Session) -> PrinterAdminOut:
    return await service.create_printer(session, body)


@admin_router.put(
    "/{printer_id}",
    operation_id="admin_printers_update",
    summary="Изменить принтер",
    description=(
        "Разрешение: `devices.manage`. Меняются только переданные поля (`name` обязателен), "
        "так что калибровка не сбрасывается."
    ),
    response_model=PrinterAdminOut,
    dependencies=staff(_ADMIN, write=True),
    responses=err(
        401,
        403,
        (404, "`printer_not_found`: принтера нет"),
        422,
        (409, "`name_taken`: принтер с таким именем уже есть"),
    ),
)
async def admin_printers_update(
    printer_id: int, body: PrinterIn, session: Session
) -> PrinterAdminOut:
    return await service.update_printer(session, printer_id, body)


@admin_router.post(
    "/{printer_id}/token",
    operation_id="admin_printers_token",
    summary="Выдать новый токен агента",
    description=(
        "Разрешение: `devices.manage`. Токен показывается **один раз** (в базе только его "
        "хэш); предыдущий перестаёт работать."
    ),
    response_model=PrinterTokenOut,
    dependencies=staff(_ADMIN, write=True),
    responses=err(401, 403, (404, "`printer_not_found`: принтера нет")),
)
async def admin_printers_token(printer_id: int, session: Session) -> PrinterTokenOut:
    return await service.issue_agent_token(session, printer_id)


@agent_router.get(
    "/jobs/next",
    operation_id="agent_jobs_next",
    summary="Получить следующее задание печати (long-poll)",
    description=(
        "`Authorization: Agent <token>`. Держит запрос до `wait` секунд и отдаёт самое старое "
        "задание своего принтера; если заданий нет — `204 No Content`, и агент сразу "
        "спрашивает снова. Наклейки рисуются в момент выдачи по текущему шаблону; в ответе "
        "калибровка принтера (`offset_x_mm`, `offset_y_mm`, `density`, `speed`). Задание "
        "выдаётся один раз: на него нужно ответить `POST …/result` за "
        "`RS_PRINT_CONFIRM_TIMEOUT_S` (30 с), иначе оно станет `error`. Задания старше "
        "`RS_PRINT_PENDING_TIMEOUT_S` (30 с) не выдаются: они уже помечены ошибкой."
    ),
    response_model=AgentJob,
    responses={
        204: {"description": "За `wait` секунд заданий не появилось"},
        **err(_INVALID_TOKEN),
    },
    dependencies=agent(),
)
async def agent_jobs_next(
    request: Request,
    session: Session,
    current: CurrentAgent = Depends(get_current_agent),
    wait: Annotated[
        int, Query(ge=0, le=60, description="Сколько секунд ждать задание (long-poll)")
    ] = 25,
) -> AgentJob | Response:
    settings: Settings = request.app.state.settings
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    await queue.expire_stale(session, settings, current.printer_id)
    while True:
        # populate_existing: после rollback внутри claim_next объект принтера истёк
        printer = await session.get(Printer, current.printer_id, populate_existing=True)
        if printer is None:  # принтер удалили, пока агент ждал
            return Response(status_code=204)
        job = await queue.claim_next(session, settings, printer, render_job)
        if job is not None:
            return job
        remaining = deadline - loop.time()
        if remaining <= 0 or await request.is_disconnected():
            return Response(status_code=204)
        await asyncio.sleep(min(settings.print_poll_interval_s, remaining))


@agent_router.post(
    "/jobs/{job_id}/result",
    operation_id="agent_job_result",
    summary="Сообщить результат печати",
    description=(
        "`Authorization: Agent <token>`. `ok=true` — задание `done` (счётчик печатей "
        "участника +1, пометка «Наклейка не напечатана» снимается); `ok=false` — `error` с "
        "причиной `error` (пометка ставится, TR-08). Повтор того же ответа ничего не меняет "
        "(`204`). Поздний `ok=true` после просрочки засчитывается. `404 print_job_not_found` — "
        "задания нет или оно другого принтера; `409 print_job_not_sent` — задание ещё не "
        "выдавалось агенту."
    ),
    status_code=204,
    response_class=Response,
    dependencies=agent(),
    responses=err(
        _INVALID_TOKEN,
        (404, "`print_job_not_found`: задания нет или оно другого принтера"),
        (409, "`print_job_not_sent`: задание ещё не выдавалось агенту"),
        422,
    ),
)
async def agent_job_result(
    job_id: int,
    body: AgentResultIn,
    session: Session,
    current: CurrentAgent = Depends(get_current_agent),
) -> Response:
    await queue.finish_job(session, current.printer_id, job_id, body.ok, body.error)
    return Response(status_code=204)


@agent_router.post(
    "/heartbeat",
    operation_id="agent_heartbeat",
    summary="Heartbeat агента и состояние принтера",
    description=(
        "`Authorization: Agent <token>`. Раз в несколько секунд: обновляет статус принтера "
        "(`ready | offline | error | unknown`) и время последней связи. Терминал считает "
        "принтер «на связи», если heartbeat со статусом `ready` пришёл не позже 30 с назад."
    ),
    status_code=204,
    response_class=Response,
    dependencies=agent(),
    responses=err(_INVALID_TOKEN, 422),
)
async def agent_heartbeat(
    body: HeartbeatIn,
    session: Session,
    current: CurrentAgent = Depends(get_current_agent),
) -> None:
    await service.record_heartbeat(session, current.printer_id, body.printer_status)


router = APIRouter()
router.include_router(printers_router)
router.include_router(admin_router)
router.include_router(agent_router)
