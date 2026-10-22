"""Сканирование на терминале (B2-03): TR-01, TR-02, TR-07, DP-01.

Ничего, кроме журнала событий и счётчика повторов, этот модуль не меняет. Регистрирует
только `app.registration.service.register` (см. `confirm_flow`).
"""

from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import EventType, ParticipantStatus
from app.core.text import full_name
from app.models.conference import Conference
from app.models.participant import EventLog, Participant
from app.registration import messages
from app.registration.rescan import record_rescan
from app.terminals.deps import CurrentTerminal
from app.terminals.scan_code import extract_invite_id, is_badge_link, normalize_scan
from app.terminals.scan_id import issue_scan_id
from app.terminals.schemas import ScanAlreadyRegistered, ScanFound, ScanNotFound, ScanParticipant

_RAW_CODE_MAX = 2000

_SCAN_COLUMNS = (
    Participant.id,
    Participant.status,
    Participant.registered_at,
    Participant.last_name,
    Participant.first_name,
    Participant.middle_name,
    Participant.position,
    Participant.organization,
)


async def scan(
    session: AsyncSession, terminal: CurrentTerminal, raw: str, settings: Settings
) -> ScanFound | ScanNotFound | ScanAlreadyRegistered:
    conference = (
        await session.execute(
            select(Conference.id, Conference.invite_id_regex).where(Conference.is_active)
        )
    ).first()
    normalized = normalize_scan(raw)

    row = None
    if conference is not None and not is_badge_link(normalized, settings.public_base_url):
        # Регулярка конференции главнее общей из настроек
        pattern = conference.invite_id_regex or settings.invite_id_regex or None
        invite_id = extract_invite_id(normalized, pattern)
        if invite_id is not None:
            row = await _find_participant(session, conference.id, invite_id)

    if row is None:
        # TR-07: ничего не меняем, кроме журнала (время, терминал, считанный код)
        session.add(
            EventLog(
                conference_id=conference.id if conference else None,
                type=EventType.SCAN_NOT_FOUND,
                terminal_id=terminal.terminal_id,
                raw_code=raw[:_RAW_CODE_MAX],
                payload={} if normalized == raw else {"normalized": normalized[:_RAW_CODE_MAX]},
            )
        )
        await session.commit()
        return ScanNotFound(result="not_found", message=messages.NOT_FOUND)

    assert conference is not None
    if row.status != ParticipantStatus.NOT_REGISTERED:
        # DP-01: попытка запоминается в карточке (счётчик + событие со временем и терминалом)
        await record_rescan(session, row.id, conference.id, terminal.terminal_id)
        await session.commit()
        assert row.registered_at is not None
        tz = ZoneInfo(settings.timezone)
        return ScanAlreadyRegistered(
            result="already_registered",
            message=messages.already_registered(row.registered_at, tz),
        )

    return ScanFound(
        result="found",
        scan_id=issue_scan_id(settings.secret_key, terminal.terminal_id, row.id),
        participant=ScanParticipant(
            id=row.id,
            # Ровно то, что попадёт на наклейку (TR-02)
            full_name=full_name(row.last_name, row.first_name, row.middle_name),
            position=(row.position or "").strip() or messages.NOT_SPECIFIED,
            organization=(row.organization or "").strip() or messages.NOT_SPECIFIED,
        ),
    )


async def _find_participant(session: AsyncSession, conference_id: int, invite_id: str) -> Any:
    """По `external_id`: точно, иначе без учёта регистра, если совпадение единственное.

    Второе нужно на случай CapsLock на сканере. Если без учёта регистра подходят двое
    (`ab1` и `AB1`), выбирать нельзя, и точное совпадение — единственный честный ответ.
    Выбираются колонки, а не сущность: так не мешает устаревший объект в identity map.
    """
    exact = (
        await session.execute(
            select(*_SCAN_COLUMNS).where(
                Participant.conference_id == conference_id, Participant.external_id == invite_id
            )
        )
    ).first()
    if exact is not None:
        return exact
    similar = (
        await session.execute(
            select(*_SCAN_COLUMNS)
            .where(
                Participant.conference_id == conference_id,
                func.lower(Participant.external_id) == invite_id.lower(),
            )
            .limit(2)
        )
    ).all()
    return similar[0] if len(similar) == 1 else None
