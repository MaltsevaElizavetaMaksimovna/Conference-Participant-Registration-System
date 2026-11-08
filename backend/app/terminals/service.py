"""Администрирование терминалов и ответ `ping` (B2-01, B2-06)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.conference import Conference
from app.models.device import Printer, Terminal
from app.terminals.deps import CurrentTerminal
from app.terminals.schemas import (
    PingConference,
    PingOut,
    TerminalIn,
    TerminalOut,
    TerminalSettings,
    TerminalTokenOut,
)
from app.terminals.tokens import TERMINAL_PREFIX, generate_token, hash_token

PRINTER_READY = "ready"


def terminal_out(t: Terminal) -> TerminalOut:
    return TerminalOut(
        id=t.id,
        name=t.name,
        enabled=t.is_enabled,
        printer_id=t.printer_id,
        last_seen_at=t.last_seen_at,
        token_set=t.token_hash is not None,
    )


def _terminal_not_found() -> AppError:
    return AppError("terminal_not_found", "Терминал не найден", 404)


def _name_taken() -> AppError:
    return AppError("name_taken", "Терминал с таким названием уже есть", 409)


async def _check_printer(session: AsyncSession, printer_id: int | None) -> None:
    if printer_id is not None and await session.get(Printer, printer_id) is None:
        raise AppError(
            "printer_not_found",
            "Принтер не найден",
            422,
            {"fields": {"printer_id": "Принтер не найден"}},
        )


async def _name_exists(session: AsyncSession, name: str, *, exclude_id: int | None = None) -> bool:
    query = select(Terminal.id).where(Terminal.name == name)
    if exclude_id is not None:
        query = query.where(Terminal.id != exclude_id)
    return (await session.execute(query.limit(1))).first() is not None


async def list_terminals(
    session: AsyncSession, limit: int, offset: int
) -> tuple[list[TerminalOut], int]:
    total = await session.scalar(select(func.count()).select_from(Terminal)) or 0
    rows = await session.scalars(select(Terminal).order_by(Terminal.id).limit(limit).offset(offset))
    return [terminal_out(t) for t in rows], total


async def create_terminal(session: AsyncSession, body: TerminalIn) -> TerminalOut:
    await _check_printer(session, body.printer_id)
    if await _name_exists(session, body.name):
        raise _name_taken()
    terminal = Terminal(name=body.name, is_enabled=body.enabled, printer_id=body.printer_id)
    session.add(terminal)
    try:
        await session.commit()
    except IntegrityError:  # гонка двух одинаковых имён: ловит уникальный индекс
        await session.rollback()
        raise _name_taken() from None
    return terminal_out(terminal)


async def update_terminal(session: AsyncSession, terminal_id: int, body: TerminalIn) -> TerminalOut:
    terminal = await session.get(Terminal, terminal_id)
    if terminal is None:
        raise _terminal_not_found()
    changes = body.model_dump(exclude_unset=True)
    if "printer_id" in changes:
        await _check_printer(session, changes["printer_id"])
    if await _name_exists(session, body.name, exclude_id=terminal_id):
        raise _name_taken()
    terminal.name = body.name
    if "enabled" in changes:
        terminal.is_enabled = body.enabled
    if "printer_id" in changes:
        terminal.printer_id = body.printer_id
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _name_taken() from None
    return terminal_out(terminal)


async def issue_terminal_token(session: AsyncSession, terminal_id: int) -> TerminalTokenOut:
    """Новый токен; прежний перестаёт работать. В БД — только хэш."""
    terminal = await session.get(Terminal, terminal_id)
    if terminal is None:
        raise _terminal_not_found()
    token = generate_token(TERMINAL_PREFIX)
    terminal.token_hash = hash_token(token)
    await session.commit()
    return TerminalTokenOut(id=terminal.id, token=token)


async def build_ping(
    session: AsyncSession, terminal: CurrentTerminal, settings: Settings
) -> PingOut:
    """Состояние для экрана терминала: конференция, принтер терминала на связи или нет."""
    conference = (
        await session.execute(
            select(Conference.title, Conference.badge_type).where(Conference.is_active).limit(1)
        )
    ).first()

    printer_online = False
    if terminal.printer_id is not None:
        printer = (
            await session.execute(
                select(Printer.status, Printer.last_seen_at).where(
                    Printer.id == terminal.printer_id
                )
            )
        ).first()
        if printer is not None and printer.last_seen_at is not None:
            fresh = datetime.now(UTC) - printer.last_seen_at <= timedelta(
                seconds=settings.printer_online_timeout_s
            )
            printer_online = fresh and printer.status == PRINTER_READY

    return PingOut(
        terminal_name=terminal.name,
        enabled=True,  # отключённый терминал получает 423 раньше, чем дойдёт сюда
        conference=(
            PingConference(title=conference.title, badge_type=conference.badge_type)
            if conference
            else None
        ),
        printer_online=printer_online,
        server_time=datetime.now(UTC),
        settings=TerminalSettings(
            idle_timeout_s=settings.terminal_idle_timeout_s,
            result_screen_s=settings.result_screen_s,
        ),
    )
