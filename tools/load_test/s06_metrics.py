"""Shared S-06 timing hooks for a single Locust process."""

import csv
import os
from pathlib import Path
from time import perf_counter

from gevent.event import Event
from locust import events

FIELDS = (
    "run_id",
    "scenario",
    "device_alias",
    "participant_id",
    "metric",
    "duration_ms",
    "status",
    "error_code",
    "limit_ms",
    "violation",
)
_starts: dict[int, float] = {}
_ready_panels: set[str] = set()
_panels_ready = Event()
_samples: list[tuple] = []


def mark_panel_ready(device_alias: str) -> None:
    _ready_panels.add(device_alias)
    if len(_ready_panels) == 2:
        _panels_ready.set()


def wait_for_panels(timeout: float = 10.0) -> bool:
    """Wait for one SSE snapshot from each panel before starting the terminal schedule."""
    return _panels_ready.wait(timeout=timeout)


def record_confirmation_started(participant_id: int, started_at: float) -> None:
    """Call immediately before a terminal confirm, with time.perf_counter()."""
    _starts.setdefault(participant_id, started_at)


def confirmation_started_at(participant_id: int) -> float | None:
    return _starts.get(participant_id)


def confirmation_starts() -> dict[int, float]:
    return _starts.copy()


def sample(
    device_alias: str,
    metric: str,
    started_at: float,
    *,
    participant_id: int | None = None,
    limit_ms: int | None = None,
    error_code: str = "",
) -> None:
    duration = (perf_counter() - started_at) * 1000
    _samples.append(
        (
            os.getenv("RS_LOAD_RUN_ID", ""),
            os.getenv("RS_LOAD_SCENARIO", ""),
            device_alias,
            participant_id,
            metric,
            round(duration, 3),
            "error" if error_code else "ok",
            error_code,
            limit_ms,
            int(limit_ms is not None and duration > limit_ms),
        )
    )
    events.request.fire(
        request_type="S06",
        name=metric,
        response_time=duration,
        response_length=0,
        exception=RuntimeError(error_code) if error_code else None,
    )


@events.test_start.add_listener
def reset_metrics(**_kwargs) -> None:
    _starts.clear()
    _ready_panels.clear()
    _panels_ready.clear()
    _samples.clear()


@events.quitting.add_listener
def write_samples(**_kwargs) -> None:
    if path := os.getenv("RS_LOAD_SAMPLES"):
        with Path(path).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(FIELDS)
            writer.writerows(_samples)
