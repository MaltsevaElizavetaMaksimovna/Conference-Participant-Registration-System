"""Статус задания печати для экрана терминала (TR-04, TR-08)."""

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import PrintJobStatus
from app.models.printing import PrintJob
from app.printing.queue import print_job_not_found
from app.registration import messages
from app.terminals.schemas import TerminalPrintJobOut


async def get_terminal_print_job(
    session: AsyncSession, terminal_id: int, print_job_id: int
) -> TerminalPrintJobOut:
    """Статус задания печати для экрана своего терминала: TR-04 или TR-08."""
    status = await session.scalar(
        select(PrintJob.status).where(
            PrintJob.id == print_job_id,
            PrintJob.created_by_terminal_id == terminal_id,
        )
    )
    if status is None:
        raise print_job_not_found()

    message = messages.STICKER_FAILED if status == "error" else messages.STICKER_PRINTING
    return TerminalPrintJobOut(status=cast(PrintJobStatus, status), message=message)
