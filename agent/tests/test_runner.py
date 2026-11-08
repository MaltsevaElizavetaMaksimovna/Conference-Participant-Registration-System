"""Тесты главного цикла агента печати runner."""

from __future__ import annotations

import threading
from typing import cast

import httpx
import pytest

from regsys_agent.api import AuthError
from regsys_agent.runner import run
from regsys_agent.worker import Worker


def test_runner_normal_rounds() -> None:
    """Нормальное выполнение кругов без ошибок и пауз."""
    stop = threading.Event()
    calls = 0

    class NormalWorker:
        def run_once(self, wait_s: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                stop.set()

    pauses: list[float] = []
    run(cast(Worker, NormalWorker()), wait_s=25, stop=stop, sleep=pauses.append)

    assert calls == 3
    assert pauses == []


def test_runner_http_error_backoff_and_reset() -> None:
    """При httpx.ConnectError задержки растут (1, 2, 4) и сбрасываются в 1 после успеха."""
    stop = threading.Event()
    request = httpx.Request("GET", "http://test")
    err = httpx.ConnectError("Connection failed", request=request)

    steps: list[Exception | None] = [
        err,
        err,
        err,
        None,
        err,
    ]
    pauses: list[float] = []

    class SteppingWorker:
        def run_once(self, wait_s: int) -> None:
            if not steps:
                stop.set()
                return
            step_outcome = steps.pop(0)
            if step_outcome is not None:
                raise step_outcome

    def fake_sleep(duration: float) -> None:
        pauses.append(duration)
        if not steps:
            stop.set()

    run(cast(Worker, SteppingWorker()), wait_s=25, stop=stop, sleep=fake_sleep)

    assert pauses == [1, 2, 4, 1]


def test_runner_backoff_cap_at_30() -> None:
    """Пауза при повторных сетевых ошибках ограничивается 30 секундами."""
    stop = threading.Event()
    request = httpx.Request("GET", "http://test")
    err = httpx.ConnectError("Connection failed", request=request)
    pauses: list[float] = []

    class FailingWorker:
        def run_once(self, wait_s: int) -> None:
            raise err

    def fake_sleep(duration: float) -> None:
        pauses.append(duration)
        if len(pauses) == 7:
            stop.set()

    run(cast(Worker, FailingWorker()), wait_s=25, stop=stop, sleep=fake_sleep)

    assert pauses == [1, 2, 4, 8, 16, 30, 30]


def test_runner_auth_error_pause_60(caplog: pytest.LogCaptureFixture) -> None:
    """При AuthError выводится ошибка в лог и выполняется пауза 60 с."""
    stop = threading.Event()
    pauses: list[float] = []

    class AuthFailingWorker:
        def run_once(self, wait_s: int) -> None:
            raise AuthError("401 Unauthorized")

    def fake_sleep(duration: float) -> None:
        pauses.append(duration)
        stop.set()

    with caplog.at_level("ERROR"):
        run(cast(Worker, AuthFailingWorker()), wait_s=25, stop=stop, sleep=fake_sleep)

    assert pauses == [60]
    assert "Сервер не принял токен агента: выпустите новый в админке принтеров" in caplog.text


def test_runner_unexpected_exception_pause_5(caplog: pytest.LogCaptureFixture) -> None:
    """При неожиданном исключении пишется лог, выдерживается пауза 5 с, и цикл продолжается."""
    stop = threading.Event()
    pauses: list[float] = []
    calls = 0

    class UnexpectedWorker:
        def run_once(self, wait_s: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Непредвиденный сбой")
            stop.set()

    def fake_sleep(duration: float) -> None:
        pauses.append(duration)

    with caplog.at_level("ERROR"):
        run(cast(Worker, UnexpectedWorker()), wait_s=25, stop=stop, sleep=fake_sleep)

    assert calls == 2
    assert pauses == [5]
    assert "Непредвиденная ошибка в основном цикле агента печати" in caplog.text


def test_runner_stops_immediately_when_stop_is_set() -> None:
    """Если событие stop установлено до запуска, цикл сразу завершается."""
    stop = threading.Event()
    stop.set()
    called = False

    class DummyWorker:
        def run_once(self, wait_s: int) -> None:
            nonlocal called
            called = True

    run(cast(Worker, DummyWorker()), wait_s=25, stop=stop)
    assert not called
