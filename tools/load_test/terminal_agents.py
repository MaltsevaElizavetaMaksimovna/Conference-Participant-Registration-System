"""Агенты S-06 подтверждают выдачу задания без отправки наклейки на принтер."""

from dataclasses import dataclass
from time import perf_counter

import gevent
import locust
import requests
from gevent.event import AsyncResult
from s06_metrics import sample


@dataclass(frozen=True)
class ExpectedJob:
    participant_id: int
    started_at: float
    terminal_index: int


_expected: dict[int, AsyncResult] = {}
_seen: set[int] = set()
_result_reported: set[int] = set()


def expect_job(
    job_id: int, participant_id: int, started_at: float, terminal_index: int
) -> None:
    match = _expected.setdefault(job_id, AsyncResult())
    if match.ready():
        sample(
            f"terminal-{terminal_index}",
            "terminal_print_job",
            started_at,
            participant_id=participant_id,
            error_code="job_id_reused",
        )
        return
    match.set(ExpectedJob(participant_id, started_at, terminal_index))


@locust.events.test_start.add_listener
def reset_agent_state(**_kwargs) -> None:
    _expected.clear()
    _seen.clear()
    _result_reported.clear()


@locust.events.test_stop.add_listener
def report_unfinished_jobs(**_kwargs) -> None:
    for job_id, match in _expected.items():
        if match.ready() and job_id not in _result_reported:
            job = match.value
            sample(
                f"agent-{job.terminal_index}",
                "agent_unfinished_job",
                job.started_at,
                participant_id=job.participant_id,
                error_code="job_result_not_reported",
            )


def run_agent(
    base_url: str, agent_token: str, terminal_index: int, ca: str | None
) -> None:
    alias = f"agent-{terminal_index}"
    base = base_url.rstrip("/")
    with requests.Session() as session:
        session.headers["Authorization"] = f"Agent {agent_token}"
        if ca:
            session.verify = ca

        next_heartbeat = 0.0
        while True:
            now = perf_counter()
            if now >= next_heartbeat:
                _heartbeat(session, base, alias)
                next_heartbeat = now + 10

            started = perf_counter()
            try:
                response = session.get(
                    f"{base}/api/agent/jobs/next",
                    params={"wait": 2},
                    timeout=(3, 6),
                )
            except requests.RequestException:
                sample(
                    alias,
                    "agent_pickup_api_ms",
                    started,
                    error_code="agent_poll_network",
                )
                gevent.sleep(1)
                continue

            if response.status_code == 204:
                continue
            if response.status_code != 200:
                sample(
                    alias, "agent_pickup_api_ms", started, error_code="agent_poll_http"
                )
                gevent.sleep(1)
                continue

            received_at = perf_counter()
            try:
                payload = response.json()
                job_id = payload["job_id"]
                copies = payload["copies"]
                if type(job_id) is not int or not _valid_copies(copies):
                    raise ValueError("invalid issue")
            except (ValueError, KeyError, TypeError):
                sample(
                    alias,
                    "agent_pickup_api_ms",
                    started,
                    error_code="agent_job_invalid",
                )
                continue

            _accept_job(session, base, terminal_index, job_id, received_at)


def _heartbeat(session: requests.Session, base: str, alias: str) -> None:
    started = perf_counter()
    error = ""
    try:
        response = session.post(
            f"{base}/api/agent/heartbeat",
            json={"printer_status": "ready"},
            timeout=(3, 6),
        )
        if response.status_code not in (200, 204):
            error = "agent_heartbeat_http"
    except requests.RequestException:
        error = "agent_heartbeat_network"
    if error:
        sample(alias, "agent_heartbeat_api_ms", started, error_code=error)


def _accept_job(
    session: requests.Session,
    base: str,
    terminal_index: int,
    job_id: int,
    received_at: float,
) -> None:
    alias = f"agent-{terminal_index}"
    if job_id in _seen:
        sample(
            alias, "agent_pickup_api_ms", received_at, error_code="agent_job_repeated"
        )
        return
    _seen.add(job_id)

    # Выдача может закончиться раньше HTTP-ответа confirm. Сохраняем момент выдачи.
    match = _expected.setdefault(job_id, AsyncResult())
    try:
        expected = match.get(timeout=10)
    except gevent.Timeout:
        sample(
            alias, "agent_pickup_api_ms", received_at, error_code="agent_job_unexpected"
        )
        return
    if expected.terminal_index != terminal_index:
        sample(
            alias,
            "agent_pickup_api_ms",
            received_at,
            participant_id=expected.participant_id,
            error_code="agent_wrong_printer",
        )
        return

    sample(
        alias,
        "agent_confirm_to_claim_api_ms",
        expected.started_at + (perf_counter() - received_at),
        participant_id=expected.participant_id,
    )
    started = perf_counter()
    error = ""
    try:
        response = session.post(
            f"{base}/api/agent/jobs/{job_id}/result", json={"ok": True}, timeout=(3, 6)
        )
        if response.status_code != 204:
            error = "agent_result_http"
    except requests.RequestException:
        error = "agent_result_network"
    _result_reported.add(job_id)
    sample(
        alias,
        "agent_result_api_ms",
        started,
        participant_id=expected.participant_id,
        error_code=error,
    )


def _valid_copies(copies: object) -> bool:
    return (
        isinstance(copies, list)
        and len(copies) in (1, 2)
        and all(
            isinstance(copy, dict)
            and isinstance(copy.get("png_base64"), str)
            and bool(copy["png_base64"])
            for copy in copies
        )
    )
