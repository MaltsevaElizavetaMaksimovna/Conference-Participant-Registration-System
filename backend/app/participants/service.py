"""Общие утилиты участников: поисковая строка и флаг «Данные изменены».

Статус регистрации здесь не меняется: это делает только `registration.service`.
"""

from collections.abc import Collection

from app.core.text import normalize_search

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
