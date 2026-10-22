"""Код бейджа (QR-01): отдельный от ID приглашения случайный токен в ссылке на наклейке.

Токен хранится открытым текстом (`badge_token.token`): при повторной печати нужен тот же QR.
Угадать его нельзя: `secrets.token_urlsafe(16)` даёт 128 бит случайности.
"""

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BadgeTokenStatus
from app.models.participant import BadgeToken

TOKEN_BYTES = 16  # 128 бит


def new_badge_token() -> str:
    """Новый случайный код бейджа (22 символа urlsafe base64)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


async def get_or_create_active_token(session: AsyncSession, participant_id: int) -> BadgeToken:
    """Действующий код бейджа участника; если его нет, создаёт новый (без commit).

    Повторная печать вызывает эту же функцию и получает прежний токен (QR-01). Не больше
    одного действующего кода на участника гарантирует частичный уникальный индекс.
    """
    token = await session.scalar(
        select(BadgeToken)
        .where(
            BadgeToken.participant_id == participant_id,
            BadgeToken.status == BadgeTokenStatus.ACTIVE,
        )
        .limit(1)
    )
    if token is None:
        token = BadgeToken(
            participant_id=participant_id,
            token=new_badge_token(),
            status=BadgeTokenStatus.ACTIVE,
        )
        session.add(token)
        await session.flush()
    return token
