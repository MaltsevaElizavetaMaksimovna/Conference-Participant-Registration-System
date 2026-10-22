"""Конференции (AD-01): CRUD, привязка шаблонов, атомарная активация.

Одновременно активна одна конференция (частичный уникальный индекс `uq_conference_single_active`);
данные прошлых конференций не удаляются: DELETE в API нет.
TODO B2-07: копирование шаблонов из прошлой конференции при создании новой.
"""

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.conferences.schemas import ActiveConferenceOut, ConferenceIn, ConferenceOut
from app.core.enums import TemplateKind
from app.core.errors import AppError
from app.models.base import utcnow
from app.models.conference import Conference, LabelTemplate
from app.models.participant import Participant

# Ключ advisory-lock активации (произвольная константа проекта)
_ACTIVATE_LOCK = 0x52_53_43_46  # "RSCF"

# Поле конференции -> вид шаблона, который в него можно привязать
TEMPLATE_FIELDS: dict[str, TemplateKind] = {
    "front_template_id": TemplateKind.FRONT,
    "back_template_id": TemplateKind.BACK,
    "changed_template_id": TemplateKind.CHANGED,
    "changed_back_template_id": TemplateKind.CHANGED_BACK,
}


def conference_not_found() -> AppError:
    return AppError("conference_not_found", "Конференция не найдена", 404)


def _out(conf: Conference, participants_total: int) -> ConferenceOut:
    return ConferenceOut(
        id=conf.id,
        title=conf.title,
        date_from=conf.date_from,
        date_to=conf.date_to,
        badge_type=conf.badge_type,  # type: ignore[arg-type]
        front_template_id=conf.front_template_id,
        back_template_id=conf.back_template_id,
        changed_template_id=conf.changed_template_id,
        changed_back_template_id=conf.changed_back_template_id,
        invite_id_regex=conf.invite_id_regex,
        is_active=conf.is_active,
        participants_total=participants_total,
        created_at=conf.created_at,
    )


async def _participants_total(session: AsyncSession, conference_id: int) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Participant)
            .where(Participant.conference_id == conference_id)
        )
        or 0
    )


async def list_conferences(
    session: AsyncSession, limit: int, offset: int
) -> tuple[list[ConferenceOut], int]:
    total = await session.scalar(select(func.count()).select_from(Conference)) or 0
    confs = list(
        await session.scalars(
            select(Conference).order_by(Conference.id.desc()).limit(limit).offset(offset)
        )
    )
    counts: dict[int, int] = {}
    if confs:
        rows = await session.execute(
            select(Participant.conference_id, func.count())
            .where(Participant.conference_id.in_([c.id for c in confs]))
            .group_by(Participant.conference_id)
        )
        counts = {cid: n for cid, n in rows}
    return [_out(c, counts.get(c.id, 0)) for c in confs], total


async def _check_templates(
    session: AsyncSession, conference_id: int | None, body: ConferenceIn
) -> None:
    """Шаблон должен существовать, принадлежать этой конференции и иметь нужный `kind`."""
    wanted = {f: v for f in TEMPLATE_FIELDS if (v := getattr(body, f)) is not None}
    if not wanted:
        return
    if conference_id is None:
        raise AppError(
            "validation_error",
            "Некорректные данные запроса",
            422,
            {"fields": {f: "Шаблоны можно привязать после создания конференции" for f in wanted}},
        )
    found = {
        t.id: t
        for t in await session.scalars(
            select(LabelTemplate).where(LabelTemplate.id.in_(set(wanted.values())))
        )
    }
    fields: dict[str, str] = {}
    for field, tid in wanted.items():
        tpl = found.get(tid)
        if tpl is None or tpl.conference_id != conference_id:
            fields[field] = "Шаблон не найден в этой конференции"
        elif tpl.kind != TEMPLATE_FIELDS[field].value:
            fields[field] = f"Нужен шаблон вида «{TEMPLATE_FIELDS[field].value}»"
    if fields:
        raise AppError("validation_error", "Некорректные данные запроса", 422, {"fields": fields})


def _apply(conf: Conference, body: ConferenceIn) -> None:
    data: dict[str, Any] = body.model_dump()
    for key, value in data.items():
        setattr(conf, key, value)


async def create_conference(session: AsyncSession, body: ConferenceIn) -> ConferenceOut:
    await _check_templates(session, None, body)
    conf = Conference(is_active=False)
    _apply(conf, body)
    session.add(conf)
    await session.commit()
    return _out(conf, 0)


async def _get(session: AsyncSession, conference_id: int) -> Conference:
    conf = await session.get(Conference, conference_id, populate_existing=True)
    if conf is None:
        await session.rollback()
        raise conference_not_found()
    return conf


async def get_conference(session: AsyncSession, conference_id: int) -> ConferenceOut:
    conf = await session.get(Conference, conference_id, populate_existing=True)
    if conf is None:
        raise conference_not_found()
    return _out(conf, await _participants_total(session, conference_id))


async def get_active(session: AsyncSession) -> ActiveConferenceOut | None:
    """Активная конференция или None, если ни одна не активирована."""
    conf = await session.scalar(select(Conference).where(Conference.is_active.is_(True)))
    if conf is None:
        return None
    return ActiveConferenceOut(
        id=conf.id,
        title=conf.title,
        date_from=conf.date_from,
        date_to=conf.date_to,
        badge_type=conf.badge_type,  # type: ignore[arg-type]
    )


async def update_conference(
    session: AsyncSession, conference_id: int, body: ConferenceIn
) -> ConferenceOut:
    conf = await _get(session, conference_id)
    try:
        await _check_templates(session, conference_id, body)
    except AppError:
        await session.rollback()
        raise
    _apply(conf, body)
    conf.updated_at = utcnow()
    await session.commit()
    return _out(conf, await _participants_total(session, conference_id))


async def activate_conference(session: AsyncSession, conference_id: int) -> ConferenceOut:
    """Атомарно: снимает активность с остальных и включает эту (одна транзакция)."""
    await session.execute(select(func.pg_advisory_xact_lock(_ACTIVATE_LOCK)))
    conf = await _get(session, conference_id)
    # Сначала снимаем: уникальный индекс проверяется после каждого оператора
    await session.execute(
        update(Conference)
        .where(Conference.is_active.is_(True), Conference.id != conference_id)
        .values(is_active=False, updated_at=utcnow())
    )
    if not conf.is_active:
        conf.is_active = True
        conf.updated_at = utcnow()
    await session.commit()
    return _out(conf, await _participants_total(session, conference_id))
