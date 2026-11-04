"""Тесты загрузки конфигурации агента печати."""

from __future__ import annotations

from pathlib import Path

import pytest

from regsys_agent.config import load_config


def test_load_config_full(tmp_path: Path) -> None:
    """Проверка загрузки всех параметров конфигурации из INI-файла."""
    ini_file = tmp_path / "agent.ini"
    ini_content = """[agent]
server_url = http://example.com:8000/
printer_name = XP-360B
token = secret_token_ini
journal_path = custom_journal.jsonl
log_path = custom_agent.log
wait_s = 30
heartbeat_s = 15.5
spool_timeout_s = 20.0
settle_s = 5.0
stale_after_s = 60.0
"""
    ini_file.write_text(ini_content, encoding="utf-8")

    cfg = load_config(ini_file, env={})

    assert cfg.server_url == "http://example.com:8000"
    assert cfg.printer_name == "XP-360B"
    assert cfg.token == "secret_token_ini"
    assert cfg.journal_path == tmp_path / "custom_journal.jsonl"
    assert cfg.log_path == tmp_path / "custom_agent.log"
    assert cfg.wait_s == 30
    assert cfg.heartbeat_s == 15.5
    assert cfg.spool_timeout_s == 20.0
    assert cfg.settle_s == 5.0
    assert cfg.stale_after_s == 60.0


def test_load_config_defaults(tmp_path: Path) -> None:
    """Проверка значений по умолчанию и относительных путей рядом с INI-файлом."""
    ini_file = tmp_path / "agent.ini"
    ini_content = """[agent]
server_url = http://127.0.0.1:8000
printer_name = TestPrinter
token = ini_token
"""
    ini_file.write_text(ini_content, encoding="utf-8")

    cfg = load_config(ini_file, env={})

    assert cfg.server_url == "http://127.0.0.1:8000"
    assert cfg.printer_name == "TestPrinter"
    assert cfg.token == "ini_token"
    assert cfg.journal_path == tmp_path / "journal.jsonl"
    assert cfg.log_path == tmp_path / "agent.log"
    assert cfg.wait_s == 25
    assert cfg.heartbeat_s == 10.0
    assert cfg.spool_timeout_s == 10.0
    assert cfg.settle_s == 3.0
    assert cfg.stale_after_s == 30.0


def test_token_env_precedence(tmp_path: Path) -> None:
    """Переменная окружения RS_AGENT_TOKEN имеет приоритет над значением из INI."""
    ini_file = tmp_path / "agent.ini"
    ini_content = """[agent]
server_url = http://127.0.0.1:8000
printer_name = XP-360B
token = ini_token_value
"""
    ini_file.write_text(ini_content, encoding="utf-8")

    cfg = load_config(ini_file, env={"RS_AGENT_TOKEN": "env_token_override"})
    assert cfg.token == "env_token_override"


def test_token_only_in_env(tmp_path: Path) -> None:
    """Токен может быть задан только через переменную окружения."""
    ini_file = tmp_path / "agent.ini"
    ini_content = """[agent]
server_url = http://127.0.0.1:8000
printer_name = XP-360B
"""
    ini_file.write_text(ini_content, encoding="utf-8")

    cfg = load_config(ini_file, env={"RS_AGENT_TOKEN": "env_only_token"})
    assert cfg.token == "env_only_token"


def test_missing_required_fields_raises_value_error(tmp_path: Path) -> None:
    """Отсутствие обязательных параметров приводит к понятному ValueError без раскрытия токена."""
    secret = "super_secret_token_never_leak"

    # Нет server_url
    ini_1 = tmp_path / "no_url.ini"
    ini_1.write_text(f"[agent]\nprinter_name = XP\ntoken = {secret}\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc1:
        load_config(ini_1, env={})
    assert "server_url" in str(exc1.value)
    assert secret not in str(exc1.value)

    # Нет printer_name
    ini_2 = tmp_path / "no_printer.ini"
    ini_2.write_text(f"[agent]\nserver_url = http://x\ntoken = {secret}\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc2:
        load_config(ini_2, env={})
    assert "printer_name" in str(exc2.value)
    assert secret not in str(exc2.value)

    # Нет токена ни в файле, ни в env
    ini_3 = tmp_path / "no_token.ini"
    ini_3.write_text("[agent]\nserver_url = http://x\nprinter_name = XP\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc3:
        load_config(ini_3, env={})
    assert "токен" in str(exc3.value).lower()
    assert secret not in str(exc3.value)


def test_missing_file_raises_not_found(tmp_path: Path) -> None:
    """Попытка загрузки несуществующего файла вызывает FileNotFoundError."""
    missing = tmp_path / "missing.ini"
    with pytest.raises(FileNotFoundError):
        load_config(missing, env={})
