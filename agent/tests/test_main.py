"""Тесты точки входа __main__ агента печати."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import regsys_agent.__main__ as main_mod
from regsys_agent.__main__ import main
from regsys_agent.heartbeat import Heartbeat
from regsys_agent.worker import Worker


def test_main_missing_config_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Указание несуществующего файла конфигурации приводит к коду завершения 2."""
    missing_file = tmp_path / "nonexistent.ini"
    exit_code = main(["--config", str(missing_file)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Ошибка конфигурации" in captured.err


def test_main_invalid_config_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Некорректный INI-файл приводит к ошибке конфигурации и коду завершения 2."""
    bad_file = tmp_path / "invalid.ini"
    bad_file.write_text("[agent]\n", encoding="utf-8")

    exit_code = main(["--config", str(bad_file)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "Ошибка конфигурации" in captured.err


def test_main_success_log_created_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """При успешном запуске создается лог-файл без раскрытия токена."""
    ini_file = tmp_path / "agent.ini"
    secret_token = "secret_agent_token_xyz_998877"
    ini_content = f"""[agent]
server_url = http://test-server:8080
printer_name = XP-360B-TestPrinter
token = {secret_token}
journal_path = custom_journal.jsonl
log_path = custom_agent.log
wait_s = 15
heartbeat_s = 5
"""
    ini_file.write_text(ini_content, encoding="utf-8")

    class MockServerClient:
        def __init__(self, base_url: str, token: str) -> None:
            self.base_url = base_url
            self.token = token
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class MockSpooler:
        def __init__(self, printer_name: str) -> None:
            self.printer_name = printer_name

        def purge_stale(self, doc_prefix: str, older_than_s: float) -> int:
            return 0

    monkeypatch.setattr(main_mod, "ServerClient", MockServerClient)
    monkeypatch.setattr(main_mod, "Win32Spooler", MockSpooler)
    monkeypatch.setattr(Worker, "start", lambda self: None)
    monkeypatch.setattr(Heartbeat, "start", lambda self: None)
    monkeypatch.setattr(Heartbeat, "stop", lambda self: None)

    run_called = False

    def fake_run(worker: Worker, wait_s: int, stop: threading.Event) -> None:
        nonlocal run_called
        run_called = True

    monkeypatch.setattr(main_mod, "run", fake_run)

    exit_code = main(["--config", str(ini_file)])

    assert exit_code == 0
    assert run_called is True

    log_file = tmp_path / "custom_agent.log"
    assert log_file.exists()
    log_text = log_file.read_text(encoding="utf-8")

    assert secret_token not in log_text
    assert "XP-360B-TestPrinter" in log_text
    assert "http://test-server:8080" in log_text
    assert "0.1.0" in log_text
