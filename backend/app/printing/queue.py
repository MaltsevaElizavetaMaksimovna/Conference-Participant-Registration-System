"""Очередь заданий печати (B2-11, TR-04, TR-08, RG-08).

Жизнь задания: `pending` → (агент забрал) `sent` → `done` | `error`.

- **Выдача** — `SELECT … FOR UPDATE SKIP LOCKED`: два одновременных запроса одного агента
  (или повтор после обрыва) никогда не получат одно задание. Наклейка рисуется в момент
  выдачи по текущему шаблону (PR-05), с калибровкой принтера.
- **Просрочка** — `pending` дольше `RS_PRINT_PENDING_TIMEOUT_S` (агент или принтер выключен)
  и `sent` без ответа дольше `RS_PRINT_CONFIRM_TIMEOUT_S` становятся `error`. Просроченное
  `pending` агенту уже не выдаётся: наклейка, вышедшая через минуту, никому не нужна.
- **Итог** меняется условным UPDATE (`WHERE status IN …`): ответ агента и просрочка не
  применяются дважды, повтор ответа агента ничего не меняет.

Итог задания с участником (кроме пробной печати): `done` — счётчик печатей +1, пометка
«Наклейка не напечатана» снимается; `error` — пометка ставится. Плюс событие в журнале и
`NOTIFY` для панели — в той же транзакции.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import EventType, PrintJobKind, PrintJobStatus
from app.core.errors import AppError
from app.eventlog.notify import notify_participant_updated
from app.models.device import Printer
from app.models.participant import EventLog, Participant
from app.models.printing import PrintJob
from app.printing.schemas import AgentJob, AgentJobCopy

# Причины ошибки в `print_job.error`
REASON_TIMEOUT = "timeout"  # агент забрал, но не ответил
REASON_NOT_PICKED = "not_picked_up"  # агент не забрал вовремя
REASON_PRINTER = "printer_error"  # агент сообщил об ошибке без текста
MAX_ERROR_LEN = 500

_RESULT_COLUMNS = (
    PrintJob.id,
    PrintJob.participant_id,
    PrintJob.conference_id,
    PrintJob.kind,
    PrintJob.created_by_terminal_id,
    PrintJob.created_by_user_id,
)

# Рендер задания: (сессия, настройки, задание, принтер) -> наклейки; AppError — не напечатать
RenderJob = Callable[[AsyncSession, Settings, PrintJob, Printer], Awaitable[list[AgentJobCopy]]]


def print_job_not_found() -> AppError:
    return AppError("print_job_not_found", "Задание печати не найдено", 404)


async def _apply_outcome(session: AsyncSession, row: Any, ok: bool, reason: str | None) -> None:
    """Последствия итога для участника: счётчик, пометка, журнал, событие панели. Без commit."""
    if row.participant_id is None or row.kind == PrintJobKind.TEST:
        return
    values: dict[str, Any] = (
        {"print_count": Participant.print_count + 1, "sticker_not_printed": False}
        if ok
        else {"sticker_not_printed": True}
    )
    await session.execute(
        update(Participant)
        .where(Participant.id == row.participant_id)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    payload: dict[str, Any] = {"job_id": row.id, "kind": row.kind}
    if not ok:
        payload["reason"] = reason
    session.add(
        EventLog(
            conference_id=row.conference_id,
            participant_id=row.participant_id,
            type=EventType.PRINT_OK if ok else EventType.PRINT_ERROR,
            terminal_id=row.created_by_terminal_id,
            user_id=row.created_by_user_id,
            payload=payload,
        )
    )
    await notify_participant_updated(session, row.participant_id, row.conference_id)


async def expire_stale(
    session: AsyncSession, settings: Settings, printer_id: int | None = None
) -> int:
    """Просроченные задания → `error` (все или одного принтера). Commit. Возвращает число."""
    now = func.now()
    pending_cutoff = now - timedelta(seconds=settings.print_pending_timeout_s)
    sent_cutoff = now - timedelta(seconds=settings.print_confirm_timeout_s)
    stale = or_(
        and_(PrintJob.status == PrintJobStatus.PENDING, PrintJob.created_at < pending_cutoff),
        and_(PrintJob.status == PrintJobStatus.SENT, PrintJob.sent_at < sent_cutoff),
    )
    if printer_id is not None:
        stale = and_(PrintJob.printer_id == printer_id, stale)
    rows = (
        await session.execute(
            update(PrintJob)
            .where(stale)
            .values(
                status=PrintJobStatus.ERROR,
                error=case(
                    (PrintJob.status == PrintJobStatus.SENT, REASON_TIMEOUT),
                    else_=REASON_NOT_PICKED,
                ),
                done_at=func.clock_timestamp(),
            )
            .returning(*_RESULT_COLUMNS, PrintJob.error)
            .execution_options(synchronize_session=False)
        )
    ).all()
    for row in rows:
        await _apply_outcome(session, row, ok=False, reason=row.error)
    await session.commit()
    return len(rows)


async def _fail(session: AsyncSession, job_id: int, reason: str) -> None:
    """Задание, которое нельзя напечатать (нет шаблона и т. п.), сразу → `error`. Commit."""
    rows = (
        await session.execute(
            update(PrintJob)
            .where(PrintJob.id == job_id, PrintJob.status == PrintJobStatus.PENDING)
            .values(status=PrintJobStatus.ERROR, error=reason, done_at=func.clock_timestamp())
            .returning(*_RESULT_COLUMNS)
            .execution_options(synchronize_session=False)
        )
    ).all()
    for row in rows:
        await _apply_outcome(session, row, ok=False, reason=reason)
    await session.commit()


async def claim_next(
    session: AsyncSession, settings: Settings, printer: Printer, render: RenderJob
) -> AgentJob | None:
    """Забрать самое старое свежее задание принтера, нарисовать и пометить `sent`. Commit.

    Задание, которое не нарисовать (`AppError`), сразу становится `error`, и берётся
    следующее. Нет заданий — None.
    """
    pending_cutoff = func.now() - timedelta(seconds=settings.print_pending_timeout_s)
    # После rollback объекты сессии истекают: всё нужное о принтере берём заранее
    printer_id = printer.id
    offset_x, offset_y = float(printer.offset_x_mm), float(printer.offset_y_mm)
    density, speed = printer.density, printer.speed
    while True:
        job = (
            await session.execute(
                select(PrintJob)
                .where(
                    PrintJob.printer_id == printer_id,
                    PrintJob.status == PrintJobStatus.PENDING,
                    PrintJob.created_at >= pending_cutoff,
                )
                .order_by(PrintJob.created_at, PrintJob.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if job is None:
            await session.rollback()  # не держим транзакцию между опросами
            return None
        job_id, participant_id = job.id, job.participant_id
        conference_id, kind = job.conference_id, job.kind
        try:
            copies = await render(session, settings, job, printer)
        except AppError as e:
            await session.rollback()
            await _fail(session, job_id, e.code)
            continue
        await session.execute(
            update(PrintJob)
            .where(PrintJob.id == job_id)
            .values(
                status=PrintJobStatus.SENT,
                sent_at=func.clock_timestamp(),
                attempts=PrintJob.attempts + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if participant_id is not None and kind != PrintJobKind.TEST:
            await notify_participant_updated(session, participant_id, conference_id)
        await session.commit()
        return AgentJob(
            job_id=job_id,
            copies=copies,
            offset_x_mm=offset_x,
            offset_y_mm=offset_y,
            density=density,
            speed=speed,
        )


async def finish_job(
    session: AsyncSession, printer_id: int, job_id: int, ok: bool, error: str | None
) -> None:
    """Ответ агента о печати. Повтор того же ответа ничего не меняет. Commit.

    - `sent` → `done`/`error`;
    - `error` по просрочке → `done`, если наклейка всё-таки вышла (агент ответил поздно);
    - `done` — окончательный, повторы игнорируются;
    - `pending` (агент такое задание не получал) — `409 print_job_not_sent`;
    - задание другого принтера или несуществующее — `404 print_job_not_found`.
    """
    allowed: Sequence[str] = (
        (PrintJobStatus.SENT, PrintJobStatus.ERROR) if ok else (PrintJobStatus.SENT,)
    )
    reason = None if ok else ((error or "").strip()[:MAX_ERROR_LEN] or REASON_PRINTER)
    row = (
        await session.execute(
            update(PrintJob)
            .where(
                PrintJob.id == job_id,
                PrintJob.printer_id == printer_id,
                PrintJob.status.in_(allowed),
            )
            .values(
                status=PrintJobStatus.DONE if ok else PrintJobStatus.ERROR,
                error=reason,
                done_at=func.clock_timestamp(),
            )
            .returning(*_RESULT_COLUMNS)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if row is not None:
        await _apply_outcome(session, row, ok, reason)
        await session.commit()
        return
    status = await session.scalar(
        select(PrintJob.status).where(PrintJob.id == job_id, PrintJob.printer_id == printer_id)
    )
    await session.rollback()
    if status is None:
        raise print_job_not_found()
    if status == PrintJobStatus.PENDING:
        raise AppError("print_job_not_sent", "Задание ещё не выдано агенту", 409)
    # done или повтор ошибки — повтор ответа агента, ничего не меняем
