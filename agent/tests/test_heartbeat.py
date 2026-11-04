"""Тесты фонового сервиса heartbeat."""

from __future__ import annotations

import time
from typing import cast

import pytest

from regsys_agent.api import AuthError, ServerClient
from regsys_agent.heartbeat import Heartbeat
from regsys_agent.spooler import PrintOutcome, Spooler


class DummySpooler:
    """Фиктивный спулер для тестирования heartbeat."""

    def __init__(self, status: str = "ready", error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.calls: int = 0

    def printer_status(self) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.status

    def ensure_online(self) -> None:
        pass

    def submit(self, data: bytes, doc_name: str) -> int:
        return 1

    def wait_printed(self, spool_job_id: int, timeout_s: float, settle_s: float) -> PrintOutcome:
        return PrintOutcome(True)

    def purge_stale(self, doc_prefix: str, older_than_s: float) -> int:
        return 0


class DummyClient:
    """Фиктивный клиент сервера для проверки отправки статусов."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.statuses: list[str] = []

    def heartbeat(self, printer_status: str) -> bool:
        self.statuses.append(printer_status)
        if self.error is not None:
            raise self.error
        return True


def test_beat_sends_spooler_status() -> None:
    """Метод beat опрашивает статус спулера и отправляет его серверу."""
    spooler: Spooler = DummySpooler(status="ready")
    client = DummyClient()
    hb = Heartbeat(cast(ServerClient, client), spooler, interval_s=1.0)

    status = hb.beat()

    assert status == "ready"
    assert client.statuses == ["ready"]


def test_beat_spooler_exception_returns_unknown() -> None:
    """Исключение при опросе спулера приводит к статусу 'unknown'."""
    spooler: Spooler = DummySpooler(error=RuntimeError("Спулер недоступен"))
    client = DummyClient()
    hb = Heartbeat(cast(ServerClient, client), spooler, interval_s=1.0)

    status = hb.beat()

    assert status == "unknown"
    assert client.statuses == ["unknown"]


def test_beat_auth_error_propagates() -> None:
    """Исключение AuthError от клиента пробрасывается наружу."""
    spooler: Spooler = DummySpooler(status="ready")
    client = DummyClient(error=AuthError("401 Unauthorized"))
    hb = Heartbeat(cast(ServerClient, client), spooler, interval_s=1.0)

    with pytest.raises(AuthError):
        hb.beat()


def test_beat_logs_status_change(caplog: pytest.LogCaptureFixture) -> None:
    """Смена статуса сопровождается записью в лог с подсказкой для offline."""
    spooler = DummySpooler(status="offline")
    client = DummyClient()
    hb = Heartbeat(cast(ServerClient, client), cast(Spooler, spooler), interval_s=1.0)

    with caplog.at_level("WARNING"):
        hb.beat()
    assert "offline" in caplog.text
    assert "Проверьте питание и кабель" in caplog.text

    # Смена на ready
    spooler.status = "ready"
    caplog.clear()
    with caplog.at_level("INFO"):
        hb.beat()
    assert "ready" in caplog.text


def test_start_and_stop_multiple_calls() -> None:
    """Запуск фонового потока выполняет несколько вызовов и корректно останавливается."""
    spooler: Spooler = DummySpooler(status="ready")
    client = DummyClient()
    hb = Heartbeat(cast(ServerClient, client), spooler, interval_s=0.01)

    hb.start()
    time.sleep(0.06)
    hb.stop(timeout=1.0)

    assert len(client.statuses) >= 2
    assert hb._thread is not None
    assert not hb._thread.is_alive()
