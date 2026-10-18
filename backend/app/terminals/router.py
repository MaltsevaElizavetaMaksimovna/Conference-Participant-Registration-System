"""Эндпоинты терминала самообслуживания и админка терминалов. ЗАГЛУШКИ (B2-03, B2-05)."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header

from app.api.common import STUB_TAG, Limit, Offset, Page, err
from app.api.deps import staff, terminal
from app.api.stubs import T0
from app.terminals.schemas import (
    ConfirmIn,
    ConfirmOut,
    PingConference,
    PingOut,
    ReportErrorIn,
    ReportErrorOut,
    ScanAlreadyRegistered,
    ScanFound,
    ScanIn,
    ScanNotFound,
    ScanOut,
    ScanParticipant,
    TerminalIn,
    TerminalOut,
    TerminalPrintJobOut,
    TerminalSettings,
    TerminalTokenOut,
)

terminal_router = APIRouter(prefix="/terminal", tags=["terminal", STUB_TAG])
admin_router = APIRouter(prefix="/admin/terminals", tags=["admin: terminals", STUB_TAG])

_DISABLED = (423, "`terminal_disabled`: «Терминал не работает, воспользуйтесь соседним»")


@terminal_router.get(
    "/ping",
    operation_id="terminal_ping",
    summary="Проверка связи и состояния терминала",
    description=(
        "`Authorization: Terminal <token>`. Вызывать каждые 3 с; после 2 неудач подряд "
        "показывать «Нет связи с сервером» и не принимать коды (NF-05)."
    ),
    response_model=PingOut,
    dependencies=terminal(),
    responses=err(401, _DISABLED),
)
async def terminal_ping() -> PingOut:
    return PingOut(
        terminal_name="Терминал 2",
        enabled=True,
        conference=PingConference(title="Демо-конференция", badge_type="single"),
        printer_online=True,
        server_time=datetime.now(UTC),
        settings=TerminalSettings(idle_timeout_s=60, result_screen_s=10),
    )


@terminal_router.post(
    "/scan",
    operation_id="terminal_scan",
    summary="Отправить отсканированный код",
    description=(
        "`Authorization: Terminal <token>`. Результат в поле `result`: `found` (показать "
        "данные и кнопку подтверждения), `not_found`, `already_registered`. Если нет активной "
        "конференции, всегда `not_found`. **Заглушка:** `raw` с подстрокой `notfound` даёт "
        "`not_found`, с подстрокой `again` — `already_registered`, иначе `found`."
    ),
    response_model=ScanOut,
    dependencies=terminal(),
    responses=err(401, 422, _DISABLED),
)
async def terminal_scan(body: ScanIn) -> ScanFound | ScanNotFound | ScanAlreadyRegistered:
    raw = body.raw.lower()
    if "notfound" in raw:
        return ScanNotFound(
            result="not_found", message="Участник не найден. Обратитесь к стойке регистрации"
        )
    if "again" in raw:
        return ScanAlreadyRegistered(
            result="already_registered",
            message=(
                "Вы уже зарегистрированы (20.11, 09:15). "
                "Если вы не получили бейдж — обратитесь к стойке регистрации"
            ),
        )
    return ScanFound(
        result="found",
        scan_id="scan_8f14e45f",
        participant=ScanParticipant(
            id=17,
            full_name="Иванов Пётр Сергеевич",
            position="не указано",
            organization="ООО Ромашка",
        ),
    )


@terminal_router.post(
    "/confirm",
    operation_id="terminal_confirm",
    summary="Подтвердить регистрацию",
    description=(
        "`Authorization: Terminal <token>` + обязательный заголовок `Idempotency-Key` (UUID, "
        "один на экран подтверждения; повторные нажатия отправлять с тем же ключом). "
        "Результат `registered` (с `print_job_id`) или `already_registered`. После "
        "`print_job_id` опрашивайте `GET /api/terminal/print-jobs/{id}` раз в 500 мс, не "
        "дольше 15 с. **Заглушка:** `participant_id=18` даёт `already_registered`."
    ),
    response_model=ConfirmOut,
    dependencies=terminal(),
    responses=err(401, 422, 404, _DISABLED),
)
async def terminal_confirm(
    body: ConfirmIn,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            description="Ключ идемпотентности (UUID)",
            examples=["3f2b8c1e-5a6d-4e7f-9b0a-1c2d3e4f5a6b"],
        ),
    ],
) -> ConfirmOut:
    if body.participant_id == 18:
        return ConfirmOut(
            result="already_registered",
            message="Вы уже зарегистрированы (20.11, 09:15). Обратитесь к стойке регистрации",
        )
    return ConfirmOut(
        result="registered",
        print_job_id=501,
        message="Регистрация выполнена. Печатаем вашу наклейку",
    )


@terminal_router.post(
    "/report-error",
    operation_id="terminal_report_error",
    summary="Сообщить, что данные участника неверны",
    description="`Authorization: Terminal <token>`. Ставит участнику пометку «Ошибка» (ER-01).",
    response_model=ReportErrorOut,
    dependencies=terminal(),
    responses=err(401, 422, 404, _DISABLED),
)
async def terminal_report_error(body: ReportErrorIn) -> ReportErrorOut:
    return ReportErrorOut(
        message="Спасибо, мы передали информацию. Обратитесь к стойке регистрации"
    )


@terminal_router.get(
    "/print-jobs/{print_job_id}",
    operation_id="terminal_print_job",
    summary="Статус печати для экрана терминала",
    description=(
        "`Authorization: Terminal <token>`. `message` показывать на экране как есть. "
        "Заглушка всегда отвечает `done`."
    ),
    response_model=TerminalPrintJobOut,
    dependencies=terminal(),
    responses=err(401, 404, _DISABLED),
)
async def terminal_print_job(print_job_id: int) -> TerminalPrintJobOut:
    return TerminalPrintJobOut(
        status="done", message="Заберите наклейку из принтера и приклейте её"
    )


def _terminal(terminal_id: int) -> TerminalOut:
    return TerminalOut(
        id=terminal_id,
        name=f"Терминал {terminal_id}",
        enabled=True,
        printer_id=1,
        last_seen_at=T0,
        token_set=True,
    )


@admin_router.get(
    "",
    operation_id="admin_terminals_list",
    summary="Терминалы",
    description="Разрешение: `devices.manage`.",
    response_model=Page[TerminalOut],
    dependencies=staff("devices.manage"),
    responses=err(401, 403),
)
async def admin_terminals_list(limit: Limit = 50, offset: Offset = 0) -> Page[TerminalOut]:
    items = [_terminal(1), _terminal(2).model_copy(update={"enabled": False})]
    return Page[TerminalOut](items=items[offset : offset + limit], total=len(items))


@admin_router.post(
    "",
    operation_id="admin_terminals_create",
    summary="Добавить терминал",
    description="Разрешение: `devices.manage`. Токен выдаётся отдельным запросом.",
    status_code=201,
    response_model=TerminalOut,
    dependencies=staff("devices.manage", write=True),
    responses=err(401, 403, 422, (409, "`name_taken`: терминал с таким именем уже есть")),
)
async def admin_terminals_create(body: TerminalIn) -> TerminalOut:
    return TerminalOut(
        id=3,
        name=body.name,
        enabled=body.enabled,
        printer_id=body.printer_id,
        last_seen_at=None,
        token_set=False,
    )


@admin_router.put(
    "/{terminal_id}",
    operation_id="admin_terminals_update",
    summary="Изменить терминал",
    description="Разрешение: `devices.manage`. `enabled=false` отключает терминал (423).",
    response_model=TerminalOut,
    dependencies=staff("devices.manage", write=True),
    responses=err(401, 403, 404, 422),
)
async def admin_terminals_update(terminal_id: int, body: TerminalIn) -> TerminalOut:
    return _terminal(terminal_id).model_copy(
        update={"name": body.name, "enabled": body.enabled, "printer_id": body.printer_id}
    )


@admin_router.post(
    "/{terminal_id}/token",
    operation_id="admin_terminals_token",
    summary="Выдать новый токен терминала",
    description=(
        "Разрешение: `devices.manage`. Токен показывается **один раз**; предыдущий перестаёт "
        "работать."
    ),
    response_model=TerminalTokenOut,
    dependencies=staff("devices.manage", write=True),
    responses=err(401, 403, 404),
)
async def admin_terminals_token(terminal_id: int) -> TerminalTokenOut:
    return TerminalTokenOut(id=terminal_id, token="trm_Zk3x9QnS7Vb2LmT4Zk3x9QnS7Vb2LmT4")


router = APIRouter()
router.include_router(terminal_router)
router.include_router(admin_router)
