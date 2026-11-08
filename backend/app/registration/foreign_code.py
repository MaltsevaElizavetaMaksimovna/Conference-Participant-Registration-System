"""Регистрация по чужому коду (B2-14, QR-03).

По QR участника зарегистрировался другой человек. Регистратор сверил личность по фото и
отмечает это. В ОДНОЙ транзакции, под блокировкой строки участника:

1. действующий код бейджа отзывается навсегда (ссылка с наклейки самозванца → «Бейдж
   аннулирован», вернуть её нельзя: отозванный код больше никогда не станет действующим);
2. выдаётся новый случайный код;
3. ставится пометка «Зарегистрирован по чужому коду» (время, сотрудник) и событие журнала;
4. на принтер панели сотрудника ставится наклейка с новым QR (`kind=foreign`).

Статус, время и место первой регистрации не меняются: регистрация остаётся одной.
Принтер в панели не выбран — `409 printer_not_selected`, и ничего не меняется: иначе код
был бы отозван, а новой наклейки не было бы. В конференции «без бейджа» QR не печатается,
регистрироваться по нему нельзя — `409 no_badge`.
"""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.tokens import new_badge_token
from app.core.enums import (
    BadgeTokenStatus,
    BadgeType,
    EventType,
    ParticipantStatus,
    PrintJobKind,
    PrintJobStatus,
)
from app.core.errors import AppError
from app.eventlog.notify import notify_participant_updated
from app.models.participant import BadgeToken, EventLog
from app.models.printing import PrintJob
from app.models.staff import StaffUser
from app.participants.card import find_active


def not_registered() -> AppError:
    return AppError("participant_not_registered", "Участник ещё не зарегистрирован", 409)


def no_badge() -> AppError:
    return AppError("no_badge", "В конференции без бейджа нет QR-кодов на наклейках", 409)


def printer_not_selected() -> AppError:
    return AppError(
        "printer_not_selected", "Выберите принтер в панели, чтобы напечатать наклейку", 409
    )


async def register_foreign_code(session: AsyncSession, participant_id: int, user_id: int) -> int:
    """Отметить регистрацию по чужому коду. Возвращает id задания печати новой наклейки.

    Транзакцию завершает сама (commit или rollback).
    """
    try:
        job_id = await _foreign_code(session, participant_id, user_id)
    except Exception:
        await session.rollback()
        raise
    await session.commit()
    return job_id


async def _foreign_code(session: AsyncSession, participant_id: int, user_id: int) -> int:
    # Блокировка строки: два одновременных нажатия выполняются по очереди
    participant, badge_type = await find_active(session, participant_id, for_update=True)
    if participant.status == ParticipantStatus.NOT_REGISTERED:
        raise not_registered()

    if badge_type == BadgeType.NONE:
        raise no_badge()
    printer_id = await session.scalar(
        select(StaffUser.panel_printer_id).where(StaffUser.id == user_id)
    )
    if printer_id is None:
        raise printer_not_selected()

    await session.execute(
        update(BadgeToken)
        .where(
            BadgeToken.participant_id == participant.id,
            BadgeToken.status == BadgeTokenStatus.ACTIVE,
        )
        .values(
            status=BadgeTokenStatus.REVOKED, revoked_at=func.clock_timestamp(), revoked_by=user_id
        )
        .execution_options(synchronize_session=False)
    )
    token = BadgeToken(participant_id=participant.id, token=new_badge_token())
    session.add(token)

    participant.foreign_code_at = func.clock_timestamp()
    participant.foreign_code_by = user_id
    session.add(
        EventLog(
            conference_id=participant.conference_id,
            participant_id=participant.id,
            type=EventType.FOREIGN_CODE,
            user_id=user_id,
            payload={"printer_id": printer_id},
        )
    )
    await session.flush()

    job = PrintJob(
        conference_id=participant.conference_id,
        participant_id=participant.id,
        badge_token_id=token.id,
        printer_id=printer_id,
        kind=PrintJobKind.FOREIGN,
        sides=2 if badge_type == BadgeType.DOUBLE else 1,
        status=PrintJobStatus.PENDING,
        created_by_user_id=user_id,
    )
    session.add(job)
    await session.flush()

    await notify_participant_updated(session, participant.id, participant.conference_id)
    return job.id
