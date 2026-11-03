"""Значения полей участника для элементов шаблона (PR-01, PR-04, QR-01)."""

from dataclasses import dataclass, field
from typing import Any

from app.models.participant import Participant
from app.templates.schemas import STANDARD_KEYS

EN_SUFFIX = "_en"
EXTRA_PREFIX = "extra."


@dataclass(frozen=True)
class LabelData:
    """Что печатать: значения по ключам `elements[].field` и ссылка для QR."""

    values: dict[str, str] = field(default_factory=dict)
    profile_url: str | None = None

    def value(self, key: str) -> str:
        return self.values.get(key, "")


def _text(value: Any) -> str:
    return "" if value is None else " ".join(str(value).split())


def profile_url(public_base_url: str, token: str) -> str:
    """Ссылка профиля в QR: `<RS_PUBLIC_BASE_URL>/p/<token>` (QR-02)."""
    return f"{public_base_url.rstrip('/')}/p/{token}"


def label_data(p: Participant, profile_url: str | None) -> LabelData:
    """Поля участника. Нет английского значения — печатается русское (PR-04), по каждому полю."""
    values: dict[str, str] = {}
    for key in STANDARD_KEYS:
        ru = _text(getattr(p, key))
        values[key] = ru
        values[key + EN_SUFFIX] = _text(getattr(p, key + EN_SUFFIX)) or ru
    values["full_name"] = " ".join(
        v for v in (values["last_name"], values["first_name"], values["middle_name"]) if v
    )
    for key, value in (p.extra or {}).items():
        values[EXTRA_PREFIX + key] = _text(value)
    return LabelData(values=values, profile_url=profile_url)


# Образец для предпросмотра без участника (B2-09)
SAMPLE = LabelData(
    values={
        "last_name": "Константинопольский",
        "first_name": "Александр",
        "middle_name": "Владимирович",
        "position": "Ведущий инженер",
        "organization": "ООО «Научно-производственное объединение Ромашка»",
        "last_name_en": "Konstantinopolsky",
        "first_name_en": "Alexander",
        "middle_name_en": "Vladimirovich",
        "position_en": "Lead engineer",
        "organization_en": "Romashka Research and Production Association LLC",
        "full_name": "Константинопольский Александр Владимирович",
    },
    profile_url="https://reg.example.ru/p/SAMPLE-TOKEN-0000",
)
