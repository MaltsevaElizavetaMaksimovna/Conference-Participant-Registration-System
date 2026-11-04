"""Загрузка конфигурации агента печати из INI-файла и переменных окружения."""

from __future__ import annotations

import configparser
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentConfig:
    """Параметры работы агента печати."""

    server_url: str
    token: str
    printer_name: str
    journal_path: Path
    log_path: Path
    wait_s: int = 25
    heartbeat_s: float = 10
    spool_timeout_s: float = 10
    settle_s: float = 3
    stale_after_s: float = 30


def load_config(path: Path, env: Mapping[str, str] = os.environ) -> AgentConfig:
    """Загрузить конфигурацию из INI-файла и окружения.

    Токен из переменной окружения RS_AGENT_TOKEN имеет приоритет над файлом.
    При отсутствии обязательных параметров выбрасывается ValueError без раскрытия токена.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Файл конфигурации не найден: {path}")

    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")

    if not parser.has_section("agent"):
        raise ValueError("В конфигурационном файле отсутствует секция [agent]")

    sec = parser["agent"]

    server_url = sec.get("server_url", "").strip()
    if not server_url:
        raise ValueError("Не указан обязательный параметр server_url")
    server_url = server_url.rstrip("/")

    printer_name = sec.get("printer_name", "").strip()
    if not printer_name:
        raise ValueError("Не указан обязательный параметр printer_name")

    token_env = env.get("RS_AGENT_TOKEN", "").strip()
    token_ini = sec.get("token", "").strip()
    token = token_env or token_ini
    if not token:
        raise ValueError(
            "Не указан токен агента (задайте RS_AGENT_TOKEN или параметр token в секции [agent])"
        )

    base_dir = path.parent

    journal_val = sec.get("journal_path", "").strip()
    if journal_val:
        jp = Path(journal_val)
        journal_path = jp if jp.is_absolute() else base_dir / jp
    else:
        journal_path = base_dir / "journal.jsonl"

    log_val = sec.get("log_path", "").strip()
    if log_val:
        lp = Path(log_val)
        log_path = lp if lp.is_absolute() else base_dir / lp
    else:
        log_path = base_dir / "agent.log"

    wait_s = sec.getint("wait_s", fallback=25)
    heartbeat_s = sec.getfloat("heartbeat_s", fallback=10.0)
    spool_timeout_s = sec.getfloat("spool_timeout_s", fallback=10.0)
    settle_s = sec.getfloat("settle_s", fallback=3.0)
    stale_after_s = sec.getfloat("stale_after_s", fallback=30.0)

    return AgentConfig(
        server_url=server_url,
        token=token,
        printer_name=printer_name,
        journal_path=journal_path,
        log_path=log_path,
        wait_s=wait_s,
        heartbeat_s=heartbeat_s,
        spool_timeout_s=spool_timeout_s,
        settle_s=settle_s,
        stale_after_s=stale_after_s,
    )
