"""Подписанный `scan_id` (B2-03): доказательство, что этот терминал только что отсканировал
именно этого участника.

Формат: `scan_<terminal_id>.<participant_id>.<выдан, unix-секунды>.<подпись>`, подпись —
HMAC-SHA256 от первых трёх полей на ключе из `settings.secret_key`. В БД ничего не хранится.
`confirm` и `report-error` принимают только свежий `scan_id` того же терминала и участника:
так нельзя зарегистрировать участника, которого не сканировали, перебирая `participant_id`.
Срок жизни — `idle_timeout_s + 30` с (экран подтверждения сам закроется по таймауту).
"""

import base64
import hashlib
import hmac
import time

_PREFIX = "scan_"
_LABEL = b"scan-id-v1:"  # отделяет эти подписи от любых других на том же ключе
_FUTURE_SKEW_S = 5  # допуск на расхождение часов между воркерами


def _sign(secret_key: str, payload: str) -> str:
    digest = hmac.new(
        secret_key.encode("utf-8"), _LABEL + payload.encode("ascii"), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issue_scan_id(
    secret_key: str, terminal_id: int, participant_id: int, now: float | None = None
) -> str:
    issued = int(time.time() if now is None else now)
    payload = f"{terminal_id}.{participant_id}.{issued}"
    return f"{_PREFIX}{payload}.{_sign(secret_key, payload)}"


def verify_scan_id(
    secret_key: str,
    scan_id: str,
    terminal_id: int,
    participant_id: int,
    ttl_s: int,
    now: float | None = None,
) -> bool:
    """Подпись верна, терминал и участник совпадают, срок не вышел."""
    if not scan_id.startswith(_PREFIX):
        return False
    payload, _, signature = scan_id.removeprefix(_PREFIX).rpartition(".")
    parts = payload.split(".")
    if len(parts) != 3 or not all(p.isascii() and p.isdigit() for p in parts):
        return False
    if not hmac.compare_digest(_sign(secret_key, payload), signature):
        return False
    scan_terminal, scan_participant, issued = (int(p) for p in parts)
    if (scan_terminal, scan_participant) != (terminal_id, participant_id):
        return False
    age = (time.time() if now is None else now) - issued
    return -_FUTURE_SKEW_S <= age <= ttl_s
