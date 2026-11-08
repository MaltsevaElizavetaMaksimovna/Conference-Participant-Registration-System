"""Администрирование принтеров и heartbeat агента печати (B2-01)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import PrinterOut, PrinterStatus
from app.core.errors import AppError
from app.models.device import Printer
from app.printing.schemas import PrinterAdminOut, PrinterIn, PrinterTokenOut
from app.terminals.tokens import AGENT_PREFIX, generate_token, hash_token


def _status(value: str) -> PrinterStatus:
    # В БД статус текстовый; неожиданное значение показываем как «неизвестно»
    return cast(PrinterStatus, value if value in ("ready", "offline", "error") else "unknown")


def printer_out(p: Printer) -> PrinterOut:
    return PrinterOut(id=p.id, name=p.name, status=_status(p.status), last_seen_at=p.last_seen_at)


def printer_admin_out(p: Printer) -> PrinterAdminOut:
    return PrinterAdminOut(
        id=p.id,
        name=p.name,
        status=_status(p.status),
        last_seen_at=p.last_seen_at,
        windows_printer_name=p.windows_printer_name,
        dpi=p.dpi,
        offset_x_mm=float(p.offset_x_mm),
        offset_y_mm=float(p.offset_y_mm),
        density=p.density,
        speed=p.speed,
        token_set=p.agent_token_hash is not None,
    )


def _printer_not_found() -> AppError:
    return AppError("printer_not_found", "Принтер не найден", 404)


def _name_taken() -> AppError:
    return AppError("name_taken", "Принтер с таким названием уже есть", 409)


def _db_values(changes: dict[str, Any]) -> dict[str, Any]:
    """Поля схемы -> атрибуты модели (миллиметры храним как Numeric)."""
    values = dict(changes)
    for key in ("offset_x_mm", "offset_y_mm"):
        if key in values:
            values[key] = Decimal(str(round(values[key], 2)))
    return values


async def list_printers(session: AsyncSession) -> list[Printer]:
    return list(await session.scalars(select(Printer).order_by(Printer.id)))


async def list_printers_page(
    session: AsyncSession, limit: int, offset: int
) -> tuple[list[PrinterAdminOut], int]:
    total = await session.scalar(select(func.count()).select_from(Printer)) or 0
    rows = await session.scalars(select(Printer).order_by(Printer.id).limit(limit).offset(offset))
    return [printer_admin_out(p) for p in rows], total


async def _name_exists(session: AsyncSession, name: str, *, exclude_id: int | None = None) -> bool:
    query = select(Printer.id).where(Printer.name == name)
    if exclude_id is not None:
        query = query.where(Printer.id != exclude_id)
    return (await session.execute(query.limit(1))).first() is not None


async def create_printer(session: AsyncSession, body: PrinterIn) -> PrinterAdminOut:
    if await _name_exists(session, body.name):
        raise _name_taken()
    printer = Printer(**_db_values(body.model_dump()))
    session.add(printer)
    try:
        await session.commit()
    except IntegrityError:  # гонка двух одинаковых имён
        await session.rollback()
        raise _name_taken() from None
    return printer_admin_out(printer)


async def update_printer(
    session: AsyncSession, printer_id: int, body: PrinterIn
) -> PrinterAdminOut:
    printer = await session.get(Printer, printer_id)
    if printer is None:
        raise _printer_not_found()
    if await _name_exists(session, body.name, exclude_id=printer_id):
        raise _name_taken()
    # Калибровку не сбрасываем, если её не прислали
    for key, value in _db_values(body.model_dump(exclude_unset=True)).items():
        setattr(printer, key, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _name_taken() from None
    return printer_admin_out(printer)


async def issue_agent_token(session: AsyncSession, printer_id: int) -> PrinterTokenOut:
    """Новый токен агента; прежний перестаёт работать. В БД — только хэш."""
    printer = await session.get(Printer, printer_id)
    if printer is None:
        raise _printer_not_found()
    token = generate_token(AGENT_PREFIX)
    printer.agent_token_hash = hash_token(token)
    await session.commit()
    return PrinterTokenOut(id=printer.id, token=token)


async def record_heartbeat(session: AsyncSession, printer_id: int, status: PrinterStatus) -> None:
    await session.execute(
        update(Printer)
        .where(Printer.id == printer_id)
        .values(status=status, last_seen_at=datetime.now(UTC))
    )
    await session.commit()
