"""Регистрация и повторная печать на стойке (B2-15)."""

from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentStaff, require_staff
from app.badges.tokens import get_or_create_active_token
from app.core.config import Settings
from app.core.enums import BadgeType, EventType, ParticipantStatus, PrintJobKind, RegSource
from app.core.errors import AppError
from app.core.permissions import Permission
from app.eventlog.notify import notify_participant_updated
from app.models.conference import Conference
from app.models.participant import EventLog, Participant
from app.models.printing import PrintJob
from app.models.staff import StaffUser
from app.participants.actions import DESK_PLACE
from app.participants.card import find_active, get_card, participant_not_found
from app.registration.foreign_code import no_badge, printer_not_selected
from app.registration.messages import format_registered_at
from app.registration.result import make_store_key
from app.registration.schemas import RegisterOut
from app.registration.service import register

_require_print = require_staff(Permission.STICKERS_PRINT)


async def _lock_active_conference(session: AsyncSession, participant_id: int) -> str:
    # FOR SHARE не даёт сменить активную конференцию до завершения операции.
    badge_type = await session.scalar(
        select(Conference.badge_type)
        .join(Participant, Participant.conference_id == Conference.id)
        .where(Participant.id == participant_id, Conference.is_active)
        .with_for_update(read=True, of=Conference)
    )
    if badge_type is None:
        raise participant_not_found()
    return badge_type


async def _panel_printer(session: AsyncSession, user_id: int) -> int | None:
    return await session.scalar(select(StaffUser.panel_printer_id).where(StaffUser.id == user_id))


async def register_at_desk(
    session: AsyncSession,
    participant_id: int,
    current: CurrentStaff,
    *,
    with_sticker: bool,
    settings: Settings,
) -> RegisterOut:
    try:
        result = await _register_at_desk(session, participant_id, current, with_sticker, settings)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return result


async def _register_at_desk(
    session: AsyncSession,
    participant_id: int,
    current: CurrentStaff,
    with_sticker: bool,
    settings: Settings,
) -> RegisterOut:
    badge_type = await _lock_active_conference(session, participant_id)
    needs_sticker = with_sticker and badge_type != BadgeType.NONE
    printer_id = None
    if needs_sticker:
        await _require_print(current)
        printer_id = await _panel_printer(session, current.user_id)

    result = await register(
        session,
        participant_id,
        source=RegSource.DESK,
        terminal_id=None,
        user_id=current.user_id,
        with_sticker=needs_sticker,
        printer_id=printer_id,
        commit=False,
    )
    if result.result == "already_registered":
        at = format_registered_at(result.registered_at, ZoneInfo(settings.timezone))
        place = result.terminal_name or DESK_PLACE
        raise AppError(
            "already_registered",
            f"Участник уже зарегистрирован {at}, {place}",
            409,
            {
                "registered_at": result.registered_at.isoformat(),
                "source": result.source,
                "terminal_name": result.terminal_name,
                "user_login": result.user_login,
            },
        )
    card = await get_card(session, participant_id, current, settings)
    return RegisterOut(participant=card, print_job_id=result.print_job_id)


async def reprint_at_desk(
    session: AsyncSession,
    participant_id: int,
    user_id: int,
    *,
    idempotency_key: str | None = None,
) -> int:
    try:
        job_id = await _queue_reprint(session, participant_id, user_id, idempotency_key)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return job_id


async def _queue_reprint(
    session: AsyncSession, participant_id: int, user_id: int, idempotency_key: str | None
) -> int:
    await _lock_active_conference(session, participant_id)
    participant, badge_type = await find_active(session, participant_id, for_update=True)
    store_key = None
    if idempotency_key is not None:
        # Блокировка участника сериализует повторы в этой области ключа.
        store_key = make_store_key(f"reprint:{user_id}:{participant_id}", idempotency_key)
        existing = await session.scalar(
            select(PrintJob.id).where(PrintJob.idempotency_key == store_key)
        )
        if existing is not None:
            return existing

    if participant.status == ParticipantStatus.NOT_REGISTERED:
        raise AppError("not_registered", "Участник ещё не зарегистрирован", 409)
    if badge_type == BadgeType.NONE:
        raise no_badge()
    printer_id = await _panel_printer(session, user_id)
    if printer_id is None:
        raise printer_not_selected()

    token = await get_or_create_active_token(session, participant.id)
    job = PrintJob(
        conference_id=participant.conference_id,
        participant_id=participant.id,
        badge_token_id=token.id,
        printer_id=printer_id,
        kind=PrintJobKind.REPRINT,
        sides=2 if badge_type == BadgeType.DOUBLE else 1,
        created_by_user_id=user_id,
        idempotency_key=store_key,
    )
    session.add(job)
    await session.flush()
    session.add(
        EventLog(
            conference_id=participant.conference_id,
            participant_id=participant.id,
            type=EventType.REPRINT,
            user_id=user_id,
            payload={"printer_id": printer_id, "job_id": job.id},
        )
    )
    await notify_participant_updated(session, participant.id, participant.conference_id)
    return job.id
