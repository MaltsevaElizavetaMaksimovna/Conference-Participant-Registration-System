"""«Есть ошибка» на терминале (B2-05, ER-01)."""

from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import EventType, ParticipantStatus
from app.core.errors import AppError
from app.models.participant import EventLog, Participant
from app.registration import messages
from app.terminals.confirm_flow import check_scan_id, require_active_participant
from app.terminals.deps import CurrentTerminal
from app.terminals.schemas import ReportErrorOut


async def report_error(
    session: AsyncSession,
    terminal: CurrentTerminal,
    settings: Settings,
    *,
    participant_id: int,
    scan_id: str,
) -> ReportErrorOut:
    """Пометка «Сообщил об ошибке» с временем. Регистрации нет, наклейка не печатается.

    Участник потом может отсканировать код снова и подтвердить. Уже зарегистрированному
    ничего не меняем и показываем сообщение DP-01; условие `status = 'not_registered'`
    в UPDATE закрывает гонку с регистрацией.
    """
    check_scan_id(settings, terminal, participant_id, scan_id)
    await require_active_participant(session, participant_id)

    marked = (
        await session.execute(
            update(Participant)
            .where(
                Participant.id == participant_id,
                Participant.status == ParticipantStatus.NOT_REGISTERED,
            )
            .values(error_reported_at=func.clock_timestamp())
            .returning(Participant.conference_id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    if marked is not None:
        session.add(
            EventLog(
                conference_id=marked.conference_id,
                participant_id=participant_id,
                type=EventType.ERROR_REPORTED,
                terminal_id=terminal.terminal_id,
            )
        )
        await session.commit()
        return ReportErrorOut(message=messages.ERROR_REPORTED)

    registered_at = await session.scalar(
        select(Participant.registered_at).where(Participant.id == participant_id)
    )
    await session.commit()
    if registered_at is None:
        raise AppError("participant_not_found", messages.NOT_FOUND, 404)
    return ReportErrorOut(
        message=messages.already_registered(registered_at, ZoneInfo(settings.timezone))
    )
