"""Столбцы файла участников: словарь синонимов заголовков, транслит-slug для доп. полей.

Один словарь служит и разбору файла (B1-05), и шаблону для скачивания (B1-08): название
столбца в шаблоне всегда распознаётся загрузкой.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    key: str  # имя поля участника (`participant.<key>`); photo_url идёт в `source_data`
    title: str  # заголовок в шаблоне (без «*»)
    required: bool
    synonyms: tuple[str, ...]  # прочие допустимые заголовки
    example: str  # значение в строке-примере шаблона
    reason_missing: str = ""  # «не указана фамилия»


_EN_SUFFIXES = (
    "(en)",
    "en",
    "(eng)",
    "eng",
    "(english)",
    "english",
    "(англ)",
    "(англ.)",
    "англ",
    "англ.",
    "(латиницей)",
    "латиницей",
    "(на английском)",
    "на английском",
)


def _en_variants(ru: tuple[str, ...], en: tuple[str, ...]) -> tuple[str, ...]:
    """Русские названия с пометкой языка плюс англоязычные заголовки без неё."""
    out = [f"{base} {suffix}" for base in (*ru, *en) for suffix in _EN_SUFFIXES]
    out.extend(en)
    return tuple(out)


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "external_id",
        "Идентификатор",
        True,
        (
            "ID",
            "Идентификатор участника",
            "ID участника",
            "Номер участника",
            "Код участника",
            "Номер",
            "Participant ID",
            "External ID",
            "UID",
        ),
        "P-1001",
        "не указан идентификатор",
    ),
    FieldSpec(
        "last_name",
        "Фамилия",
        True,
        ("Фамилия RU", "Фамилия (RU)"),
        "Иванов",
        "не указана фамилия",
    ),
    FieldSpec("first_name", "Имя", True, ("Имя RU", "Имя (RU)"), "Пётр", "не указано имя"),
    FieldSpec("middle_name", "Отчество", False, ("Отчество RU", "Отчество (RU)"), "Сергеевич"),
    FieldSpec("position", "Должность", False, ("Должность RU", "Должность (RU)"), "Инженер"),
    FieldSpec(
        "organization",
        "Организация",
        False,
        ("Компания", "Место работы", "Организация RU", "Организация (RU)"),
        "ООО Ромашка",
    ),
    FieldSpec(
        "last_name_en",
        "Фамилия (EN)",
        False,
        _en_variants(("Фамилия",), ("Last name", "Lastname", "Surname", "Family name")),
        "Ivanov",
    ),
    FieldSpec(
        "first_name_en",
        "Имя (EN)",
        False,
        _en_variants(("Имя",), ("First name", "Firstname", "Given name")),
        "Petr",
    ),
    FieldSpec(
        "middle_name_en",
        "Отчество (EN)",
        False,
        _en_variants(("Отчество",), ("Middle name", "Middlename", "Patronymic")),
        "Sergeevich",
    ),
    FieldSpec(
        "position_en",
        "Должность (EN)",
        False,
        _en_variants(("Должность",), ("Position", "Job title", "Job")),
        "Engineer",
    ),
    FieldSpec(
        "organization_en",
        "Организация (EN)",
        False,
        _en_variants(("Организация", "Компания"), ("Organization", "Organisation", "Company")),
        "Romashka LLC",
    ),
    FieldSpec(
        "photo_url",
        "Фото (ссылка)",
        False,
        (
            "Фото",
            "Ссылка на фото",
            "Ссылка на фотографию",
            "Фотография",
            "URL фото",
            "Photo",
            "Photo URL",
            "Photo link",
        ),
        "https://example.com/photos/ivanov.jpg",
    ),
)

FIELD_BY_KEY: dict[str, FieldSpec] = {f.key: f for f in FIELDS}
REQUIRED_KEYS: tuple[str, ...] = tuple(f.key for f in FIELDS if f.required)

_IGNORED = re.compile(r"[\s*_\-.:​﻿]+")


def normalize_header(header: str) -> str:
    """Заголовок для сопоставления: без учёта регистра, «*», ё/е, пробелов и `_ - . :`."""
    return _IGNORED.sub("", header.lower().replace("ё", "е"))


def _build_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for spec in FIELDS:
        for name in (spec.title, *spec.synonyms):
            norm = normalize_header(name)
            owner = index.setdefault(norm, spec.key)
            assert owner == spec.key, f"заголовок {name!r} относится к {owner} и {spec.key}"
    return index


_INDEX = _build_index()


def match_header(header: str) -> str | None:
    """Ключ стандартного поля по заголовку столбца или None (тогда это доп. поле)."""
    return _INDEX.get(normalize_header(header))


def template_header(spec: FieldSpec) -> str:
    """Заголовок столбца в шаблоне: обязательные помечены «*»."""
    return f"{spec.title}*" if spec.required else spec.title


# --------------------------------------------------------------------------- slug доп. полей

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}  # fmt: skip

_NOT_SLUG = re.compile(r"[^a-z0-9]+")
MAX_SLUG_LEN = 60


def slugify(label: str) -> str:
    """Транслит-slug для ключа доп. поля: «Секция» -> `sektsiya`; пусто -> `field`."""
    lowered = label.lower()
    text = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    slug = _NOT_SLUG.sub("_", text).strip("_")[:MAX_SLUG_LEN].strip("_")
    return slug or "field"


def unique_slug(label: str, taken: set[str]) -> str:
    """slug, не совпадающий с `taken` (при совпадении добавляется `_2`, `_3`...)."""
    base = slugify(label)
    slug, n = base, 2
    while slug in taken:
        slug = f"{base}_{n}"
        n += 1
    return slug
