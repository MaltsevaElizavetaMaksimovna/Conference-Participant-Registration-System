"""HTTP-клиент взаимодействия агента печати с сервером регистрации."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Copy:
    """Параметры и изображение одной наклейки задания."""

    png: bytes
    width_mm: float
    height_mm: float
    gap_mm: float


@dataclass(frozen=True)
class Job:
    """Задание на печать наклеек."""

    job_id: int
    copies: list[Copy]
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    density: int = 10
    speed: int = 3


class AuthError(Exception):
    """Сервер не принял токен агента (401)."""

    def __init__(self, message: str = "Сервер не принял токен агента (401)") -> None:
        super().__init__(message)


class ServerClient:
    """Синхронный HTTP-клиент к REST API сервера регистрации."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_s: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout_s,
            headers={"Authorization": f"Agent {token}"},
        )

    def __repr__(self) -> str:
        return f"ServerClient(base_url={self._base_url!r}, timeout_s={self._timeout_s!r})"

    def next_job(self, wait_s: int) -> Job | None:
        """Получить следующее задание по long-poll.

        При 204 возвращает None. При сетевых ошибках и 5xx выбрасывает httpx.HTTPError.
        При 401 выбрасывает AuthError.
        """
        read_timeout = float(wait_s + self._timeout_s)
        timeout = httpx.Timeout(self._timeout_s, read=read_timeout)
        resp = self._client.get(
            f"{self._base_url}/api/agent/jobs/next",
            params={"wait": wait_s},
            timeout=timeout,
        )
        if resp.status_code == 401:
            raise AuthError()
        if resp.status_code == 204:
            return None

        resp.raise_for_status()

        data: dict[str, Any] = resp.json()
        copies_raw: list[dict[str, Any]] = data.get("copies", [])
        copies = [
            Copy(
                png=base64.b64decode(c["png_base64"]),
                width_mm=float(c["width_mm"]),
                height_mm=float(c["height_mm"]),
                gap_mm=float(c["gap_mm"]),
            )
            for c in copies_raw
        ]
        return Job(
            job_id=int(data["job_id"]),
            copies=copies,
            offset_x_mm=float(data.get("offset_x_mm", 0.0)),
            offset_y_mm=float(data.get("offset_y_mm", 0.0)),
            density=int(data.get("density", 10)),
            speed=int(data.get("speed", 3)),
        )

    def send_result(self, job_id: int, ok: bool, error: str | None) -> bool:
        """Отправить результат печати задания.

        Возвращает True, если сервер принял ответ или задание уже не ожидается (404/409).
        Возвращает False при сетевых сбоях и 5xx для повтора позже.
        При 401 выбрасывает AuthError.
        """
        try:
            resp = self._client.post(
                f"{self._base_url}/api/agent/jobs/{job_id}/result",
                json={"ok": ok, "error": error},
            )
        except httpx.HTTPError as exc:
            log.warning("Сетевая ошибка при отправке результата задания %s: %s", job_id, exc)
            return False

        if resp.status_code == 401:
            raise AuthError()
        if resp.status_code in (200, 204):
            return True
        if resp.status_code in (404, 409):
            log.warning(
                "Сервер вернул статус %s для задания %s: повторная отправка не требуется",
                resp.status_code,
                job_id,
            )
            return True
        if resp.status_code >= 500:
            log.warning(
                "Сервер вернул ошибку %s при отправке результата задания %s",
                resp.status_code,
                job_id,
            )
            return False

        log.warning(
            "Неожиданный статус %s при отправке результата задания %s",
            resp.status_code,
            job_id,
        )
        return False

    def heartbeat(self, printer_status: str) -> bool:
        """Отправить статус принтера (heartbeat).

        Возвращает True при успехе, False при ошибках сети или сервера.
        При 401 выбрасывает AuthError.
        """
        try:
            resp = self._client.post(
                f"{self._base_url}/api/agent/heartbeat",
                json={"printer_status": printer_status},
            )
        except httpx.HTTPError as exc:
            log.warning("Ошибка связи при отправке heartbeat: %s", exc)
            return False

        if resp.status_code == 401:
            raise AuthError()
        return resp.status_code in (200, 204)

    def close(self) -> None:
        """Закрыть HTTP-клиент."""
        self._client.close()

    def __enter__(self) -> ServerClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
