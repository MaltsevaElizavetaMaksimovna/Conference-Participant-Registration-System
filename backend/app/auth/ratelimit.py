"""Ограничение перебора пароля: скользящее окно неудачных входов в памяти процесса."""

import time
from collections import deque
from collections.abc import Callable

from fastapi import FastAPI

_MAX_KEYS = 10_000


class LoginRateLimiter:
    """Считает неудачные попытки по ключу (ip, логин в нижнем регистре).

    Состояние живёт в памяти одного процесса: при нескольких воркерах лимит действует
    на каждый воркер отдельно (для сервиса на одном ПК этого достаточно).
    """

    def __init__(
        self, max_failures: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._clock = clock
        self._failures: dict[tuple[str, str], deque[float]] = {}

    def _prune(self, key: tuple[str, str]) -> deque[float] | None:
        attempts = self._failures.get(key)
        if attempts is None:
            return None
        border = self._clock() - self.window_s
        while attempts and attempts[0] <= border:
            attempts.popleft()
        if not attempts:
            del self._failures[key]
            return None
        return attempts

    def retry_after(self, key: tuple[str, str]) -> int | None:
        """Секунд до снятия блокировки или None, если вход разрешён."""
        attempts = self._prune(key)
        if attempts is None or len(attempts) < self.max_failures:
            return None
        return max(1, int(attempts[0] + self.window_s - self._clock()) + 1)

    def fail(self, key: tuple[str, str]) -> None:
        if len(self._failures) >= _MAX_KEYS:
            for k in list(self._failures):
                self._prune(k)
            if len(self._failures) >= _MAX_KEYS:  # защита памяти от потока разных логинов
                self._failures.pop(next(iter(self._failures)))
        self._failures.setdefault(key, deque()).append(self._clock())

    def reset(self, key: tuple[str, str]) -> None:
        self._failures.pop(key, None)


def get_login_limiter(app: FastAPI) -> LoginRateLimiter:
    """Лимитер живёт в `app.state` (свой у каждого приложения, настройки из `Settings`)."""
    limiter: LoginRateLimiter | None = getattr(app.state, "login_limiter", None)
    if limiter is None:
        settings = app.state.settings
        limiter = LoginRateLimiter(settings.login_max_failures, settings.login_fail_window_s)
        app.state.login_limiter = limiter
    return limiter
