"""Two registrar panels with independent sessions and persistent SSE streams."""

import json
import os
from itertools import cycle
from time import perf_counter

import gevent
import requests
from locust import HttpUser, between, task
from locust.exception import StopUser
from s06_metrics import (
    confirmation_started_at,
    confirmation_starts,
    mark_panel_ready,
    sample,
)

SEARCHES = ("Иванов", "Пётр", "Федоров", "Козлов", "Смирнова")


class Panel(HttpUser):
    abstract = True
    wait_time = between(0.8, 1.5)
    number: int

    def on_start(self) -> None:
        self.alias = f"panel-{self.number}"
        self.searches = cycle(SEARCHES)
        self.seen: set[int] = set()
        self.subscribed_at = 0.0
        self.stream = None
        ca = os.getenv("RS_LOAD_CA")
        if ca:
            self.client.verify = ca
        login = os.environ[f"RS_LOAD_PANEL_{self.number}_LOGIN"]
        password = os.environ[f"RS_LOAD_PANEL_{self.number}_PASSWORD"]
        with self.client.post(
            "/api/auth/login",
            json={"login": login, "password": password},
            timeout=10,
            catch_response=True,
        ) as response:
            if response.status_code != 200 or "rs_session" not in self.client.cookies:
                response.failure("panel_login_failed")
                raise StopUser()
        self.stream = gevent.spawn(self.read_events)

    def on_stop(self) -> None:
        if self.stream is None:
            return
        self.stream.kill()
        if not self.subscribed_at:
            return
        now = perf_counter()
        for participant_id, started in confirmation_starts().items():
            if (
                self.subscribed_at <= started <= now - 5
                and participant_id not in self.seen
            ):
                sample(
                    self.alias,
                    "panel_sse_update_ms",
                    started,
                    participant_id=participant_id,
                    limit_ms=5000,
                    error_code="sse_update_missing",
                )

    @task
    def search(self) -> None:
        started = perf_counter()
        with self.client.get(
            "/api/participants",
            params={"q": next(self.searches), "limit": 20},
            name="/api/participants [search]",
            timeout=10,
            catch_response=True,
        ) as response:
            code = self.check_json(response, "items", list)
            sample(
                self.alias,
                "panel_search_api_ms",
                started,
                limit_ms=1000,
                error_code=code,
            )

    @task
    def counter(self) -> None:
        with self.client.get(
            "/api/participants/stats", timeout=10, catch_response=True
        ) as response:
            self.check_json(response, "registered", int)

    @staticmethod
    def check_json(response, key, expected_type) -> str:
        if response.status_code != 200:
            code = "panel_http_error"
        else:
            try:
                valid = isinstance(response.json().get(key), expected_type)
            except (ValueError, AttributeError):
                valid = False
            code = "" if valid else "panel_invalid_response"
        if code:
            response.failure(code)
        return code

    def read_events(self) -> None:
        with requests.Session() as session:
            session.cookies.update(self.client.cookies)
            session.verify = self.client.verify
            while True:
                started = perf_counter()
                try:
                    with session.get(
                        f"{self.host.rstrip('/')}/api/events/stream",
                        headers={"Accept": "text/event-stream"},
                        stream=True,
                        timeout=(5, 25),
                    ) as response:
                        response.raise_for_status()
                        if not response.headers.get("content-type", "").startswith(
                            "text/event-stream"
                        ):
                            raise ValueError("unexpected media type")
                        self.consume(response, started)
                except (requests.RequestException, ValueError, KeyError, TypeError):
                    sample(
                        self.alias,
                        "panel_sse_connection",
                        started,
                        error_code="sse_disconnected",
                    )
                gevent.sleep(1)

    def consume(self, response, started: float) -> None:
        event = ""
        first_snapshot = True
        for line in response.iter_lines(chunk_size=1, decode_unicode=True):
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: ") and event:
                data = json.loads(line.removeprefix("data: "))
                if event == "stats" and first_snapshot:
                    if not all(
                        isinstance(data[key], int) for key in ("registered", "total")
                    ):
                        raise ValueError("invalid snapshot")
                    if not self.subscribed_at:
                        self.subscribed_at = perf_counter()
                    sample(self.alias, "panel_sse_snapshot_ms", started, limit_ms=5000)
                    first_snapshot = False
                    mark_panel_ready(self.alias)
                elif event == "participant_updated":
                    participant_id = int(data["id"])
                    confirmed = confirmation_started_at(participant_id)
                    registered = data["status"] in {
                        "registered",
                        "registered_no_sticker",
                    }
                    if (
                        registered
                        and confirmed is not None
                        and participant_id not in self.seen
                    ):
                        self.seen.add(participant_id)
                        sample(
                            self.alias,
                            "panel_sse_update_ms",
                            confirmed,
                            participant_id=participant_id,
                            limit_ms=5000,
                        )
                event = ""
        raise ValueError("unexpected EOF")


class PanelOne(Panel):
    fixed_count = 1
    number = 1


class PanelTwo(Panel):
    fixed_count = 1
    number = 2
