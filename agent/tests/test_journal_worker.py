"""Идемпотентность агента по job_id (B2-12): без двойной печати и без потерянных итогов."""

from pathlib import Path

import pytest

from regsys_agent.api import Job
from regsys_agent.journal import AGENT_RESTARTED, KEEP_CLOSED, Journal
from regsys_agent.spooler import PrintOutcome
from regsys_agent.worker import DOC_PREFIX, Worker


class FakeClient:
    def __init__(self, jobs: list[Job] | None = None) -> None:
        self.jobs = list(jobs or [])
        self.results: list[tuple[int, bool, str | None]] = []
        self.online = True

    def next_job(self, wait_s: int) -> Job | None:
        return self.jobs.pop(0) if self.jobs else None

    def send_result(self, job_id: int, ok: bool, error: str | None) -> bool:
        if not self.online:
            return False
        self.results.append((job_id, ok, error))
        return True


class FakeSpooler:
    def __init__(self, outcome: PrintOutcome | None = None) -> None:
        self.outcome = outcome or PrintOutcome(True)
        self.submitted: list[str] = []
        self.purged: list[float] = []
        self.fail_submit = False

    def printer_status(self) -> str:
        return "ready"

    def ensure_online(self) -> None:
        pass

    def submit(self, data: bytes, doc_name: str) -> int:
        if self.fail_submit:
            raise OSError("принтер пропал")
        self.submitted.append(doc_name)
        return len(self.submitted)

    def wait_printed(self, spool_job_id: int, timeout_s: float, settle_s: float) -> PrintOutcome:
        return self.outcome

    def purge_stale(self, doc_prefix: str, older_than_s: float) -> int:
        self.purged.append(older_than_s)
        return 0


def job(job_id: int) -> Job:
    return Job(job_id=job_id, copies=[])


@pytest.fixture(autouse=True)
def _no_tspl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Здесь проверяется порядок действий, а не TSPL: пустое задание."""
    monkeypatch.setattr("regsys_agent.worker.build_job", lambda j: b"")


def make(tmp_path: Path, client: FakeClient, spooler: FakeSpooler) -> tuple[Worker, Journal]:
    journal = Journal(tmp_path / "journal.jsonl")
    return Worker(client, spooler, journal), journal  # type: ignore[arg-type]


def test_job_printed_once_and_reported(tmp_path: Path) -> None:
    client, spooler = FakeClient([job(7)]), FakeSpooler()
    worker, journal = make(tmp_path, client, spooler)

    worker.run_once(0)

    assert spooler.submitted == [f"{DOC_PREFIX}7"]
    assert client.results == [(7, True, None)]
    rec = journal.get(7)
    assert rec is not None and rec.state == "sent"


def test_same_job_again_is_not_printed_twice(tmp_path: Path) -> None:
    client, spooler = FakeClient([job(7), job(7)]), FakeSpooler()
    worker, _ = make(tmp_path, client, spooler)

    worker.run_once(0)
    worker.run_once(0)

    assert spooler.submitted == [f"{DOC_PREFIX}7"]


def test_result_kept_while_server_is_down(tmp_path: Path) -> None:
    client, spooler = FakeClient([job(7)]), FakeSpooler(PrintOutcome(False, "нет ленты"))
    client.online = False
    worker, journal = make(tmp_path, client, spooler)

    worker.run_once(0)
    assert client.results == []
    assert [r.job_id for r in journal.unsent()] == [7]

    client.online = True
    worker.run_once(0)  # сначала досылаем итог, потом новые задания
    assert client.results == [(7, False, "нет ленты")]
    assert spooler.submitted == [f"{DOC_PREFIX}7"]


def test_unsent_result_survives_restart(tmp_path: Path) -> None:
    client, spooler = FakeClient([job(7)]), FakeSpooler()
    client.online = False
    worker, _ = make(tmp_path, client, spooler)
    worker.run_once(0)

    client2 = FakeClient()
    worker2, _ = make(tmp_path, client2, FakeSpooler())  # агент перезапущен
    worker2.start()
    worker2.flush_results()

    assert client2.results == [(7, True, None)]


def test_crash_during_print_is_reported_not_reprinted(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.jsonl")
    journal.started(9)  # агент упал после записи и до итога

    client, spooler = FakeClient([job(9)]), FakeSpooler()
    worker, _ = make(tmp_path, client, spooler)
    worker.start()
    worker.run_once(0)

    assert spooler.submitted == []  # повторно не печатаем
    assert client.results == [(9, False, AGENT_RESTARTED)]
    assert spooler.purged[0] == 0  # при запуске убраны все наши зависшие задания


def test_spooler_exception_becomes_error_result(tmp_path: Path) -> None:
    client, spooler = FakeClient([job(3)]), FakeSpooler()
    spooler.fail_submit = True
    worker, _ = make(tmp_path, client, spooler)

    worker.run_once(0)

    [(job_id, ok, error)] = client.results
    assert (job_id, ok) == (3, False)
    assert error and "принтер пропал" in error


def test_journal_ignores_torn_line_and_compacts(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    journal = Journal(path)
    for i in range(1, KEEP_CLOSED + 11):
        journal.started(i)
        journal.finished(i, True, None)
        journal.sent(i)
    journal.started(10_000)
    with path.open("a", encoding="utf-8") as f:
        f.write('{"job_id": 10001, "sta')  # оборванная запись при выключении

    reloaded = Journal(path)
    assert reloaded.get(10_001) is None
    reloaded.compact()

    again = Journal(path)
    assert again.get(1) is None  # старые закрытые удалены
    assert again.get(KEEP_CLOSED + 10) is not None
    rec = again.get(10_000)
    assert rec is not None and rec.state == "started"  # открытое не теряется
