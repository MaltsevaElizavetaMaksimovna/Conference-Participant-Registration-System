"""Принтеры и агент печати. ЗАГЛУШКИ (B2-02, B2-09, B2-11)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.common import STUB_TAG, Limit, Offset, Page, PrinterOut, err
from app.api.deps import agent, staff
from app.api.stubs import PNG_1X1_B64, T0
from app.printing.schemas import (
    AgentJob,
    AgentJobCopy,
    AgentResultIn,
    HeartbeatIn,
    PrinterAdminOut,
    PrinterIn,
    PrinterTokenOut,
)

printers_router = APIRouter(tags=["desk", STUB_TAG])
admin_router = APIRouter(prefix="/admin/printers", tags=["admin: printers", STUB_TAG])
agent_router = APIRouter(prefix="/agent", tags=["agent", STUB_TAG])


def _printer(printer_id: int) -> PrinterAdminOut:
    return PrinterAdminOut(
        id=printer_id,
        name=f"Принтер {printer_id}",
        status="online",
        last_seen_at=T0,
        windows_printer_name="XP-360B",
        dpi=203,
        token_set=True,
    )


@printers_router.get(
    "/printers",
    operation_id="printers_list",
    summary="Принтеры для выбора в панели",
    description="Любой вошедший сотрудник (RG-05).",
    response_model=list[PrinterOut],
    dependencies=staff(),
    responses=err(401),
)
async def printers_list() -> list[PrinterOut]:
    return [
        PrinterOut(id=1, name="Принтер 1", status="online", last_seen_at=T0),
        PrinterOut(id=2, name="Принтер 2", status="offline", last_seen_at=T0.replace(hour=8)),
        PrinterOut(id=3, name="Принтер 3", status="unknown", last_seen_at=None),
    ]


@admin_router.get(
    "",
    operation_id="admin_printers_list",
    summary="Принтеры (администрирование)",
    description="Разрешение: `devices.manage`.",
    response_model=Page[PrinterAdminOut],
    dependencies=staff("devices.manage"),
    responses=err(401, 403),
)
async def admin_printers_list(limit: Limit = 50, offset: Offset = 0) -> Page[PrinterAdminOut]:
    items = [_printer(1), _printer(2)]
    return Page[PrinterAdminOut](items=items[offset : offset + limit], total=len(items))


@admin_router.post(
    "",
    operation_id="admin_printers_create",
    summary="Добавить принтер",
    description="Разрешение: `devices.manage`. Токен агента выдаётся отдельным запросом.",
    status_code=201,
    response_model=PrinterAdminOut,
    dependencies=staff("devices.manage", write=True),
    responses=err(401, 403, 422, (409, "`name_taken`: принтер с таким именем уже есть")),
)
async def admin_printers_create(body: PrinterIn) -> PrinterAdminOut:
    return _printer(3).model_copy(
        update={
            "name": body.name,
            "windows_printer_name": body.windows_printer_name,
            "dpi": body.dpi,
            "status": "unknown",
            "last_seen_at": None,
            "token_set": False,
        }
    )


@admin_router.put(
    "/{printer_id}",
    operation_id="admin_printers_update",
    summary="Изменить принтер",
    description="Разрешение: `devices.manage`.",
    response_model=PrinterAdminOut,
    dependencies=staff("devices.manage", write=True),
    responses=err(401, 403, 404, 422),
)
async def admin_printers_update(printer_id: int, body: PrinterIn) -> PrinterAdminOut:
    return _printer(printer_id).model_copy(
        update={
            "name": body.name,
            "windows_printer_name": body.windows_printer_name,
            "dpi": body.dpi,
        }
    )


@admin_router.post(
    "/{printer_id}/token",
    operation_id="admin_printers_token",
    summary="Выдать новый токен агента",
    description=(
        "Разрешение: `devices.manage`. Токен показывается **один раз**; предыдущий перестаёт "
        "работать."
    ),
    response_model=PrinterTokenOut,
    dependencies=staff("devices.manage", write=True),
    responses=err(401, 403, 404),
)
async def admin_printers_token(printer_id: int) -> PrinterTokenOut:
    return PrinterTokenOut(id=printer_id, token="agt_Zk3x9QnS7Vb2LmT4Zk3x9QnS7Vb2LmT4")


@agent_router.get(
    "/jobs/next",
    operation_id="agent_jobs_next",
    summary="Получить следующее задание печати (long-poll)",
    description=(
        "`Authorization: Agent <token>`. Держит запрос до `wait` секунд; если заданий нет, "
        "`204 No Content`, и агент делает запрос снова. **Заглушка** сразу отвечает заданием "
        "из двух наклеек, а при `wait=0` — `204`."
    ),
    response_model=AgentJob,
    responses={
        204: {"description": "За `wait` секунд заданий не появилось"},
        **err((401, "`unauthenticated`: неверный токен агента")),
    },
    dependencies=agent(),
)
async def agent_jobs_next(
    wait: Annotated[
        int, Query(ge=0, le=60, description="Сколько секунд ждать задание (long-poll)")
    ] = 25,
) -> AgentJob | Response:
    if wait == 0:
        return Response(status_code=204)
    copy = AgentJobCopy(png_base64=PNG_1X1_B64, width_mm=58.0, height_mm=40.0, gap_mm=2.0)
    return AgentJob(job_id=501, copies=[copy, copy])


@agent_router.post(
    "/jobs/{job_id}/result",
    operation_id="agent_job_result",
    summary="Сообщить результат печати",
    description="`Authorization: Agent <token>`. Задание получает статус `done` или `error`.",
    status_code=204,
    response_class=Response,
    dependencies=agent(),
    responses=err(401, 404, 422),
)
async def agent_job_result(job_id: int, body: AgentResultIn) -> None:
    return None


@agent_router.post(
    "/heartbeat",
    operation_id="agent_heartbeat",
    summary="Heartbeat агента и состояние принтера",
    description="`Authorization: Agent <token>`. Раз в несколько секунд: по нему видно «на связи».",
    status_code=204,
    response_class=Response,
    dependencies=agent(),
    responses=err(401, 422),
)
async def agent_heartbeat(body: HeartbeatIn) -> None:
    return None


router = APIRouter()
router.include_router(printers_router)
router.include_router(admin_router)
router.include_router(agent_router)
