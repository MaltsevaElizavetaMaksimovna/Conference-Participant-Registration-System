"""Журнал заданий агента: печать без дублей и ответ серверу без потерь (B2-12).

Файл JSON Lines, только дописывается; состояние задания — последняя запись о нём:

- `started` — задание отдаётся принтеру. Пишется ДО отправки в спулер. Если агент упал
  после этого, при запуске задание не печатается повторно, а считается ошибкой
  (`agent_restarted`): регистратор нажмёт «Напечатать повторно». Лишняя наклейка хуже
  потерянной только тем, что её не ждут, а молча напечатать дважды мы не хотим.
- `finished` — итог печати известен, но сервер его ещё не принял;
- `sent` — сервер принял итог, задание закрыто.

Сервер не выдаёт задание дважды, но журнал страхует и от этого: повторно пришедшее
задание не печатается, серверу уходит уже известный итог.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

State = Literal["started", "finished", "sent"]

AGENT_RESTARTED = "agent_restarted"
# Сколько закрытых заданий хранить после сжатия файла
KEEP_CLOSED = 500


@dataclass(frozen=True)
class Record:
    job_id: int
    state: State
    ok: bool | None = None
    error: str | None = None


class Journal:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._records: dict[int, Record] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    rec = Record(
                        job_id=int(data["job_id"]),
                        state=data["state"],
                        ok=data.get("ok"),
                        error=data.get("error"),
                    )
                except (ValueError, KeyError, TypeError):
                    continue  # строка, оборванная при сбое питания
                self._records[rec.job_id] = rec

    def _write(self, rec: Record) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"job_id": rec.job_id, "state": rec.state, "ok": rec.ok, "error": rec.error},
            ensure_ascii=False,
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())  # запись должна пережить выключение терминала
        self._records[rec.job_id] = rec

    def get(self, job_id: int) -> Record | None:
        return self._records.get(job_id)

    def started(self, job_id: int) -> None:
        self._write(Record(job_id, "started"))

    def finished(self, job_id: int, ok: bool, error: str | None) -> None:
        self._write(Record(job_id, "finished", ok, error))

    def sent(self, job_id: int) -> None:
        rec = self._records[job_id]
        self._write(Record(job_id, "sent", rec.ok, rec.error))

    def unsent(self) -> list[Record]:
        """Итоги, которые сервер ещё не принял, по порядку заданий."""
        return sorted(
            (r for r in self._records.values() if r.state == "finished"), key=lambda r: r.job_id
        )

    def recover(self) -> list[int]:
        """После запуска: прерванные печати → ошибка `agent_restarted`. Возвращает их id."""
        broken = [r.job_id for r in self._records.values() if r.state == "started"]
        for job_id in broken:
            self.finished(job_id, False, AGENT_RESTARTED)
        return broken

    def compact(self) -> None:
        """Переписать файл: все открытые задания и последние `KEEP_CLOSED` закрытых."""
        closed = sorted(j for j, r in self._records.items() if r.state == "sent")
        drop = set(closed[:-KEEP_CLOSED]) if len(closed) > KEEP_CLOSED else set()
        keep = [r for j, r in sorted(self._records.items()) if j not in drop]
        tmp = self._path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in keep:
                f.write(
                    json.dumps(
                        {"job_id": r.job_id, "state": r.state, "ok": r.ok, "error": r.error},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)
        self._records = {r.job_id: r for r in keep}
