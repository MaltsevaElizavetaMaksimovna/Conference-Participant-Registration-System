"""Повторная попытка зарегистрированного участника (DP-01)."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EventType
from app.models.participant import EventLog, Participant


async def record_rescan(
    session: AsyncSession, participant_id: int, conference_id: int, terminal_id: int
) -> None:
    """Счётчик повторов в карточке + событие `scan_rescan` (время, терминал). Без commit.

    Счётчик растёт атомарно на стороне БД (`SET rescan_count = rescan_count + 1`), чтобы
    одновременные сканы не теряли друг друга.
    """
    await session.execute(
        update(Participant)
        .where(Participant.id == participant_id)
        .values(rescan_count=Participant.rescan_count + 1)
        .execution_options(synchronize_session=False)
    )
    session.add(
        EventLog(
            conference_id=conference_id,
            participant_id=participant_id,
            type=EventType.SCAN_RESCAN,
            terminal_id=terminal_id,
        )
    )
