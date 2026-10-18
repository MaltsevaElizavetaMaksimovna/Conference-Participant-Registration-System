"""Текущий терминал и агент печати — общий интерфейс.

В тестах подменяются через `app.dependency_overrides[get_current_terminal]` / `[get_current_agent]`.

Терминал: `Authorization: Terminal <token>`, агент: `Authorization: Agent <token>`. Схемы
разные, поэтому токен терминала не подходит агенту и наоборот. Ни тот ни другой не открывает
API сотрудника: оно читает только cookie `rs_session`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request, Security
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import agent_token, terminal_token
from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import AppError
from app.models.device import Printer, Terminal
from app.terminals.tokens import hash_token

TERMINAL_DISABLED_MESSAGE = "Терминал не работает, воспользуйтесь соседним"
INVALID_TOKEN_MESSAGE = "Неверный или отсутствующий токен устройства"


@dataclass(frozen=True)
class CurrentTerminal:
    terminal_id: int
    name: str
    printer_id: int | None


@dataclass(frozen=True)
class CurrentAgent:
    printer_id: int
    name: str


def _invalid_token() -> AppError:
    return AppError("invalid_device_token", INVALID_TOKEN_MESSAGE, 401)


def parse_device_token(header: str | None, scheme: str) -> str | None:
    """`Authorization: <scheme> <token>` -> токен; схема без учёта регистра."""
    if not header:
        return None
    parts = header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != scheme.lower():
        return None
    return parts[1].strip() or None


async def get_current_terminal(
    request: Request,
    header: Annotated[str | None, Security(terminal_token)],
    session: AsyncSession = Depends(get_session),
) -> CurrentTerminal:
    """`Authorization: Terminal <token>` -> терминал.

    Нет токена или он неверный: 401 `invalid_device_token`. Терминал отключён: 423
    `terminal_disabled`. Время последней связи обновляется не чаще раза в 10 с.
    """
    token = parse_device_token(header, "Terminal")
    if token is None:
        raise _invalid_token()
    row = (
        await session.execute(
            select(Terminal.id, Terminal.name, Terminal.printer_id, Terminal.is_enabled)
            .where(Terminal.token_hash == hash_token(token))
            .limit(1)
        )
    ).first()
    if row is None:
        raise _invalid_token()

    settings: Settings = request.app.state.settings
    now = datetime.now(UTC)
    stale = now - timedelta(seconds=settings.device_last_seen_throttle_s)
    # Условный UPDATE: при нескольких запросах подряд пишет только первый
    result = await session.execute(
        update(Terminal)
        .where(Terminal.id == row.id)
        .where((Terminal.last_seen_at.is_(None)) | (Terminal.last_seen_at <= stale))
        .values(last_seen_at=now)
    )
    if result.rowcount:  # type: ignore[attr-defined]
        await session.commit()

    # «Связь есть» отмечаем и у отключённого терминала: админ видит, что он жив
    if not row.is_enabled:
        raise AppError("terminal_disabled", TERMINAL_DISABLED_MESSAGE, 423)
    return CurrentTerminal(terminal_id=row.id, name=row.name, printer_id=row.printer_id)


async def get_current_agent(
    header: Annotated[str | None, Security(agent_token)],
    session: AsyncSession = Depends(get_session),
) -> CurrentAgent:
    """`Authorization: Agent <token>` -> принтер, которому выдан токен; иначе 401."""
    token = parse_device_token(header, "Agent")
    if token is None:
        raise _invalid_token()
    row = (
        await session.execute(
            select(Printer.id, Printer.name).where(Printer.agent_token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        raise _invalid_token()
    return CurrentAgent(printer_id=row.id, name=row.name)
