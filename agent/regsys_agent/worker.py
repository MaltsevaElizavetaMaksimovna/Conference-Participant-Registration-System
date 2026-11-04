"""Цикл агента: взять задание, напечатать, сообщить итог (B2-12, TR-04, TR-08).

Порядок важен для отсутствия дублей (см. `journal.py`):
1. неотправленные итоги — серверу, до новых заданий;
2. задание → запись `started` → спулер → ожидание → запись `finished` → итог серверу;
3. сервер недоступен — итог остаётся в журнале и уходит на следующем круге.
"""

import logging
from dataclasses import dataclass

from regsys_agent.api import Job, ServerClient
from regsys_agent.journal import Journal
from regsys_agent.spooler import PrintOutcome, Spooler
from regsys_agent.tspl import build_job

log = logging.getLogger(__name__)

DOC_PREFIX = "regsys-job-"


@dataclass(frozen=True)
class PrintTiming:
    spool_timeout_s: float = 10  # задание должно уйти из очереди Windows за это время
    settle_s: float = 3  # и принтер не должен уйти в «автономно» сразу после (S-04)
    stale_after_s: float = 30  # наше задание висит в очереди дольше — удаляем (не печатать позже)


class Worker:
    def __init__(
        self,
        client: ServerClient,
        spooler: Spooler,
        journal: Journal,
        timing: PrintTiming | None = None,
    ) -> None:
        self._client = client
        self._spooler = spooler
        self._journal = journal
        self._timing = timing or PrintTiming()

    def start(self) -> None:
        """При запуске: прерванные печати — в ошибки, старые задания — из очереди Windows."""
        for job_id in self._journal.recover():
            log.warning("Задание %s прервано перезапуском агента: считаем ненапечатанным", job_id)
        purged = self._spooler.purge_stale(DOC_PREFIX, 0)
        if purged:
            log.warning("Удалено зависших заданий из очереди Windows: %s", purged)
        self._journal.compact()

    def flush_results(self) -> None:
        """Отправить итоги, которые сервер ещё не принял. Ошибка сети — попробуем позже."""
        for rec in self._journal.unsent():
            assert rec.ok is not None
            if not self._client.send_result(rec.job_id, rec.ok, rec.error):
                log.info("Сервер недоступен, итог задания %s отправим позже", rec.job_id)
                return
            self._journal.sent(rec.job_id)

    def run_once(self, wait_s: int) -> None:
        """Один круг long-poll. Исключения сети пробрасываются: цикл снаружи подождёт."""
        self.flush_results()
        self._spooler.purge_stale(DOC_PREFIX, self._timing.stale_after_s)
        job = self._client.next_job(wait_s)
        if job is not None:
            self.handle(job)

    def handle(self, job: Job) -> None:
        if self._journal.get(job.job_id) is None:
            self._journal.started(job.job_id)
            outcome = self._print(job)
            self._journal.finished(job.job_id, outcome.ok, outcome.error)
            log.info("Задание %s: %s", job.job_id, "напечатано" if outcome.ok else outcome.error)
        else:
            log.warning("Задание %s уже обрабатывалось: повторно не печатаем", job.job_id)
        self.flush_results()

    def _print(self, job: Job) -> PrintOutcome:
        try:
            self._spooler.ensure_online()
            spool_id = self._spooler.submit(build_job(job), f"{DOC_PREFIX}{job.job_id}")
            return self._spooler.wait_printed(
                spool_id, self._timing.spool_timeout_s, self._timing.settle_s
            )
        except Exception as e:  # принтер пропал из системы, ошибка win32 и т. п.
            log.exception("Ошибка печати задания %s", job.job_id)
            return PrintOutcome(False, f"Ошибка печати: {e}"[:500])
