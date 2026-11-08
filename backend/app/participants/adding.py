"""Добавление участника, которого нет в списке, с немедленной регистрацией (B1-13, RG-07).

Участник создаётся в той же транзакции, что и регистрация: `registration.service.register`
(место — стойка регистратора) коммитит всё вместе, а при ошибке откатывает и самого участника.
Пометка «Добавлен вручную» (`is_manual_added`) включает и «Данные изменены»: наклейка печатается
по шаблону «Данные изменены» (ER-02).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentStaff
from app.core.enums import EventType, RegSource
from app.core.errors import AppError
from app.core.permissions import Permission
from app.models.conference import Conference
from app.models.participant import EventLog, Participant
from app.models.staff import StaffUser
from app.participants.schemas import ParticipantCreateIn
from app.participants.service import compute_search_norm
from app.registration.result import RegistrationResult
from app.registration.service import register


async def add_participant(
    session: AsyncSession, body: ParticipantCreateIn, staff: CurrentStaff
) -> RegistrationResult:
    if body.with_sticker and not staff.has(Permission.STICKERS_PRINT):
        raise AppError(
            "forbidden", "Недостаточно прав", 403, {"missing": [str(Permission.STICKERS_PRINT)]}
        )
    conference_id = await session.scalar(select(Conference.id).where(Conference.is_active))
    if conference_id is None:
        raise AppError("no_active_conference", "Нет активной конференции", 409)
    printer_id = (
        await session.scalar(
            select(StaffUser.panel_printer_id).where(StaffUser.id == staff.user_id)
        )
        if body.with_sticker
        else None
    )

    participant = Participant(
        conference_id=conference_id,
        external_id=None,
        last_name=body.last_name,
        first_name=body.first_name,
        middle_name=body.middle_name,
        position=body.position,
        organization=body.organization,
        is_manual_added=True,
        search_norm=compute_search_norm(body.last_name, body.first_name, body.middle_name),
    )
    session.add(participant)
    await session.flush()
    session.add(
        EventLog(
            conference_id=conference_id,
            participant_id=participant.id,
            type=EventType.MANUAL_ADDED,
            user_id=staff.user_id,
        )
    )
    result = await register(
        session,
        participant.id,
        source=RegSource.DESK,
        terminal_id=None,
        user_id=staff.user_id,
        with_sticker=body.with_sticker,
        printer_id=printer_id,
    )
    # register меняет строку UPDATE-ом мимо сессии: карточку читаем заново
    session.expire_all()
    return result
