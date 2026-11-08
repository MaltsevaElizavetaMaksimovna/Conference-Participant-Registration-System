"""Зависимости авторизации.

Схемы описывают в OpenAPI (Swagger «Authorize»), какой вид авторизации нужен эндпоинту
(`auto_error=False`: ошибки отдают сами зависимости в едином формате).

Терминал и агент печати проверяются по-настоящему (`app.terminals.deps`, B2-01).
TODO B1-01: сессия сотрудника (cookie `rs_session`), проверка разрешений и CSRF-заголовка;
сейчас `staff()` только описывает схему в OpenAPI.
"""

from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import Depends, Header, Security
from fastapi.security import APIKeyCookie, APIKeyHeader

from app.auth.deps import require_staff
from app.core.permissions import Permission

staff_session = APIKeyCookie(
    name="rs_session",
    scheme_name="StaffSession",
    auto_error=False,
    description=(
        "Сессия сотрудника: HttpOnly-cookie `rs_session`, ставится `POST /api/auth/login`. "
        "Эндпоинты, которые что-то меняют, требуют ещё заголовок `X-Requested-With: rs`. "
        "Без сессии `401 unauthenticated`, без разрешения `403 forbidden` "
        "(нужное разрешение указано в описании эндпоинта и в scopes схемы)."
    ),
)

terminal_token = APIKeyHeader(
    name="Authorization",
    scheme_name="TerminalToken",
    auto_error=False,
    description=(
        "Терминал: заголовок `Authorization: Terminal <token>`. Токен выдаёт администратор "
        "(`POST /api/admin/terminals/{id}/token`). Нет токена или он неверный — "
        "`401 invalid_device_token`, терминал отключён — `423 terminal_disabled`."
    ),
)

agent_token = APIKeyHeader(
    name="Authorization",
    scheme_name="AgentToken",
    auto_error=False,
    description=(
        "Агент печати: заголовок `Authorization: Agent <token>`. Токен выдаёт администратор "
        "(`POST /api/admin/printers/{id}/token`). Неверный токен — `401 invalid_device_token`."
    ),
)


async def csrf_header(
    x_requested_with: Annotated[
        str | None,
        Header(
            description="Защита от CSRF: для запросов сотрудника, меняющих данные, значение `rs`."
        ),
    ] = None,
) -> None:
    """Описывает заголовок в OpenAPI; саму проверку делает `get_current_staff`.

    Проверка живёт там, чтобы порядок ошибок был 401 (нет сессии) -> 403 `csrf_required` ->
    403 `forbidden`, а у анонимного запроса не раскрывалось ничего, кроме «нужен вход».
    Заголовок требуется от всех методов, кроме GET/HEAD/OPTIONS, а не только от `write=True`.
    """


def staff(*permissions: str, write: bool = False) -> Sequence[Any]:
    """Сотрудник с сессией и (опционально) разрешениями; `write=True` — ещё CSRF-заголовок.

    Схема `staff_session` со scopes нужна для OpenAPI, а проверку делает `require_staff`:
    401 `unauthenticated` без действующей сессии, 403 `forbidden` без разрешения.
    """
    perms = [Permission(p) for p in permissions]  # опечатка в коде разрешения -> ошибка при импорте
    deps: list[Any] = [
        Security(staff_session, scopes=[str(p) for p in perms]),
        Depends(require_staff(*perms)),
    ]
    if write:
        deps.append(Depends(csrf_header))
    return deps


def terminal() -> Sequence[Any]:
    """Терминал с токеном (`Authorization: Terminal`); отключённый получает 423."""
    from app.terminals.deps import get_current_terminal  # отложено: циклический импорт

    return [Security(get_current_terminal)]


def agent() -> Sequence[Any]:
    """Агент печати с токеном (`Authorization: Agent`)."""
    from app.terminals.deps import get_current_agent  # отложено: циклический импорт

    return [Security(get_current_agent)]
