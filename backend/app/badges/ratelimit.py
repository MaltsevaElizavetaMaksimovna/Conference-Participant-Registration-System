"""Ограничение частоты запросов к публичному профилю: скользящее окно по IP в памяти процесса."""

import time
from collections import deque
from collections.abc import Callable

from fastapi import FastAPI

_MAX_KEYS = 10_000


class PublicRateLimiter:
    """Считает все запросы с одного IP за окно; сверх `max_requests` отвечает отказом.

    Как и лимитер входа, живёт в памяти одного процесса: при нескольких воркерах лимит
    действует на каждый воркер отдельно (для сервиса на одном ПК этого достаточно).
    """

    def __init__(
        self, max_requests: int, window_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.max_requests = max_requests
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def _prune(self, key: str) -> deque[float] | None:
        hits = self._hits.get(key)
        if hits is None:
            return None
        border = self._clock() - self.window_s
        while hits and hits[0] <= border:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def hit(self, key: str) -> int | None:
        """Учесть запрос. None — можно обрабатывать; число — через сколько секунд повторить."""
        hits = self._prune(key)
        if hits is not None and len(hits) >= self.max_requests:
            return max(1, int(hits[0] + self.window_s - self._clock()) + 1)
        if hits is None:
            if len(self._hits) >= _MAX_KEYS:
                for k in list(self._hits):
                    self._prune(k)
                if len(self._hits) >= _MAX_KEYS:  # защита памяти от потока разных адресов
                    self._hits.pop(next(iter(self._hits)))
            hits = self._hits.setdefault(key, deque())
        hits.append(self._clock())
        return None


def get_public_limiter(app: FastAPI) -> PublicRateLimiter:
    """Лимитер живёт в `app.state` (свой у каждого приложения, настройки из `Settings`)."""
    limiter: PublicRateLimiter | None = getattr(app.state, "public_limiter", None)
    if limiter is None:
        settings = app.state.settings
        limiter = PublicRateLimiter(
            settings.public_profile_rate_limit, settings.public_profile_rate_window_s
        )
        app.state.public_limiter = limiter
    return limiter
