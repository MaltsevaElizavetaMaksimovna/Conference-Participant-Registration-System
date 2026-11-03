"""Смена статуса задания печати (B2-04a; выдача и результат заданий — B2-11)."""

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PrintJobStatus
from app.eventlog.notify import notify_participant_updated
from app.models.printing import PrintJob


async def set_job_status(
    session: AsyncSession,
    job_id: int,
    status: PrintJobStatus,
    *,
    error: str | None = None,
) -> bool:
    """Записать новый статус задания и сообщить панели об участнике. Без commit.

    `sent` ставит `sent_at`, `done`/`error` — `done_at`. Пробная печать (без участника)
    событие не шлёт. Возвращает False, если задания нет.
    """
    values: dict[str, object] = {"status": status.value, "error": error}
    if status == PrintJobStatus.SENT:
        values["sent_at"] = func.clock_timestamp()
    elif status in (PrintJobStatus.DONE, PrintJobStatus.ERROR):
        values["done_at"] = func.clock_timestamp()
    row = (
        await session.execute(
            update(PrintJob)
            .where(PrintJob.id == job_id)
            .values(**values)
            .returning(PrintJob.participant_id, PrintJob.conference_id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if row is None:
        return False
    if row.participant_id is not None:
        await notify_participant_updated(session, row.participant_id, row.conference_id)
    return True
