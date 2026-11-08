"""Какие шаблоны печатать участнику (PR-04, ER-02).

- бейдж `none` — ничего; `single` — лицевая сторона; `double` — лицевая и оборотная;
- данные изменены или участник добавлен вручную (`is_data_changed`) — лицевая сторона по
  шаблону «Данные изменены» (`changed`, на нём пометка, обязателен), оборот — `changed_back`,
  а если он не задан, обычный оборот (пометки на обороте может и не быть).

Нужный шаблон не выбран в настройках конференции — `409 template_not_set`: молча печатать
обычную наклейку вместо «Данные изменены» нельзя, сотрудник не увидит пометку.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BadgeType
from app.core.errors import AppError
from app.models.conference import Conference, LabelTemplate
from app.models.participant import Participant
from app.participants.service import is_data_changed


def template_not_set(side: str) -> AppError:
    return AppError(
        "template_not_set",
        "Для конференции не выбран шаблон наклейки",
        409,
        {"side": side},
    )


def template_ids(conference: Conference, data_changed: bool) -> list[tuple[str, int | None]]:
    """(вид, id шаблона) для каждой печатаемой стороны; id None — шаблон не выбран."""
    if conference.badge_type == BadgeType.NONE:
        return []
    if data_changed:
        front = ("changed", conference.changed_template_id)
        back = ("changed_back", conference.changed_back_template_id or conference.back_template_id)
    else:
        front = ("front", conference.front_template_id)
        back = ("back", conference.back_template_id)
    return [front, back] if conference.badge_type == BadgeType.DOUBLE else [front]


async def templates_for(
    session: AsyncSession, participant: Participant, conference: Conference
) -> list[LabelTemplate]:
    """Шаблоны сторон наклейки участника по порядку печати (лицо, затем оборот)."""
    changed = is_data_changed(participant.manual_fields, participant.is_manual_added)
    result = []
    for side, template_id in template_ids(conference, changed):
        tpl = await session.get(LabelTemplate, template_id) if template_id is not None else None
        if tpl is None:
            raise template_not_set(side)
        result.append(tpl)
    return result
