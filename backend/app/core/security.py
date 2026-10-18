"""Пароли (argon2id) и непрозрачные токены (сессии сотрудников)."""

import hashlib
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """True, если пароль подходит. Некорректный хэш в БД трактуется как «не подходит»."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Параметры argon2 устарели -> перехэшировать при успешном входе."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@lru_cache
def dummy_hash() -> str:
    """Фиктивный хэш: для неизвестного логина verify занимает столько же времени."""
    return _hasher.hash(secrets.token_urlsafe(16))


def new_token() -> str:
    """Токен для cookie: 256 бит случайности."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """В БД хранится только sha256 токена (id сессии), не сам токен."""
    return hashlib.sha256(token.encode()).hexdigest()
