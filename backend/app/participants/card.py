"""Карточка участника (B1-12, RG-03): данные, регистрация, пометки, история, события, действия.

Карточка доступна только для участников активной конференции, как и список.
"""

from collections.abc import Iterable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentStaff
from app.badges.service import resolve_photo
from app.core.config import Settings
from app.core.enums import BadgeTokenStatus, ParticipantStatus
from app.core.errors import AppError
from app.models.conference import Conference, ExtraFieldDef
from app.models.device import Terminal
from app.models.participant import BadgeToken, ChangeLog, EventLog, Participant
from app.models.staff import StaffUser
from app.participants.actions import card_actions
from app.participants.schemas import (
    EventItem,
    ExtraField,
    FlagInfo,
    HistoryItem,
    ParticipantCard,
    ParticipantFlag,
    RegistrationInfo,
)
from app.participants.service import participant_flags


def participant_not_found() -> AppError:
    return AppError("participant_not_found", "Участник не найден", 404)


async def find_active(
    session: AsyncSession, participant_id: int, *, for_update: bool = False
) -> tuple[Participant, str]:
    """Участник активной конференции и тип бейджа конференции; иначе 404."""
    stmt = (
        select(Participant, Conference.badge_type)
        .join(Conference, Conference.id == Participant.conference_id)
        .where(Participant.id == participant_id, Conference.is_active)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Participant)
    row = (await session.execute(stmt)).first()
    if row is None:
        raise participant_not_found()
    return row[0], row[1]


async def _logins(session: AsyncSession, ids: Iterable[int | None]) -> dict[int, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await session.execute(
        select(StaffUser.id, StaffUser.login).where(StaffUser.id.in_(wanted))
    )
    return {uid: login for uid, login in rows}


async def _events(session: AsyncSession, participant_id: int) -> list[EventItem]:
    rows = await session.execute(
        select(EventLog.type, EventLog.created_at, Terminal.name, StaffUser.login)
        .outerjoin(Terminal, Terminal.id == EventLog.terminal_id)
        .outerjoin(StaffUser, StaffUser.id == EventLog.user_id)
        .where(EventLog.participant_id == participant_id)
        .order_by(EventLog.created_at, EventLog.id)
    )
    return [
        EventItem(type=type_, at=at, terminal_name=terminal, user_login=login)  # type: ignore[arg-type]
        for type_, at, terminal, login in rows
    ]


async def _history(session: AsyncSession, participant_id: int) -> list[HistoryItem]:
    rows = await session.execute(
        select(ChangeLog, StaffUser.login)
        .outerjoin(StaffUser, StaffUser.id == ChangeLog.user_id)
        .where(ChangeLog.participant_id == participant_id)
        .order_by(ChangeLog.created_at, ChangeLog.id)
    )
    return [
        HistoryItem(
            field=ch.field,
            old=ch.old_value,
            new=ch.new_value,
            source=ch.source,  # type: ignore[arg-type]
            user_login=login,
            at=ch.created_at,
        )
        for ch, login in rows
    ]


async def _extra(session: AsyncSession, p: Participant) -> list[ExtraField]:
    defs = await session.scalars(
        select(ExtraFieldDef)
        .where(ExtraFieldDef.conference_id == p.conference_id)
        .order_by(ExtraFieldDef.sort_order, ExtraFieldDef.id)
    )
    values = p.extra or {}
    return [
        ExtraField(
            key=d.key,
            label=d.label,
            value=None if values.get(d.key) is None else str(values[d.key]),
        )
        for d in defs
    ]


def _flags(
    p: Participant,
    events: list[EventItem],
    history: list[HistoryItem],
    logins: dict[int, str],
) -> list[FlagInfo]:
    """Пометки с временем и автором: из полей участника, журнала изменений и событий."""
    last_manual = next((h for h in reversed(history) if h.source == "manual"), None)
    last_print_error = next((e.at for e in reversed(events) if e.type == "print_error"), None)
    reg_login = logins.get(p.reg_user_id) if p.reg_user_id is not None else None
    foreign_login = logins.get(p.foreign_code_by) if p.foreign_code_by is not None else None
    sources: dict[ParticipantFlag, tuple[datetime | None, str | None]] = {
        "error_reported": (p.error_reported_at, None),
        "sticker_not_printed": (last_print_error or p.registered_at, None),
        "data_changed": (
            (last_manual.at, last_manual.user_login) if last_manual else (p.created_at, reg_login)
        ),
        "manual_added": (p.created_at, reg_login),
        "foreign_code": (p.foreign_code_at, foreign_login),
    }
    return [
        FlagInfo(code=code, at=sources[code][0] or p.updated_at, by=sources[code][1])
        for code in participant_flags(p)
    ]


async def get_card(
    session: AsyncSession, participant_id: int, staff: CurrentStaff, settings: Settings
) -> ParticipantCard:
    p, badge_type = await find_active(session, participant_id)
    events = await _events(session, p.id)
    history = await _history(session, p.id)
    logins = await _logins(session, (p.reg_user_id, p.foreign_code_by))

    registration = None
    if p.status != ParticipantStatus.NOT_REGISTERED and p.registered_at is not None:
        terminal_name = (
            await session.scalar(select(Terminal.name).where(Terminal.id == p.reg_terminal_id))
            if p.reg_terminal_id is not None
            else None
        )
        registration = RegistrationInfo(
            at=p.registered_at,
            source=p.reg_source or "terminal",  # type: ignore[arg-type]
            terminal_name=terminal_name,
            user_login=logins.get(p.reg_user_id) if p.reg_user_id is not None else None,
        )

    token = await session.scalar(
        select(BadgeToken.token).where(
            BadgeToken.participant_id == p.id, BadgeToken.status == BadgeTokenStatus.ACTIVE
        )
    )
    base_url = (settings.public_base_url or "").rstrip("/")
    has_photo = resolve_photo(settings.photo_dir, p.photo_path) is not None

    return ParticipantCard(
        id=p.id,
        external_id=p.external_id,
        last_name=p.last_name,
        first_name=p.first_name,
        middle_name=p.middle_name,
        position=p.position,
        organization=p.organization,
        last_name_en=p.last_name_en,
        first_name_en=p.first_name_en,
        middle_name_en=p.middle_name_en,
        position_en=p.position_en,
        organization_en=p.organization_en,
        extra=await _extra(session, p),
        status=p.status,  # type: ignore[arg-type]
        registration=registration,
        flags=_flags(p, events, history, logins),
        photo_url=f"/api/participants/{p.id}/photo" if has_photo else None,
        profile_url=f"{base_url}/p/{token}" if base_url and token else None,
        print_count=p.print_count,
        rescan_count=p.rescan_count,
        history=history,
        events=events,
        actions=card_actions(badge_type, staff, registration, ZoneInfo(settings.timezone)),
    )
