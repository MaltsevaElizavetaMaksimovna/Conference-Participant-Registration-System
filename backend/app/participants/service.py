"""Общие утилиты участников: поисковая строка, флаг «Данные изменены», пометки.

Статус регистрации здесь не меняется: это делает только `registration.service`.
"""

from collections.abc import Collection

from app.core.text import normalize_search
from app.models.participant import Participant
from app.participants.schemas import ParticipantFlag

# Поля ФИО, из которых строится `search_norm`
NAME_FIELDS = ("last_name", "first_name", "middle_name")


def compute_search_norm(last_name: str, first_name: str, middle_name: str | None = None) -> str:
    """`search_norm` участника: «фамилия имя отчество» в нижнем регистре, ё -> е."""
    return normalize_search(f"{last_name} {first_name} {middle_name or ''}")


def is_data_changed(manual_fields: Collection[str] | None, is_manual_added: bool = False) -> bool:
    """Флаг «Данные изменены» (ER-02): регистратор правил данные или добавил участника вручную.

    Рендер наклейки по этому флагу выбирает шаблон «Данные изменены». Данные, обновлённые
    повторной загрузкой файла, флаг не включают: он про правки на месте регистрации.
    """
    return is_manual_added or bool(manual_fields)


def participant_flags(p: Participant) -> list[ParticipantFlag]:
    """Пометки участника для значков в списке, в порядке `ParticipantFlag`."""
    flags: list[ParticipantFlag] = []
    if p.error_reported_at is not None:
        flags.append("error_reported")
    if p.sticker_not_printed:
        flags.append("sticker_not_printed")
    if is_data_changed(p.manual_fields, p.is_manual_added):
        flags.append("data_changed")
    if p.is_manual_added:
        flags.append("manual_added")
    if p.foreign_code_at is not None:
        flags.append("foreign_code")
    return flags
