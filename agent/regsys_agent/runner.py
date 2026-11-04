"""Главный цикл агента печати с обработкой сбоев и повторами."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import httpx

from regsys_agent.api import AuthError
from regsys_agent.worker import Worker

log = logging.getLogger(__name__)


def run(
    worker: Worker,
    wait_s: int,
    stop: threading.Event,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Главный цикл агента: опрос заданий до сигнала stop.

    При сбоях связи (httpx.HTTPError) выполняется пауза с ростом 1, 2, 4 ... до 30 с.
    После успешного круга пауза сбрасывается до 1 с.
    При неверном токене (AuthError) пишется сообщение об ошибке и пауза 60 с.
    При прочих ошибках пишется исключение в лог и пауза 5 с.
    """
    backoff_s = 1

    while not stop.is_set():
        try:
            worker.run_once(wait_s)
            backoff_s = 1
        except httpx.HTTPError as exc:
            log.warning(
                "Сетевая ошибка при обращении к серверу: %s. Пауза %s с перед повтором",
                exc,
                backoff_s,
            )
            sleep(backoff_s)
            backoff_s = min(backoff_s * 2, 30)
        except AuthError:
            log.error("Сервер не принял токен агента: выпустите новый в админке принтеров")
            sleep(60)
        except Exception:
            log.exception("Непредвиденная ошибка в основном цикле агента печати")
            sleep(5)
