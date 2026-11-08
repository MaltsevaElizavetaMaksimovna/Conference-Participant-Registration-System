"""Подтверждение регистрации на терминале (B2-04): TR-03, TR-04, TR-05, TR-09, DP-01, DP-02.

Разбор запроса терминала и тексты экрана. Статус регистрации меняет исключительно
`app.registration.service.register`.
"""

from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import ParticipantStatus, RegSource
from app.core.errors import AppError
from app.models.conference import Conference
from app.models.participant import Participant
from app.registration import messages, service
from app.registration.result import RegistrationResult, find_replay, idempotency_scope
from app.terminals.deps import CurrentTerminal
from app.terminals.scan_id import verify_scan_id
from app.terminals.schemas import ConfirmOut


def check_scan_id(
    settings: Settings, terminal: CurrentTerminal, participant_id: int, scan_id: str
) -> None:
    """`scan_id` выдан этому терминалу для этого участника и ещё не просрочен, иначе 409."""
    ttl = settings.terminal_idle_timeout_s + settings.scan_id_grace_s
    if not verify_scan_id(settings.secret_key, scan_id, terminal.terminal_id, participant_id, ttl):
        raise AppError("scan_expired", messages.SCAN_EXPIRED, 409)


async def require_active_participant(session: AsyncSession, participant_id: int) -> None:
    """Участник должен быть в активной конференции: терминал работает только с ней."""
    found = await session.scalar(
        select(Participant.id)
        .join(Conference, Conference.id == Participant.conference_id)
        .where(Participant.id == participant_id, Conference.is_active)
    )
    if found is None:
        raise AppError("participant_not_found", messages.NOT_FOUND, 404)


def confirm_out(result: RegistrationResult, settings: Settings) -> ConfirmOut:
    """Ответ confirm строится только из сохранённого результата: повтор даёт тот же ответ."""
    if result.result == "already_registered":
        tz = ZoneInfo(settings.timezone)
        return ConfirmOut(
            result="already_registered",
            message=messages.already_registered(result.registered_at, tz),
        )
    if result.status == ParticipantStatus.REGISTERED_NO_STICKER:
        message = messages.REGISTERED_NO_BADGE  # TR-09
    elif result.sticker_not_printed:
        message = messages.STICKER_FAILED  # TR-08: принтер терминала не привязан
    else:
        message = messages.STICKER_PRINTING  # TR-04
    return ConfirmOut(result="registered", print_job_id=result.print_job_id, message=message)


async def confirm(
    session: AsyncSession,
    terminal: CurrentTerminal,
    settings: Settings,
    *,
    participant_id: int,
    scan_id: str,
    idempotency_key: str,
) -> ConfirmOut:
    scope = idempotency_scope(RegSource.TERMINAL, terminal.terminal_id, None)
    # Повтор уже обработанного запроса отвечает тем же, даже если scan_id успел протухнуть:
    # клиент не получил ответ и просто повторил
    result = await find_replay(session, scope, idempotency_key, participant_id)
    if result is None:
        check_scan_id(settings, terminal, participant_id, scan_id)
        await require_active_participant(session, participant_id)
        result = await service.register(
            session,
            participant_id,
            source=RegSource.TERMINAL,
            terminal_id=terminal.terminal_id,
            user_id=None,
            with_sticker=True,
            printer_id=terminal.printer_id,
            idempotency_key=idempotency_key,
        )
    else:
        await session.commit()  # только читали; закрываем транзакцию
    return confirm_out(result, settings)
