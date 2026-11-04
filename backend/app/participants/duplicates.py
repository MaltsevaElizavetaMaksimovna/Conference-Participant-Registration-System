"""Возможные дубли перед добавлением участника (B1-13, RG-07).

Сравнение в Python: участников конференции не больше ~1000, `pg_trgm` во встроенном PostgreSQL нет.
Похожесть — `difflib.SequenceMatcher` по нормализованным фамилии и имени (lower, ё -> е); дублем
считается участник, у которого похожи и фамилия, и имя, в том числе если их перепутали местами.
"""

from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import full_name, normalize_search
from app.models.conference import Conference
from app.models.participant import Participant
from app.participants.schemas import ParticipantShort
from app.participants.service import participant_flags


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def name_similarity(last: str, first: str, other_last: str, other_first: str) -> float:
    """Похожесть ФИ двух людей: худшая из двух оценок, лучший из двух порядков полей."""
    last, first = normalize_search(last), normalize_search(first)
    other_last, other_first = normalize_search(other_last), normalize_search(other_first)
    direct = min(_ratio(last, other_last), _ratio(first, other_first))
    swapped = min(_ratio(last, other_first), _ratio(first, other_last))
    return max(direct, swapped)


async def find_duplicates(
    session: AsyncSession, last_name: str, first_name: str, *, threshold: float, limit: int
) -> list[ParticipantShort]:
    """Похожие участники активной конференции, самые похожие первыми."""
    people = await session.scalars(
        select(Participant)
        .join(Conference, Conference.id == Participant.conference_id)
        .where(Conference.is_active)
    )
    scored = [
        (score, p)
        for p in people
        if (score := name_similarity(last_name, first_name, p.last_name, p.first_name)) >= threshold
    ]
    scored.sort(key=lambda item: (-item[0], item[1].search_norm, item[1].id))
    return [
        ParticipantShort(
            id=p.id,
            full_name=full_name(p.last_name, p.first_name, p.middle_name),
            organization=p.organization,
            status=p.status,  # type: ignore[arg-type]
            flags=participant_flags(p),
        )
        for _, p in scored[:limit]
    ]
