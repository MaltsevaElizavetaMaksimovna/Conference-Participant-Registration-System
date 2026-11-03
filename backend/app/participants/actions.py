"""Доступность кнопок карточки участника и причины недоступности (B1-12, RG-05).

Флаг `false` делает кнопку неактивной, подсказка берётся из `reasons` по имени флага.
"""

from zoneinfo import ZoneInfo

from app.auth.deps import CurrentStaff
from app.core.enums import BadgeType
from app.core.permissions import Permission
from app.participants.schemas import ParticipantActions, RegistrationInfo
from app.registration.messages import format_registered_at

DESK_PLACE = "Стойка регистратора"


def card_actions(
    badge_type: str,
    staff: CurrentStaff,
    registration: RegistrationInfo | None,
    tz: ZoneInfo,
) -> ParticipantActions:
    """Доступность кнопок карточки и причины недоступности (RG-05, RG-06, RG-08, QR-03)."""
    reasons: dict[str, str] = {}
    badges = badge_type != BadgeType.NONE

    if registration is not None:
        place = registration.terminal_name or DESK_PLACE
        reasons["can_register"] = (
            f"Уже зарегистрирован {format_registered_at(registration.at, tz)}, {place}"
        )
    can_register = registration is None and staff.has(Permission.REGISTRATION_DESK)
    if registration is None and not can_register:
        reasons["can_register"] = "Нет права регистрировать участников"

    can_reprint = registration is not None and badges and staff.has(Permission.STICKERS_PRINT)
    if registration is None:
        reasons["can_reprint"] = "Сначала зарегистрируйте участника"
    elif not badges:
        reasons["can_reprint"] = "Конференция проходит без бейджей"
    elif not can_reprint:
        reasons["can_reprint"] = "Нет права печатать наклейки"

    can_edit = staff.has(Permission.PARTICIPANTS_EDIT)
    if not can_edit:
        reasons["can_edit"] = "Нет права исправлять данные"

    can_foreign_code = (
        registration is not None and badges and staff.has(Permission.REGISTRATION_FOREIGN_CODE)
    )
    if registration is None:
        reasons["can_foreign_code"] = "По коду участника ещё никто не регистрировался"
    elif not badges:
        reasons["can_foreign_code"] = "Конференция проходит без бейджей"
    elif not can_foreign_code:
        reasons["can_foreign_code"] = "Нет права регистрировать по чужому коду"

    return ParticipantActions(
        can_register=can_register,
        can_reprint=can_reprint,
        can_edit=can_edit,
        can_foreign_code=can_foreign_code,
        reasons=reasons,
    )
