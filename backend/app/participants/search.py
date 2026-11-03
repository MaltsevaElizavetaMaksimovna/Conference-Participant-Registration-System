"""Список, поиск и счётчик участников активной конференции (B1-09, B1-10, RG-02, RG-04).

Поиск идёт по `search_norm` («фамилия имя отчество», lower, ё -> е): запрос разбивается на
слова, каждое ищется как часть слова через LIKE, условия объединяются по И.
"""

from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ParticipantStatus
from app.core.text import full_name, normalize_search
from app.models.conference import Conference
from app.models.participant import Participant
from app.participants.schemas import (
    ParticipantFilter,
    ParticipantShort,
    ParticipantSort,
    ParticipantStats,
)
from app.participants.service import participant_flags


def search_tokens(q: str | None, min_chars: int) -> list[str]:
    """Слова запроса; короче `min_chars` (без учёта пробелов по краям) — поиска нет."""
    norm = normalize_search(q or "")
    if len(norm) < min_chars:
        return []
    return norm.split(" ")


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _is_registered() -> ColumnElement[bool]:
    return Participant.status != ParticipantStatus.NOT_REGISTERED


def _filter_condition(filter: ParticipantFilter) -> ColumnElement[bool] | None:
    match filter:
        case "registered":
            return _is_registered()
        case "not_registered":
            return Participant.status == ParticipantStatus.NOT_REGISTERED
        case "flagged":
            return or_(
                Participant.error_reported_at.is_not(None),
                Participant.sticker_not_printed,
                func.cardinality(Participant.manual_fields) > 0,
                Participant.is_manual_added,
                Participant.foreign_code_at.is_not(None),
            )
    return None


def _order_by(sort: ParticipantSort) -> list[ColumnElement[Any]]:
    by_name: list[ColumnElement[Any]] = [Participant.search_norm.asc(), Participant.id.asc()]
    match sort:
        case "registered_at":
            return [Participant.registered_at.asc().nulls_last(), *by_name]
        case "-registered_at":
            return [Participant.registered_at.desc().nulls_last(), *by_name]
    return by_name


async def list_participants(
    session: AsyncSession,
    *,
    q: str | None,
    filter: ParticipantFilter,
    sort: ParticipantSort,
    limit: int,
    offset: int,
    min_chars: int,
) -> tuple[list[ParticipantShort], int]:
    """Страница участников активной конференции. Нет активной конференции — пусто."""
    conference_id = await session.scalar(select(Conference.id).where(Conference.is_active))
    if conference_id is None:
        return [], 0

    conditions: list[ColumnElement[bool]] = [Participant.conference_id == conference_id]
    conditions += [
        Participant.search_norm.like(f"%{_escape_like(token)}%", escape="\\")
        for token in search_tokens(q, min_chars)
    ]
    if (condition := _filter_condition(filter)) is not None:
        conditions.append(condition)

    total = await session.scalar(select(func.count()).select_from(Participant).where(*conditions))
    rows = await session.scalars(
        select(Participant)
        .where(*conditions)
        .order_by(*_order_by(sort))
        .limit(limit)
        .offset(offset)
    )
    items = [
        ParticipantShort(
            id=p.id,
            full_name=full_name(p.last_name, p.first_name, p.middle_name),
            organization=p.organization,
            status=p.status,  # type: ignore[arg-type]
            flags=participant_flags(p),
        )
        for p in rows
    ]
    return items, total or 0


async def participant_stats(session: AsyncSession) -> ParticipantStats:
    """Счётчик «Зарегистрировано X из Y» активной конференции (RG-04). Нет активной — 0 из 0.

    `registered` совпадает с `total` списка при `filter=registered`.
    """
    row = (
        await session.execute(
            select(func.count(), func.count().filter(_is_registered()))
            .select_from(Participant)
            .join(Conference, Conference.id == Participant.conference_id)
            .where(Conference.is_active)
        )
    ).one()
    return ParticipantStats(total=row[0], registered=row[1])
