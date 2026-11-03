"""Исправление данных участника регистратором (B1-12, RG-06, ER-03, ER-02).

Всё в одной транзакции под блокировкой строки: новые значения, `manual_fields` (их не перезапишет
повторная загрузка, по ним включается пометка «Данные изменены» и шаблон наклейки), запись в
`change_log` (UPDATE/DELETE запрещены триггером), событие `data_changed` и NOTIFY для панели.
Статус регистрации не меняется.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentStaff
from app.core.enums import ChangeSource, EventType
from app.eventlog.notify import notify_participant_updated
from app.models.participant import ChangeLog, EventLog
from app.participants.card import find_active
from app.participants.service import NAME_FIELDS, compute_search_norm


async def update_participant(
    session: AsyncSession,
    participant_id: int,
    changes: dict[str, str | None],
    staff: CurrentStaff,
) -> list[str]:
    """Применить правки (уже проверенные схемой) и закоммитить. Возвращает изменённые поля."""
    p, _ = await find_active(session, participant_id, for_update=True)
    changed = [field for field, value in changes.items() if getattr(p, field) != value]
    if not changed:
        await session.rollback()
        return []

    for field in changed:
        session.add(
            ChangeLog(
                participant_id=p.id,
                field=field,
                old_value=getattr(p, field),
                new_value=changes[field],
                source=ChangeSource.MANUAL,
                user_id=staff.user_id,
            )
        )
        setattr(p, field, changes[field])
    p.manual_fields = [*p.manual_fields, *(f for f in changed if f not in p.manual_fields)]
    if any(field in NAME_FIELDS for field in changed):
        p.search_norm = compute_search_norm(p.last_name, p.first_name, p.middle_name)

    session.add(
        EventLog(
            conference_id=p.conference_id,
            participant_id=p.id,
            type=EventType.DATA_CHANGED,
            user_id=staff.user_id,
            payload={"fields": changed},
        )
    )
    await notify_participant_updated(session, p.id, p.conference_id)
    await session.commit()
    return changed
