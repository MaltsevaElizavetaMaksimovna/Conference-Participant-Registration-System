"""Текстовые утилиты: нормализация для поиска и сборка ФИО."""

import re

_SPACES = re.compile(r"\s+")


def normalize_search(s: str) -> str:
    """Нижний регистр, ё -> е, схлопывание пробелов, strip."""
    return _SPACES.sub(" ", s.lower().replace("ё", "е")).strip()


def full_name(last: str, first: str, middle: str | None = None) -> str:
    """«Фамилия Имя Отчество» без лишних пробелов; пустое отчество пропускается."""
    return " ".join(p for p in (last.strip(), first.strip(), (middle or "").strip()) if p)
