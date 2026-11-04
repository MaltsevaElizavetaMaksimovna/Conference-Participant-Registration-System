"""Предпросмотр, проверка переполнения и пробная печать шаблона (B2-09, PR-02, PR-03)."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.render.data import SAMPLE, LabelData, label_data, profile_url
from app.badges.render.label import DPI, element_box, render_label, to_png
from app.badges.render.text_fit import overflows
from app.core.config import Settings
from app.core.enums import BadgeTokenStatus, PrintJobKind, PrintJobStatus
from app.core.errors import AppError
from app.models.device import Printer
from app.models.participant import BadgeToken, Participant
from app.models.printing import PrintJob
from app.templates.schemas import OverflowItem, TemplateIn, TemplateTestPrintIn
from app.templates.service import get_template, template_spec


def participant_not_found() -> AppError:
    return AppError("participant_not_found", "Участник не найден", 404)


def printer_not_found() -> AppError:
    return AppError("printer_not_found", "Принтер не найден", 404)


async def _participant(
    session: AsyncSession, conference_id: int, participant_id: int
) -> Participant:
    p = await session.get(Participant, participant_id)
    if p is None or p.conference_id != conference_id:
        raise participant_not_found()
    return p


async def _preview_data(
    session: AsyncSession, settings: Settings, participant: Participant
) -> LabelData:
    """Данные участника; QR — его действующий код, а если кода ещё нет — образец.

    Предпросмотр код бейджа не создаёт: код выдаётся только при регистрации (QR-01).
    """
    token = await session.scalar(
        select(BadgeToken.token).where(
            BadgeToken.participant_id == participant.id,
            BadgeToken.status == BadgeTokenStatus.ACTIVE,
        )
    )
    url = SAMPLE.profile_url
    if token and settings.public_base_url:
        url = profile_url(settings.public_base_url, token)
    return label_data(participant, url)


async def preview_png(
    session: AsyncSession,
    settings: Settings,
    conference_id: int,
    template_id: int,
    participant_id: int | None,
) -> bytes:
    """PNG наклейки на данных участника или на образце (PR-02)."""
    spec = template_spec(await get_template(session, conference_id, template_id))
    data = SAMPLE
    if participant_id is not None:
        participant = await _participant(session, conference_id, participant_id)
        data = await _preview_data(session, settings, participant)
    return await asyncio.to_thread(lambda: to_png(render_label(spec, data).image))


def _overflow_items(spec: TemplateIn, people: list[tuple[int, LabelData]]) -> list[OverflowItem]:
    """Кто не помещается даже минимальным кеглем. Без рисования: только раскладка текста.

    Одинаковые значения (часто — организация) раскладываются один раз.
    """
    fields = [
        (el, element_box(spec, el)) for el in spec.elements if el.type == "field" and el.field
    ]
    cache: dict[tuple[int, str], bool] = {}
    items = []
    for participant_id, data in people:
        for i, (el, (_, _, w, h)) in enumerate(fields):
            value = data.value(el.field or "")
            if not value or w <= 0 or h <= 0:
                continue
            key = (i, value)
            if key not in cache:
                cache[key] = overflows(
                    value,
                    w,
                    h,
                    min_font_size=el.min_font_size,
                    max_lines=el.max_lines,
                    bold=el.bold,
                    dpi=DPI,
                )
            if cache[key]:
                items.append(
                    OverflowItem(
                        participant_id=participant_id,
                        full_name=data.value("full_name"),
                        field=el.field or "",
                        value=value,
                    )
                )
    return items


async def spec_overflow(
    session: AsyncSession, conference_id: int, spec: TemplateIn
) -> list[OverflowItem]:
    """Переполнение шаблона по всем участникам конференции, по алфавиту (PR-03).

    Постоянный текст (`type=text`) не проверяется: он одинаков у всех участников.
    """
    rows = await session.scalars(
        select(Participant)
        .where(Participant.conference_id == conference_id)
        .order_by(Participant.last_name, Participant.first_name, Participant.id)
    )
    people = [(p.id, label_data(p, None)) for p in rows]
    # Раскладка текста — работа процессора: не держим цикл событий
    return await asyncio.to_thread(_overflow_items, spec, people)


async def template_overflow(
    session: AsyncSession, conference_id: int, template_id: int
) -> list[OverflowItem]:
    spec = template_spec(await get_template(session, conference_id, template_id))
    return await spec_overflow(session, conference_id, spec)


async def create_test_print(
    session: AsyncSession,
    conference_id: int,
    template_id: int,
    body: TemplateTestPrintIn,
    user_id: int,
) -> int:
    """Задание `kind=test` (PR-02): участника не регистрирует и его статус не меняет.

    Наклейку агент получит по шаблону задания в момент выдачи (B2-11): данными участника
    `participant_id` или образцом, если он не указан.
    """
    await get_template(session, conference_id, template_id)
    if body.participant_id is not None:
        await _participant(session, conference_id, body.participant_id)
    if await session.get(Printer, body.printer_id) is None:
        raise printer_not_found()
    job = PrintJob(
        conference_id=conference_id,
        participant_id=body.participant_id,
        printer_id=body.printer_id,
        kind=PrintJobKind.TEST,
        sides=1,
        template_id=template_id,
        status=PrintJobStatus.PENDING,
        created_by_user_id=user_id,
    )
    session.add(job)
    await session.commit()
    return job.id
