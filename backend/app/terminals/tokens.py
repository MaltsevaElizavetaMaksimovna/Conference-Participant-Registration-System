"""Токены устройств: терминалов и агентов печати.

Токен показывается администратору один раз, в БД лежит только sha256 hex (колонки
`terminal.token_hash`, `printer.agent_token_hash`). Токен длинный и случайный, поэтому
обычного быстрого хэша достаточно: подобрать его перебором нельзя.
"""

import hashlib
import secrets

TERMINAL_PREFIX = "trm"
AGENT_PREFIX = "agt"


def generate_token(prefix: str) -> str:
    """Новый токен вида `trm_<43 символа urlsafe>` (256 бит случайности)."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
