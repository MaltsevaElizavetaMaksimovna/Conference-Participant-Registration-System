"""Рендер задания печати в наклейки для агента (B2-11, TR-04, PR-04, ER-02, QR-01)."""

import asyncio
import base64

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.render.data import SAMPLE, LabelData, label_data, profile_url
from app.badges.render.label import render_label, to_png
from app.badges.render.select import templates_for
from app.core.config import Settings
from app.core.enums import BadgeTokenStatus, PrintJobKind
from app.core.errors import AppError
from app.models.conference import Conference, LabelTemplate
from app.models.device import Printer
from app.models.participant import BadgeToken, Participant
from app.models.printing import PrintJob
from app.printing.schemas import AgentJobCopy
from app.templates.service import template_spec


def _render_copies(templates: list[LabelTemplate], data: LabelData, dpi: int) -> list[AgentJobCopy]:
    """Сборка и рисование наклеек (CPU-bound операция)."""
    copies: list[AgentJobCopy] = []
    for tpl in templates:
        spec = template_spec(tpl)
        rendered = render_label(spec, data, dpi=dpi)
        png_bytes = to_png(rendered.image, dpi=dpi)
        png_base64 = base64.b64encode(png_bytes).decode("ascii")
        copies.append(
            AgentJobCopy(
                png_base64=png_base64,
                width_mm=spec.width_mm,
                height_mm=spec.height_mm,
                gap_mm=spec.gap_mm,
            )
        )
    return copies


async def render_job(
    session: AsyncSession, settings: Settings, job: PrintJob, printer: Printer
) -> list[AgentJobCopy]:
    """Наклейки задания по порядку печати (лицо, затем оборот). AppError — задание не напечатать."""
    templates: list[LabelTemplate]
    data: LabelData

    if job.kind == PrintJobKind.TEST:
        if job.template_id is None:
            raise AppError(
                "template_not_set",
                "Для конференции не выбран шаблон наклейки",
                409,
                {"side": "test"},
            )
        tpl = await session.get(LabelTemplate, job.template_id)
        if tpl is None:
            raise AppError(
                "template_not_set",
                "Для конференции не выбран шаблон наклейки",
                409,
                {"side": "test"},
            )
        templates = [tpl]

        participant: Participant | None = None
        if job.participant_id is not None:
            participant = await session.get(Participant, job.participant_id)

        if participant is not None:
            token_record: BadgeToken | None = None
            if job.badge_token_id is not None:
                token_record = await session.get(BadgeToken, job.badge_token_id)
            if token_record is None or token_record.status != BadgeTokenStatus.ACTIVE:
                token_record = await session.scalar(
                    select(BadgeToken).where(
                        BadgeToken.participant_id == participant.id,
                        BadgeToken.status == BadgeTokenStatus.ACTIVE,
                    )
                )

            token_str = token_record.token if token_record is not None else None
            url: str | None
            if token_str and settings.public_base_url:
                url = profile_url(settings.public_base_url, token_str)
            else:
                url = SAMPLE.profile_url
            data = label_data(participant, url)
        else:
            data = SAMPLE

    else:
        if job.participant_id is None:
            raise AppError("participant_not_found", "Участник не найден", 404)
        participant = await session.get(Participant, job.participant_id)
        if participant is None:
            raise AppError("participant_not_found", "Участник не найден", 404)

        conference = await session.get(Conference, job.conference_id)
        if conference is None:
            raise AppError("conference_not_found", "Конференция не найдена", 404)

        templates = await templates_for(session, participant, conference)
        if not templates:
            raise AppError("no_badge", "В конференции без бейджа наклейки не печатаются", 409)

        token_record = None
        if job.badge_token_id is not None:
            token_record = await session.get(BadgeToken, job.badge_token_id)
        else:
            token_record = await session.scalar(
                select(BadgeToken).where(
                    BadgeToken.participant_id == participant.id,
                    BadgeToken.status == BadgeTokenStatus.ACTIVE,
                )
            )

        if token_record is None:
            raise AppError("badge_token_missing", "У участника нет кода бейджа", 409)

        if not settings.public_base_url:
            raise AppError(
                "public_base_url_not_set",
                "Не задан публичный адрес системы RS_PUBLIC_BASE_URL",
                409,
            )

        url = profile_url(settings.public_base_url, token_record.token)
        data = label_data(participant, url)

    return await asyncio.to_thread(_render_copies, templates, data, printer.dpi)
