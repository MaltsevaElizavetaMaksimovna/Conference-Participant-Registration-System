"""Тесты модуля работы со спулером Windows на поддельном Win32 API."""

from __future__ import annotations

from typing import Any

from regsys_agent.spooler import (
    PRINTER_ATTRIBUTE_WORK_OFFLINE,
    PRINTER_OFF,
    PRINTER_STATUS_DOOR_OPEN,
    PRINTER_STATUS_ERROR,
    PRINTER_STATUS_NOT_AVAILABLE,
    PRINTER_STATUS_OFFLINE,
    PRINTER_STATUS_PAPER_JAM,
    PRINTER_STATUS_PAPER_OUT,
    Win32Spooler,
)


class FakeWin32Api:
    """Поддельный API win32print для автономного тестирования."""

    def __init__(
        self,
        printers: list[dict[str, Any]] | None = None,
        jobs: list[dict[str, Any]] | None = None,
    ) -> None:
        self.printers: list[dict[str, Any]] = printers or []
        self.jobs: list[dict[str, Any]] = jobs or []
        self.deleted_jobs: list[int] = []
        self.set_printer_calls: list[tuple[Any, int, dict[str, Any], int]] = []
        self.raise_on_enum: bool = False
        self.raise_on_open: bool = False

    def enum_printers(self) -> list[dict[str, Any]]:
        if self.raise_on_enum:
            raise RuntimeError("Win32 EnumPrinters error")
        return [dict(p) for p in self.printers]

    def open_printer(self, name: str, defaults: Any = None) -> Any:
        if self.raise_on_open:
            raise RuntimeError("Win32 OpenPrinter access denied")
        matching = [p for p in self.printers if p.get("pPrinterName") == name]
        if not matching:
            raise RuntimeError(f"Printer not found: {name}")
        return f"handle_{name}"

    def close_printer(self, handle: Any) -> None:
        pass

    def get_printer(self, handle: Any, level: int = 2) -> dict[str, Any]:
        printer_name = str(handle).removeprefix("handle_")
        for p in self.printers:
            if p.get("pPrinterName") == printer_name:
                return dict(p)
        raise RuntimeError(f"Printer not found: {printer_name}")

    def set_printer(self, handle: Any, level: int, info: dict[str, Any], command: int) -> None:
        self.set_printer_calls.append((handle, level, dict(info), command))
        printer_name = str(handle).removeprefix("handle_")
        for p in self.printers:
            if p.get("pPrinterName") == printer_name:
                p.update(info)

    def start_doc_printer(self, handle: Any, level: int, doc_info: tuple[Any, ...]) -> int:
        return 777

    def start_page_printer(self, handle: Any) -> None:
        pass

    def write_printer(self, handle: Any, data: bytes) -> int:
        return len(data)

    def end_page_printer(self, handle: Any) -> None:
        pass

    def end_doc_printer(self, handle: Any) -> None:
        pass

    def enum_jobs(
        self, handle: Any, first_job: int, no_jobs: int, level: int
    ) -> list[dict[str, Any]]:
        return [dict(j) for j in self.jobs]

    def set_job(self, handle: Any, job_id: int, level: int, job_info: Any, command: int) -> None:
        self.deleted_jobs.append(job_id)
        self.jobs = [j for j in self.jobs if j.get("JobId") != job_id]


class FakeClock:
    """Управление виртуальным временем для детерминированных тестов."""

    def __init__(self) -> None:
        self.time: float = 0.0

    def clock(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.time += seconds


def test_printer_status_variants() -> None:
    """Проверка всех состояний принтера: offline, error, ready, unknown."""
    printer_name = "XP-360B"

    # Принтера нет в системе -> offline
    api = FakeWin32Api(printers=[])
    spooler = Win32Spooler(printer_name, api=api)
    assert spooler.printer_status() == "offline"

    # Атрибут WORK_OFFLINE -> offline
    api = FakeWin32Api(
        printers=[
            {
                "pPrinterName": printer_name,
                "Attributes": PRINTER_ATTRIBUTE_WORK_OFFLINE,
                "Status": 0,
            }
        ]
    )
    spooler = Win32Spooler(printer_name, api=api)
    assert spooler.printer_status() == "offline"

    # Статус OFFLINE -> offline
    api = FakeWin32Api(
        printers=[
            {
                "pPrinterName": printer_name,
                "Attributes": 0,
                "Status": PRINTER_STATUS_OFFLINE,
            }
        ]
    )
    spooler = Win32Spooler(printer_name, api=api)
    assert spooler.printer_status() == "offline"

    # Ошибочные статусы -> error
    for error_flag in (
        PRINTER_STATUS_ERROR,
        PRINTER_STATUS_PAPER_OUT,
        PRINTER_STATUS_PAPER_JAM,
        PRINTER_STATUS_DOOR_OPEN,
        PRINTER_STATUS_NOT_AVAILABLE,
    ):
        api = FakeWin32Api(
            printers=[
                {
                    "pPrinterName": printer_name,
                    "Attributes": 0,
                    "Status": error_flag,
                }
            ]
        )
        spooler = Win32Spooler(printer_name, api=api)
        assert spooler.printer_status() == "error"

    # Готов -> ready
    api = FakeWin32Api(printers=[{"pPrinterName": printer_name, "Attributes": 0, "Status": 0}])
    spooler = Win32Spooler(printer_name, api=api)
    assert spooler.printer_status() == "ready"

    # Ошибка Win32 API -> unknown
    api = FakeWin32Api(printers=[{"pPrinterName": printer_name, "Attributes": 0, "Status": 0}])
    api.raise_on_enum = True
    spooler = Win32Spooler(printer_name, api=api)
    assert spooler.printer_status() == "unknown"


def test_ensure_online_removes_work_offline_bit() -> None:
    """ensure_online снимает только бит 0x400 и сохраняет остальные атрибуты."""
    printer_name = "XP-360B"
    initial_attrs = PRINTER_ATTRIBUTE_WORK_OFFLINE | 0x004  # WORK_OFFLINE + DEFAULT
    api = FakeWin32Api(
        printers=[{"pPrinterName": printer_name, "Attributes": initial_attrs, "Status": 0}]
    )
    spooler = Win32Spooler(printer_name, api=api)

    spooler.ensure_online()

    assert api.printers[0]["Attributes"] == 0x004
    assert len(api.set_printer_calls) == 1


def test_ensure_online_handles_permission_error() -> None:
    """При отказе в доступе ensure_online не падает с исключением."""
    printer_name = "XP-360B"
    api = FakeWin32Api(
        printers=[
            {
                "pPrinterName": printer_name,
                "Attributes": PRINTER_ATTRIBUTE_WORK_OFFLINE,
                "Status": 0,
            }
        ]
    )
    api.raise_on_open = True
    spooler = Win32Spooler(printer_name, api=api)

    # Не должно выбрасывать исключений
    spooler.ensure_online()


def test_submit_sends_raw_data() -> None:
    """Отправка задания через submit возвращает идентификатор задания."""
    printer_name = "XP-360B"
    api = FakeWin32Api(printers=[{"pPrinterName": printer_name, "Attributes": 0, "Status": 0}])
    spooler = Win32Spooler(printer_name, api=api)

    spool_id = spooler.submit(b"RAW_DATA", "job-1")
    assert spool_id == 777


def test_wait_printed_immediate_success() -> None:
    """Задание сразу исчезло из очереди и принтер остался online -> ok True."""
    printer_name = "XP-360B"
    api = FakeWin32Api(
        printers=[{"pPrinterName": printer_name, "Attributes": 0, "Status": 0}],
        jobs=[],  # Задания уже нет в очереди
    )
    clk = FakeClock()
    spooler = Win32Spooler(printer_name, poll_s=0.25, clock=clk.clock, sleep=clk.sleep, api=api)

    outcome = spooler.wait_printed(spool_job_id=42, timeout_s=10.0, settle_s=3.0)

    assert outcome.ok is True
    assert outcome.error is None
    # Должен был пройти этап settle (3 секунды)
    assert clk.time >= 3.0
    assert 42 not in api.deleted_jobs


def test_wait_printed_timeout_deletes_job() -> None:
    """Задание не исчезло за timeout_s -> ok False, PRINTER_OFF, задание удалено."""
    printer_name = "XP-360B"
    api = FakeWin32Api(
        printers=[{"pPrinterName": printer_name, "Attributes": 0, "Status": 0}],
        jobs=[{"JobId": 42, "pDocument": "regsys-job-42"}],
    )
    clk = FakeClock()
    spooler = Win32Spooler(printer_name, poll_s=0.25, clock=clk.clock, sleep=clk.sleep, api=api)

    outcome = spooler.wait_printed(spool_job_id=42, timeout_s=5.0, settle_s=3.0)

    assert outcome.ok is False
    assert outcome.error == PRINTER_OFF
    assert 42 in api.deleted_jobs
    assert clk.time >= 5.0


def test_wait_printed_offline_during_settle_fails() -> None:
    """Задание исчезло, но во время settle принтер ушёл в offline -> ok False."""
    printer_name = "XP-360B"
    api = FakeWin32Api(
        printers=[{"pPrinterName": printer_name, "Attributes": 0, "Status": 0}],
        jobs=[],  # Исчезло сразу
    )
    clk = FakeClock()

    def sleep_and_go_offline(s: float) -> None:
        clk.sleep(s)
        if clk.time >= 1.0:
            api.printers[0]["Status"] = PRINTER_STATUS_OFFLINE

    spooler = Win32Spooler(
        printer_name, poll_s=0.25, clock=clk.clock, sleep=sleep_and_go_offline, api=api
    )

    outcome = spooler.wait_printed(spool_job_id=42, timeout_s=10.0, settle_s=3.0)

    assert outcome.ok is False
    assert outcome.error == PRINTER_OFF
    assert 42 in api.deleted_jobs


def test_purge_stale_deletes_only_matching_prefix() -> None:
    """purge_stale удаляет только задания с совпадающим префиксом документа."""
    printer_name = "XP-360B"
    api = FakeWin32Api(
        printers=[{"pPrinterName": printer_name, "Attributes": 0, "Status": 0}],
        jobs=[
            {"JobId": 1, "pDocument": "regsys-job-1"},
            {"JobId": 2, "pDocument": "regsys-job-2"},
            {"JobId": 3, "pDocument": "unrelated-document"},
        ],
    )
    spooler = Win32Spooler(printer_name, api=api)

    purged = spooler.purge_stale("regsys-job-", older_than_s=0)

    assert purged == 2
    assert 1 in api.deleted_jobs
    assert 2 in api.deleted_jobs
    assert 3 not in api.deleted_jobs
    remaining_ids = [j["JobId"] for j in api.jobs]
    assert remaining_ids == [3]
