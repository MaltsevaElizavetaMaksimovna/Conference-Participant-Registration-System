"""Выборка событий активной конференции."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import full_name
from app.eventlog.schemas import EventOut
from app.models.conference import Conference
from app.models.device import Terminal
from app.models.participant import EventLog, Participant
from app.models.staff import StaffUser


async def list_events(
    session: AsyncSession,
    *,
    type: str | None,
    participant_id: int | None,
    terminal_id: int | None,
    limit: int,
    offset: int,
) -> tuple[list[EventOut], int]:
    """События активной конференции, новые сверху. Нет активной конференции — пусто."""
    conference_id = await session.scalar(select(Conference.id).where(Conference.is_active))
    if conference_id is None:
        return [], 0

    conditions = [EventLog.conference_id == conference_id]
    if type is not None:
        conditions.append(EventLog.type == type)
    if participant_id is not None:
        conditions.append(EventLog.participant_id == participant_id)
    if terminal_id is not None:
        conditions.append(EventLog.terminal_id == terminal_id)

    total = await session.scalar(select(func.count()).select_from(EventLog).where(*conditions))
    rows = await session.execute(
        select(
            EventLog,
            Participant.last_name,
            Participant.first_name,
            Participant.middle_name,
            Terminal.name,
            StaffUser.login,
        )
        .outerjoin(Participant, Participant.id == EventLog.participant_id)
        .outerjoin(Terminal, Terminal.id == EventLog.terminal_id)
        .outerjoin(StaffUser, StaffUser.id == EventLog.user_id)
        .where(*conditions)
        .order_by(EventLog.created_at.desc(), EventLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        EventOut(
            id=ev.id,
            type=ev.type,  # type: ignore[arg-type]
            at=ev.created_at,
            participant_id=ev.participant_id,
            participant_name=full_name(last, first, middle) if last is not None else None,
            terminal_name=terminal_name,
            user_login=login,
            raw_code=ev.raw_code,
            payload=ev.payload,
        )
        for ev, last, first, middle, terminal_name, login in rows
    ]
    return items, total or 0
