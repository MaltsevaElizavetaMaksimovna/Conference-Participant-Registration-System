"""Эндпоинты терминала самообслуживания и админка терминалов.

Реальные: `ping`, `scan`, `confirm`, `report-error` и админка (B2-01, B2-03..06).
Заглушка осталась только у `print-jobs/{id}` (B2-11), но уже под настоящей авторизацией.
"""

from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import STUB_TAG, Limit, Offset, Page, err
from app.api.deps import staff, terminal
from app.core.config import Settings
from app.core.db import get_session
from app.core.permissions import Permission
from app.terminals import confirm_flow, scan_flow, service
from app.terminals.deps import CurrentTerminal, get_current_terminal
from app.terminals.schemas import (
    ConfirmIn,
    ConfirmOut,
    PingOut,
    ReportErrorIn,
    ReportErrorOut,
    ScanAlreadyRegistered,
    ScanFound,
    ScanIn,
    ScanNotFound,
    ScanOut,
    TerminalIn,
    TerminalOut,
    TerminalPrintJobOut,
    TerminalTokenOut,
)

terminal_router = APIRouter(prefix="/terminal", tags=["terminal"])
admin_router = APIRouter(prefix="/admin/terminals", tags=["admin: terminals"])

Session = Annotated[AsyncSession, Depends(get_session)]
_STUB: list[str | Enum] = [STUB_TAG]

_DISABLED = (423, "`terminal_disabled`: «Терминал не работает, воспользуйтесь соседним»")
_INVALID_TOKEN = (401, "`invalid_device_token`: токен терминала отсутствует или неверный")


@terminal_router.get(
    "/ping",
    operation_id="terminal_ping",
    summary="Проверка связи и состояния терминала",
    description=(
        "`Authorization: Terminal <token>`. Вызывать каждые 3 с; после 2 неудач подряд "
        "показывать «Нет связи с сервером» и не принимать коды (NF-05). `printer_online` — "
        "принтер этого терминала прислал heartbeat со статусом `ready` не позже чем 30 с назад. "
        "Отключённый терминал получает `423 terminal_disabled`."
    ),
    response_model=PingOut,
    dependencies=terminal(),
    responses=err(_INVALID_TOKEN, _DISABLED),
)
async def terminal_ping(
    request: Request,
    session: Session,
    current: CurrentTerminal = Depends(get_current_terminal),
) -> PingOut:
    settings: Settings = request.app.state.settings
    return await service.build_ping(session, current, settings)


@terminal_router.post(
    "/scan",
    operation_id="terminal_scan",
    summary="Отправить отсканированный код",
    description=(
        "`Authorization: Terminal <token>`. Результат в поле `result`: `found` (показать "
        "данные и кнопки «Да, всё верно» / «Есть ошибка»; `scan_id` передать в confirm и "
        "report-error), `not_found`, `already_registered`. Поиск идёт только среди участников "
        "активной конференции; если её нет, всегда `not_found`. Строка нормализуется "
        "(раскладка, пробелы), из ссылки берётся ID приглашения (регулярка конференции "
        "`invite_id_regex`, иначе `RS_INVITE_ID_REGEX`); ссылка, из которой ID не достать, "
        "и QR с наклейки дают `not_found`. Пустые должность и организация приходят как "
        "«не указано». Не найденный код пишется в журнал, повторный скан зарегистрированного "
        "увеличивает счётчик в карточке. Время в сообщении — в часовом поясе `RS_TIMEZONE`. "
        "`scan_id` подписан, привязан к терминалу и участнику и живёт `idle_timeout_s + 30` с."
    ),
    response_model=ScanOut,
    dependencies=terminal(),
    responses=err(_INVALID_TOKEN, 422, _DISABLED),
)
async def terminal_scan(
    body: ScanIn,
    request: Request,
    session: Session,
    current: CurrentTerminal = Depends(get_current_terminal),
) -> ScanFound | ScanNotFound | ScanAlreadyRegistered:
    settings: Settings = request.app.state.settings
    return await scan_flow.scan(session, current, body.raw, settings)


@terminal_router.post(
    "/confirm",
    operation_id="terminal_confirm",
    summary="Подтвердить регистрацию",
    description=(
        "`Authorization: Terminal <token>` + обязательный заголовок `Idempotency-Key` (UUID, "
        "один на экран подтверждения; повторные нажатия отправлять с тем же ключом, ответ "
        "будет тот же и наклейка одна). Результат `registered` (с `print_job_id`, если "
        "наклейка отправлена на печать) или `already_registered` (200, не ошибка: кто-то "
        "успел раньше). `message` показывать на экране как есть. Если принтер не привязан, "
        "регистрация всё равно проходит, `print_job_id = null`, в `message` текст TR-08. "
        "Для конференции «без бейджа» печати нет. После `print_job_id` опрашивайте "
        "`GET /api/terminal/print-jobs/{id}` раз в 500 мс, не дольше 15 с. "
        "Ошибки: `409 scan_expired` («Отсканируйте код ещё раз»), "
        "`404 participant_not_found` (участник не из активной конференции)."
    ),
    response_model=ConfirmOut,
    dependencies=terminal(),
    responses=err(
        _INVALID_TOKEN,
        422,
        (404, "`participant_not_found`: участника нет в активной конференции"),
        (
            409,
            "`scan_expired`: `scan_id` просрочен или чужой, отсканируйте код ещё раз; "
            "`idempotency_key_reused`: ключ уже использован для другого участника",
        ),
        _DISABLED,
    ),
)
async def terminal_confirm(
    body: ConfirmIn,
    request: Request,
    session: Session,
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
    current: CurrentTerminal = Depends(get_current_terminal),
) -> ConfirmOut:
    settings: Settings = request.app.state.settings
    return await confirm_flow.confirm(
        session,
        current,
        settings,
        participant_id=body.participant_id,
        scan_id=body.scan_id,
        idempotency_key=idempotency_key,
    )


@terminal_router.post(
    "/report-error",
    operation_id="terminal_report_error",
    summary="Сообщить, что данные участника неверны",
    description="`Authorization: Terminal <token>`. Ставит участнику пометку «Ошибка» (ER-01).",
    response_model=ReportErrorOut,
    dependencies=terminal(),
    responses=err(_INVALID_TOKEN, 422, 404, _DISABLED),
    tags=_STUB,
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
    responses=err(_INVALID_TOKEN, 404, _DISABLED),
    tags=_STUB,
)
async def terminal_print_job(print_job_id: int) -> TerminalPrintJobOut:
    return TerminalPrintJobOut(
        status="done", message="Заберите наклейку из принтера и приклейте её"
    )


_ADMIN = Permission.DEVICES_MANAGE


@admin_router.get(
    "",
    operation_id="admin_terminals_list",
    summary="Терминалы",
    description="Разрешение: `devices.manage`.",
    response_model=Page[TerminalOut],
    dependencies=staff(_ADMIN),
    responses=err(401, 403),
)
async def admin_terminals_list(
    session: Session, limit: Limit = 50, offset: Offset = 0
) -> Page[TerminalOut]:
    items, total = await service.list_terminals(session, limit, offset)
    return Page[TerminalOut](items=items, total=total)


@admin_router.post(
    "",
    operation_id="admin_terminals_create",
    summary="Добавить терминал",
    description=(
        "Разрешение: `devices.manage`. Токен выдаётся отдельным запросом. "
        "`printer_id` должен существовать (`422 printer_not_found`)."
    ),
    status_code=201,
    response_model=TerminalOut,
    dependencies=staff(_ADMIN, write=True),
    responses=err(
        401,
        403,
        (422, "`validation_error` или `printer_not_found`: принтер не существует"),
        (409, "`name_taken`: терминал с таким именем уже есть"),
    ),
)
async def admin_terminals_create(body: TerminalIn, session: Session) -> TerminalOut:
    return await service.create_terminal(session, body)


@admin_router.put(
    "/{terminal_id}",
    operation_id="admin_terminals_update",
    summary="Изменить терминал",
    description=(
        "Разрешение: `devices.manage`. `enabled=false` отключает терминал (423). "
        "Меняются только переданные поля (`name` обязателен); чтобы отвязать принтер, "
        "передайте `printer_id: null`."
    ),
    response_model=TerminalOut,
    dependencies=staff(_ADMIN, write=True),
    responses=err(
        401,
        403,
        (404, "`terminal_not_found`: терминала нет"),
        (422, "`validation_error` или `printer_not_found`: принтер не существует"),
        (409, "`name_taken`: терминал с таким именем уже есть"),
    ),
)
async def admin_terminals_update(
    terminal_id: int, body: TerminalIn, session: Session
) -> TerminalOut:
    return await service.update_terminal(session, terminal_id, body)


@admin_router.post(
    "/{terminal_id}/token",
    operation_id="admin_terminals_token",
    summary="Выдать новый токен терминала",
    description=(
        "Разрешение: `devices.manage`. Токен показывается **один раз** (в базе только его "
        "хэш); предыдущий перестаёт работать."
    ),
    response_model=TerminalTokenOut,
    dependencies=staff(_ADMIN, write=True),
    responses=err(401, 403, (404, "`terminal_not_found`: терминала нет")),
)
async def admin_terminals_token(terminal_id: int, session: Session) -> TerminalTokenOut:
    return await service.issue_terminal_token(session, terminal_id)


router = APIRouter()
router.include_router(terminal_router)
router.include_router(admin_router)
