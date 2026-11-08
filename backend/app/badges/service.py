"""Публичный профиль по коду бейджа: проверка формата токена, поиск, путь к фото (QR-02, NF-06)."""

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BadgeTokenStatus
from app.models.participant import BadgeToken, Participant

# Токены выдаёт `secrets.token_urlsafe(16)` (22 символа); границы с запасом. Всё остальное —
# заведомо чужой ввод: отвечаем «не найдено», не обращаясь к БД.
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")


@dataclass(frozen=True)
class ProfileRecord:
    """Всё, что нужно для ответа; лишних данных об участнике здесь нет намеренно."""

    revoked: bool
    name_parts: tuple[str, str, str | None]  # фамилия, имя, отчество
    position: str | None
    organization: str | None
    photo_path: str | None


def is_valid_token_format(token: str) -> bool:
    return TOKEN_RE.fullmatch(token) is not None


async def find_profile(session: AsyncSession, token: str) -> ProfileRecord | None:
    """Участник по коду бейджа; None — код неизвестен или имеет неверный формат."""
    if not is_valid_token_format(token):
        return None
    row = (
        await session.execute(
            select(
                BadgeToken.status,
                Participant.last_name,
                Participant.first_name,
                Participant.middle_name,
                Participant.position,
                Participant.organization,
                Participant.photo_path,
            )
            .join(Participant, Participant.id == BadgeToken.participant_id)
            .where(BadgeToken.token == token)
        )
    ).one_or_none()
    if row is None:
        return None
    status, last, first, middle, position, organization, photo_path = row
    return ProfileRecord(
        revoked=status != BadgeTokenStatus.ACTIVE,
        name_parts=(last, first, middle),
        position=position,
        organization=organization,
        photo_path=photo_path,
    )


def resolve_photo(photo_dir: Path, photo_path: str | None) -> Path | None:
    """Файл фото внутри `photo_dir`; None — фото нет или путь выходит за каталог."""
    if not photo_path or "\x00" in photo_path:
        return None
    try:
        rel = Path(photo_path)
        if rel.is_absolute() or rel.drive or rel.root:
            return None
        base = photo_dir.resolve()
        candidate = (base / rel).resolve()
        if not candidate.is_relative_to(base) or not candidate.is_file():
            return None
    except (OSError, ValueError):
        return None
    return candidate
