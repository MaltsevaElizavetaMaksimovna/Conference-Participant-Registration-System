"""Три независимых терминала для общего запуска S-06 с двумя панелями."""

import csv
import os
from pathlib import Path
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

import gevent
from gevent.event import Event
from locust import HttpUser, events, task
from locust.exception import StopUser
from s06_metrics import record_confirmation_started, sample, wait_for_panels
from terminal_agents import expect_job, run_agent

_started_at = 0.0
_scheduled_at = 0.0
_regular_done: set[int] = set()
_registered: set[tuple[int, str]] = set()
_assignments: dict[int, list[str]] = {}
_all_regular_done = Event()
_race_ready = Event()
_race_scans: set[int] = set()
_race_replies: dict[int, str] = {}


def read_assignments(path: Path) -> dict[int, list[str]]:
    rows: dict[int, dict[int, str]] = {1: {}, 2: {}, 3: {}}
    used: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not {
            "external_id",
            "terminal_index",
            "order",
        }.issubset(reader.fieldnames):
            raise ValueError("assignments columns")
        for row in reader:
            number = int(row["terminal_index"])
            order = int(row["order"])
            raw = row["external_id"].strip()
            if (
                number not in rows
                or order < 0
                or order in rows[number]
                or not raw
                or raw in used
            ):
                raise ValueError("assignment duplicated or invalid")
            used.add(raw)
            rows[number][order] = raw
    if not all(rows.values()):
        raise ValueError("all terminals need assignments")
    return {
        number: [raw for _, raw in sorted(values.items())]
        for number, values in rows.items()
    }


@events.test_start.add_listener
def reset_terminals(**_kwargs) -> None:
    global _started_at, _scheduled_at
    _started_at = perf_counter()
    _scheduled_at = 0.0
    _regular_done.clear()
    _registered.clear()
    _assignments.clear()
    _all_regular_done.clear()
    _race_scans.clear()
    _race_replies.clear()
    _race_ready.clear()


@events.test_stop.add_listener
def check_completed_series(**_kwargs) -> None:
    for terminal_index, external_ids in _assignments.items():
        if any((terminal_index, raw) not in _registered for raw in external_ids):
            sample(
                f"terminal-{terminal_index}",
                "terminal_registration_series",
                _started_at,
                error_code="terminal_incomplete_series",
            )
    if os.getenv("RS_LOAD_RACE_EXTERNAL_ID") and sorted(_race_replies.values()) != [
        "already_registered",
        "registered",
    ]:
        sample(
            "terminal-race",
            "terminal_race",
            _started_at,
            error_code="race_result_mismatch",
        )


class Terminal(HttpUser):
    abstract = True
    number: int

    def on_start(self) -> None:
        global _scheduled_at
        self.alias = f"terminal-{self.number}"
        self.worker = None
        self.finished = False
        try:
            self.run_id = os.environ["RS_LOAD_RUN_ID"]
            if not self.run_id:
                raise ValueError("empty run id")
            multiplier = int(os.getenv("RS_LOAD_RATE_MULTIPLIER", "1"))
            if multiplier not in {1, 5}:
                raise ValueError("unsupported rate")
            self.period_s = 18 / multiplier
            delay = float(os.getenv("RS_LOAD_START_DELAY_S", "10"))
            if delay < 0:
                raise ValueError("negative warm-up")
            self.race_id = os.getenv("RS_LOAD_RACE_EXTERNAL_ID", "").strip()
            if not _assignments:
                _assignments.update(
                    read_assignments(Path(os.environ["RS_LOAD_ASSIGNMENTS"]))
                )
            if self.race_id and any(
                self.race_id in ids for ids in _assignments.values()
            ):
                raise ValueError("race participant must be separate")
            terminal_token = _device_tokens("TERMINAL")[self.number]
            agent_token = _device_tokens("AGENT")[self.number]
        except (OSError, KeyError, ValueError, TypeError, AttributeError, csv.Error):
            sample(
                self.alias,
                "terminal_setup",
                perf_counter(),
                error_code="terminal_setup_invalid",
            )
            raise StopUser() from None

        if not wait_for_panels(timeout=10):
            sample(
                self.alias,
                "terminal_setup",
                perf_counter(),
                error_code="panel_sse_not_ready",
            )
            raise StopUser()
        if not _scheduled_at:
            _scheduled_at = max(_started_at + delay, perf_counter())
        self.first_at = _scheduled_at + (self.number - 1) * 6 / multiplier
        self.client.headers["Authorization"] = f"Terminal {terminal_token}"
        ca = os.getenv("RS_LOAD_CA")
        if ca:
            self.client.verify = ca
        self.worker = gevent.spawn(
            run_agent, self.client.base_url, agent_token, self.number, ca
        )

    def on_stop(self) -> None:
        if self.worker is not None:
            self.worker.kill()

    @task
    def series(self) -> None:
        if self.finished:
            gevent.sleep(1)
            return
        for index, external_id in enumerate(_assignments[self.number]):
            gevent.sleep(max(0, self.first_at + index * self.period_s - perf_counter()))
            if self.register_one(self.run_id, self.number, external_id) == "registered":
                _registered.add((self.number, external_id))
        _regular_done.add(self.number)
        if len(_regular_done) == 3:
            _all_regular_done.set()
        if self.race_id and self.number in {1, 2}:
            _all_regular_done.wait()
            result = self.register_one(
                self.run_id, self.number, self.race_id, race=True
            )
            if result:
                _race_replies[self.number] = result
        self.finished = True

    def register_one(
        self, run_id: str, terminal_index: int, external_id: str, *, race: bool = False
    ) -> str | None:
        scanned = self._scan(external_id)
        if scanned is None:
            return None
        participant_id, scan_id = scanned
        if race:
            _race_scans.add(terminal_index)
            if len(_race_scans) == 2:
                _race_ready.set()
            if not _race_ready.wait(timeout=15):
                sample(
                    self.alias,
                    "terminal_race",
                    perf_counter(),
                    error_code="race_scan_missing",
                )
                return None

        key = str(uuid5(NAMESPACE_URL, f"{run_id}:{terminal_index}:{external_id}"))
        started_at = perf_counter()
        record_confirmation_started(participant_id, started_at)
        with self.client.post(
            "/api/terminal/confirm",
            headers={"Idempotency-Key": key},
            json={"participant_id": participant_id, "scan_id": scan_id},
            catch_response=True,
            timeout=10,
        ) as response:
            payload = _json_object(response)
            outcome = payload.get("result")
            job_id = payload.get("print_job_id")
            expected_success = outcome == "registered" and type(job_id) is int
            expected_loser = race and outcome == "already_registered" and job_id is None
            error = (
                "" if expected_success or expected_loser else "terminal_confirm_invalid"
            )
            if error:
                response.failure(error)
            sample(
                self.alias,
                "terminal_confirm_api_ms",
                started_at,
                participant_id=participant_id,
                error_code=error,
            )
            if error:
                return None
            if expected_success:
                expect_job(job_id, participant_id, started_at, terminal_index)
            return outcome

    def _scan(self, external_id: str) -> tuple[int, str] | None:
        started_at = perf_counter()
        with self.client.post(
            "/api/terminal/scan",
            json={"raw": external_id},
            catch_response=True,
            timeout=10,
        ) as response:
            payload = _json_object(response)
            participant = payload.get("participant")
            pid = participant.get("id") if isinstance(participant, dict) else None
            scan_id = payload.get("scan_id")
            valid = (
                payload.get("result") == "found"
                and type(pid) is int
                and isinstance(scan_id, str)
            )
            code = "" if valid else "terminal_scan_invalid"
            if code:
                response.failure(code)
            sample(
                self.alias,
                "terminal_scan_api_ms",
                started_at,
                participant_id=pid if type(pid) is int else None,
                limit_ms=2000,
                error_code=code,
            )
            return (pid, scan_id) if valid else None


def _device_tokens(kind: str) -> dict[int, str]:
    tokens = {n: os.environ[f"RS_LOAD_{kind}_{n}_TOKEN"].strip() for n in (1, 2, 3)}
    if not all(tokens.values()) or len(set(tokens.values())) != 3:
        raise ValueError("each device needs a distinct token")
    return tokens


def _json_object(response) -> dict:
    if response.status_code != 200:
        return {}
    try:
        result = response.json()
    except ValueError:
        return {}
    return result if isinstance(result, dict) else {}


class TerminalOne(Terminal):
    number = 1
    fixed_count = 1


class TerminalTwo(Terminal):
    number = 2
    fixed_count = 1


class TerminalThree(Terminal):
    number = 3
    fixed_count = 1
