"""Взаимодействие со спулером печати Windows через pywin32."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)

PRINTER_OFF = "Принтер не отвечает: выключен, не подключён или нет ленты"

# Атрибуты принтера (Win32 API)
PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x400

# Статусы принтера (Win32 API)
PRINTER_STATUS_OFFLINE = 0x80
PRINTER_STATUS_ERROR = 0x2
PRINTER_STATUS_PAPER_OUT = 0x10
PRINTER_STATUS_PAPER_JAM = 0x8
PRINTER_STATUS_DOOR_OPEN = 0x400000
PRINTER_STATUS_NOT_AVAILABLE = 0x1000

# Константы управления заданиями и принтером
JOB_CONTROL_DELETE = 5
PRINTER_ALL_ACCESS = 0xF000C


@dataclass(frozen=True)
class PrintOutcome:
    """Результат выполнения печати задания спулером."""

    ok: bool
    error: str | None = None


class Spooler(Protocol):
    """Протокол управления очередью печати и опроса принтера."""

    def printer_status(self) -> str: ...
    def ensure_online(self) -> None: ...
    def submit(self, data: bytes, doc_name: str) -> int: ...
    def wait_printed(
        self, spool_job_id: int, timeout_s: float, settle_s: float
    ) -> PrintOutcome: ...
    def purge_stale(self, doc_prefix: str, older_than_s: float) -> int: ...


class _Win32ApiProtocol(Protocol):
    """Протокол используемых функций win32print для легкой подмены в тестах."""

    def enum_printers(self) -> list[dict[str, Any]]: ...
    def open_printer(self, name: str, defaults: Any = None) -> Any: ...
    def close_printer(self, handle: Any) -> None: ...
    def get_printer(self, handle: Any, level: int = 2) -> dict[str, Any]: ...
    def set_printer(self, handle: Any, level: int, info: dict[str, Any], command: int) -> None: ...
    def start_doc_printer(self, handle: Any, level: int, doc_info: tuple[Any, ...]) -> int: ...
    def start_page_printer(self, handle: Any) -> None: ...
    def write_printer(self, handle: Any, data: bytes) -> int: ...
    def end_page_printer(self, handle: Any) -> None: ...
    def end_doc_printer(self, handle: Any) -> None: ...
    def enum_jobs(
        self, handle: Any, first_job: int, no_jobs: int, level: int
    ) -> list[dict[str, Any]]: ...
    def set_job(
        self, handle: Any, job_id: int, level: int, job_info: Any, command: int
    ) -> None: ...


class _Win32Api:
    """Тонкая обёртка над win32print для ленивой загрузки и изоляции."""

    def __init__(self) -> None:
        try:
            import win32print  # type: ignore[import-untyped,unused-ignore]

            self._w: Any = win32print
        except ImportError:
            self._w = None

    def _check(self) -> Any:
        if self._w is None:
            raise RuntimeError("Модуль win32print недоступен в данной системе")
        return self._w

    def enum_printers(self) -> list[dict[str, Any]]:
        w = self._check()
        flags = w.PRINTER_ENUM_LOCAL | w.PRINTER_ENUM_CONNECTIONS
        return list(w.EnumPrinters(flags, None, 2))

    def open_printer(self, name: str, defaults: Any = None) -> Any:
        w = self._check()
        if defaults is not None:
            return w.OpenPrinter(name, defaults)
        return w.OpenPrinter(name)

    def close_printer(self, handle: Any) -> None:
        w = self._check()
        w.ClosePrinter(handle)

    def get_printer(self, handle: Any, level: int = 2) -> dict[str, Any]:
        w = self._check()
        return dict(w.GetPrinter(handle, level))

    def set_printer(self, handle: Any, level: int, info: dict[str, Any], command: int) -> None:
        w = self._check()
        w.SetPrinter(handle, level, info, command)

    def start_doc_printer(self, handle: Any, level: int, doc_info: tuple[Any, ...]) -> int:
        w = self._check()
        return int(w.StartDocPrinter(handle, level, doc_info))

    def start_page_printer(self, handle: Any) -> None:
        w = self._check()
        w.StartPagePrinter(handle)

    def write_printer(self, handle: Any, data: bytes) -> int:
        w = self._check()
        return int(w.WritePrinter(handle, data))

    def end_page_printer(self, handle: Any) -> None:
        w = self._check()
        w.EndPagePrinter(handle)

    def end_doc_printer(self, handle: Any) -> None:
        w = self._check()
        w.EndDocPrinter(handle)

    def enum_jobs(
        self, handle: Any, first_job: int, no_jobs: int, level: int
    ) -> list[dict[str, Any]]:
        w = self._check()
        return list(w.EnumJobs(handle, first_job, no_jobs, level) or [])

    def set_job(self, handle: Any, job_id: int, level: int, job_info: Any, command: int) -> None:
        w = self._check()
        w.SetJob(handle, job_id, level, job_info, command)


class Win32Spooler:
    """Реализация Spooler для спулера печати Windows."""

    def __init__(
        self,
        printer_name: str,
        *,
        poll_s: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        api: _Win32ApiProtocol | None = None,
    ) -> None:
        self._printer_name = printer_name
        self._poll_s = poll_s
        self._clock = clock
        self._sleep = sleep
        self._api = api if api is not None else _Win32Api()
        self._seen_jobs: dict[int, float] = {}

    def printer_status(self) -> str:
        """Статус принтера: 'ready', 'offline', 'error' или 'unknown'."""
        try:
            printers = self._api.enum_printers()
            matching = [p for p in printers if p.get("pPrinterName") == self._printer_name]
            if not matching:
                return "offline"

            p_info = matching[0]
            attrs = p_info.get("Attributes", 0)
            status = p_info.get("Status", 0)

            try:
                h = self._api.open_printer(self._printer_name)
                try:
                    info = self._api.get_printer(h, 2)
                    attrs = info.get("Attributes", attrs)
                    status = info.get("Status", status)
                finally:
                    self._api.close_printer(h)
            except Exception:
                pass

            if bool(attrs & PRINTER_ATTRIBUTE_WORK_OFFLINE) or bool(
                status & PRINTER_STATUS_OFFLINE
            ):
                return "offline"

            if bool(
                status
                & (
                    PRINTER_STATUS_ERROR
                    | PRINTER_STATUS_PAPER_OUT
                    | PRINTER_STATUS_PAPER_JAM
                    | PRINTER_STATUS_DOOR_OPEN
                    | PRINTER_STATUS_NOT_AVAILABLE
                )
            ):
                return "error"

            return "ready"
        except Exception as e:
            log.warning("Ошибка Win32 при получении статуса принтера %s: %s", self._printer_name, e)
            return "unknown"

    def ensure_online(self) -> None:
        """Снять режим «Работать автономно» (PRINTER_ATTRIBUTE_WORK_OFFLINE), если он установлен."""
        try:
            h = self._api.open_printer(self._printer_name, {"DesiredAccess": PRINTER_ALL_ACCESS})
        except Exception as e:
            log.warning(
                "Не удалось открыть принтер «%s» для снятия автономного режима: %s",
                self._printer_name,
                e,
            )
            return

        try:
            info = self._api.get_printer(h, 2)
            attrs = info.get("Attributes", 0)
            if attrs & PRINTER_ATTRIBUTE_WORK_OFFLINE:
                info["Attributes"] = attrs & ~PRINTER_ATTRIBUTE_WORK_OFFLINE
                self._api.set_printer(h, 2, info, 0)
                log.info("Режим «Работать автономно» снят для принтера «%s»", self._printer_name)
        except Exception as e:
            log.warning(
                "Не удалось снять автономный режим принтера «%s»: %s",
                self._printer_name,
                e,
            )
        finally:
            with contextlib.suppress(Exception):
                self._api.close_printer(h)

    def submit(self, data: bytes, doc_name: str) -> int:
        """Отправить RAW-задание в спулер Windows. Возвращает номер задания в очереди."""
        h = self._api.open_printer(self._printer_name)
        try:
            job_id = self._api.start_doc_printer(h, 1, (doc_name, None, "RAW"))
            try:
                self._api.start_page_printer(h)
                self._api.write_printer(h, data)
                self._api.end_page_printer(h)
            finally:
                self._api.end_doc_printer(h)
            return job_id
        finally:
            self._api.close_printer(h)

    def _delete_job(self, job_id: int) -> None:
        """Удалить задание из очереди печати, игнорируя возможные ошибки."""
        try:
            h = self._api.open_printer(self._printer_name)
            try:
                self._api.set_job(h, job_id, 0, None, JOB_CONTROL_DELETE)
            finally:
                self._api.close_printer(h)
        except Exception:
            pass

    def _is_job_present(self, job_id: int) -> bool:
        """Проверить, находится ли задание ещё в очереди Windows."""
        try:
            h = self._api.open_printer(self._printer_name)
            try:
                jobs = self._api.enum_jobs(h, 0, -1, 1)
                return any(j.get("JobId") == job_id for j in jobs)
            finally:
                self._api.close_printer(h)
        except Exception:
            return True

    def wait_printed(self, spool_job_id: int, timeout_s: float, settle_s: float) -> PrintOutcome:
        """Ожидать завершения печати задания спулером Windows."""
        t_start = self._clock()

        while True:
            if self.printer_status() == "offline":
                self._delete_job(spool_job_id)
                return PrintOutcome(False, PRINTER_OFF)

            if not self._is_job_present(spool_job_id):
                break

            if self._clock() - t_start >= timeout_s:
                self._delete_job(spool_job_id)
                return PrintOutcome(False, PRINTER_OFF)

            self._sleep(self._poll_s)

        # Фаза отстаивания: принтер не должен перейти в offline
        t_settle = self._clock()
        while self._clock() - t_settle < settle_s:
            if self.printer_status() == "offline":
                self._delete_job(spool_job_id)
                return PrintOutcome(False, PRINTER_OFF)
            self._sleep(self._poll_s)

        if self.printer_status() == "offline":
            self._delete_job(spool_job_id)
            return PrintOutcome(False, PRINTER_OFF)

        return PrintOutcome(True)

    def purge_stale(self, doc_prefix: str, older_than_s: float) -> int:
        """Удалить зависшие задания агента из очереди Windows."""
        try:
            h = self._api.open_printer(self._printer_name)
        except Exception:
            return 0

        try:
            jobs = self._api.enum_jobs(h, 0, -1, 1)
        except Exception:
            return 0
        finally:
            with contextlib.suppress(Exception):
                self._api.close_printer(h)

        now = self._clock()
        current_job_ids = {j["JobId"] for j in jobs if "JobId" in j}
        self._seen_jobs = {jid: t for jid, t in self._seen_jobs.items() if jid in current_job_ids}

        purged = 0
        for j in jobs:
            doc = str(j.get("pDocument") or "")
            if not doc.startswith(doc_prefix):
                continue

            jid = j.get("JobId")
            if jid is None:
                continue

            first_seen = self._seen_jobs.setdefault(jid, now)
            if older_than_s == 0 or (now - first_seen >= older_than_s):
                try:
                    self._delete_job(jid)
                    purged += 1
                    self._seen_jobs.pop(jid, None)
                except Exception:
                    pass

        return purged
