"""Точка входа для запуска агента печати."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import signal
import sys
import threading
from pathlib import Path
from typing import Any

from regsys_agent.api import ServerClient
from regsys_agent.config import load_config
from regsys_agent.heartbeat import Heartbeat
from regsys_agent.journal import Journal
from regsys_agent.runner import run
from regsys_agent.spooler import Win32Spooler
from regsys_agent.worker import PrintTiming, Worker

VERSION = "0.1.0"
log = logging.getLogger("regsys_agent")


def _get_default_config_path() -> Path:
    """Определить путь к agent.ini по умолчанию рядом с exe или скриптом."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "agent.ini"
    script_dir = Path(__file__).resolve().parent.parent
    candidate = script_dir / "agent.ini"
    if candidate.exists():
        return candidate
    return Path.cwd() / "agent.ini"


def main(argv: list[str] | None = None) -> int:
    """Основная функция запуска агента печати."""
    parser = argparse.ArgumentParser(description="Агент печати наклеек regsys-agent")
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="Путь к файлу конфигурации agent.ini",
    )
    args = parser.parse_args(argv)

    config_path = args.config if args.config is not None else _get_default_config_path()

    try:
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Ошибка загрузки конфигурации: {exc}", file=sys.stderr)
        return 2

    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        config.log_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    try:
        log.info(
            "Запуск regsys-agent v%s (принтер: %s, сервер: %s)",
            VERSION,
            config.printer_name,
            config.server_url,
        )

        client_worker = ServerClient(config.server_url, config.token)
        client_heartbeat = ServerClient(config.server_url, config.token)
        spooler = Win32Spooler(config.printer_name)
        journal = Journal(config.journal_path)
        timing = PrintTiming(
            spool_timeout_s=config.spool_timeout_s,
            settle_s=config.settle_s,
            stale_after_s=config.stale_after_s,
        )
        worker = Worker(
            client=client_worker,
            spooler=spooler,
            journal=journal,
            timing=timing,
        )

        worker.start()

        heartbeat = Heartbeat(
            client=client_heartbeat,
            spooler=spooler,
            interval_s=config.heartbeat_s,
        )
        heartbeat.start()

        stop_event = threading.Event()

        def _handle_signal(signum: int, frame: Any) -> None:
            log.info("Получен сигнал завершения (%s), останавливаем агент...", signum)
            stop_event.set()

        try:
            signal.signal(signal.SIGINT, _handle_signal)
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, _handle_signal)
        except (ValueError, AttributeError):
            pass

        try:
            run(worker, config.wait_s, stop_event)
        except KeyboardInterrupt:
            log.info("Получено прерывание с клавиатуры (Ctrl+C)")
            stop_event.set()
        finally:
            log.info("Остановка компонентов агента...")
            heartbeat.stop()
            client_worker.close()
            client_heartbeat.close()

        log.info("Агент печати остановлен")
        return 0
    finally:
        root_logger.removeHandler(file_handler)
        root_logger.removeHandler(console_handler)
        file_handler.close()


if __name__ == "__main__":
    sys.exit(main())
