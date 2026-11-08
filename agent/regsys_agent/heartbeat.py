"""Отправка периодического статуса принтера на сервер (heartbeat)."""

from __future__ import annotations

import logging
import threading

from regsys_agent.api import AuthError, ServerClient
from regsys_agent.spooler import Spooler

log = logging.getLogger(__name__)

OFFLINE_HINT = (
    "Проверьте питание и кабель. Если принтер включили при вставленном USB, "
    "выньте и снова вставьте кабель (сначала питание, потом USB)"
)


class Heartbeat:
    """Периодический опрос спулера и отправка статуса принтера на сервер."""

    def __init__(self, client: ServerClient, spooler: Spooler, interval_s: float) -> None:
        self._client = client
        self._spooler = spooler
        self._interval_s = interval_s
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status: str | None = None

    def beat(self) -> str:
        """Спросить статус у спулера, отправить на сервер и вернуть статус.

        Исключения спулера приводятся к статусу 'unknown'.
        Исключение AuthError от клиента пробрасывается наружу.
        При смене статуса выполняется запись в лог (для 'offline' с подсказкой).
        """
        try:
            status = self._spooler.printer_status()
        except Exception as exc:
            log.warning("Ошибка при опросе статуса спулера: %s", exc)
            status = "unknown"

        if status != self._last_status:
            if status == "offline":
                log.warning("Статус принтера: %s. %s", status, OFFLINE_HINT)
            else:
                log.info("Статус принтера: %s", status)
            self._last_status = status

        self._client.heartbeat(status)
        return status

    def _run(self) -> None:
        """Рабочий цикл фонового потока heartbeat."""
        while not self._stop_event.is_set():
            try:
                self.beat()
            except AuthError:
                log.error("Сервер не принял токен агента при heartbeat: требуется новый токен")
                break
            except Exception:
                log.exception("Непредвиденная ошибка в фоновом потоке heartbeat")
            self._stop_event.wait(self._interval_s)

    def start(self) -> None:
        """Запустить фоновый daemon-поток heartbeat."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="HeartbeatThread", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Остановить фоновый поток и ожидать завершения с таймаутом."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
