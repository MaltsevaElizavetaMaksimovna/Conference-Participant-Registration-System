"""Автотесты очереди печати и статусов заданий (B2-11, TR-04, TR-08, RG-08)."""

import base64
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.tokens import get_or_create_active_token
from app.core.config import Settings
from app.core.enums import PrintJobKind, PrintJobStatus
from app.models.conference import LabelTemplate
from app.models.participant import EventLog, Participant
from app.models.printing import PrintJob
from app.printing.queue import expire_stale
from app.printing.sweeper import PrintSweeper
from app.registration.messages import STICKER_FAILED, STICKER_PRINTING
from tests.conftest import Devices, LoginAs
from tests.registration_helpers import (
    auth,
    confirm,
    make_conference,
    make_participant,
    scan_and_get_id,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        env="test",
        database_url=database_url,
        public_base_url="https://reg.example.ru",
    )


def agent_auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Agent {token}"}


async def _make_template(
    db: AsyncSession,
    conference_id: int,
    name: str = "Лицевая",
    kind: str = "front",
    elements: list[dict[str, Any]] | None = None,
) -> LabelTemplate:
    tpl = LabelTemplate(
        conference_id=conference_id,
        name=name,
        kind=kind,
        width_mm=Decimal("60"),
        height_mm=Decimal("40"),
        gap_mm=Decimal("2"),
        elements=elements
        if elements is not None
        else [
            {
                "type": "field",
                "field": "last_name",
                "x_mm": 5,
                "y_mm": 5,
                "w_mm": 50,
                "h_mm": 10,
                "font_size": 14,
                "min_font_size": 8,
                "max_lines": 2,
            },
            {"type": "qr", "x_mm": 40, "y_mm": 20, "w_mm": 15, "h_mm": 15},
        ],
    )
    db.add(tpl)
    await db.commit()
    return tpl


# ------------------------------------------------------------------ Критерий 1


async def test_tr04_terminal_confirm_and_claim_job(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """TR-04: подтверждение на терминале -> задание печати, выдача агенту с калибровкой."""
    conf = await make_conference(db, badge_type="single")
    tpl = await _make_template(db, conf.id)
    conf.front_template_id = tpl.id
    await db.commit()

    await make_participant(db, conf, external_id="B24-1001")
    printer, agent_token = await devices.printer("Принтер 1", offset_x_mm=-1, density=12, speed=3)
    terminal, term_token = await devices.terminal("Терминал 1", printer=printer)

    pid, scan_id = await scan_and_get_id(anon, term_token, "B24-1001")
    r_conf = await confirm(anon, term_token, pid, scan_id)
    assert r_conf.status_code == 200, r_conf.text
    job_id = r_conf.json()["print_job_id"]
    assert job_id is not None

    # Агент запрашивает следующее задание
    r_job = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))
    assert r_job.status_code == 200, r_job.text
    data = r_job.json()
    assert data["job_id"] == job_id
    assert len(data["copies"]) == 1
    assert data["offset_x_mm"] == -1.0
    assert data["density"] == 12
    assert data["speed"] == 3
    png_bytes = base64.b64decode(data["copies"][0]["png_base64"])
    assert png_bytes.startswith(PNG_MAGIC)

    # Задание перешло в sent, попытка 1, sent_at задан
    job = await db.scalar(select(PrintJob).where(PrintJob.id == job_id))
    assert job is not None
    assert job.status == PrintJobStatus.SENT
    assert job.attempts == 1
    assert job.sent_at is not None

    # Повторный запрос — заданий больше нет
    r_again = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))
    assert r_again.status_code == 204


# ------------------------------------------------------------------ Критерий 2


async def test_double_sided_badge_has_two_copies(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """Двусторонний бейдж -> в задании 2 наклейки."""
    conf = await make_conference(db, badge_type="double")
    front_tpl = await _make_template(db, conf.id, name="Лицевой", kind="front")
    back_tpl = await _make_template(db, conf.id, name="Оборотный", kind="back")
    conf.front_template_id = front_tpl.id
    conf.back_template_id = back_tpl.id
    await db.commit()

    await make_participant(db, conf, external_id="B24-2001")
    printer, agent_token = await devices.printer("Принтер 2")
    terminal, term_token = await devices.terminal("Терминал 2", printer=printer)

    pid, scan_id = await scan_and_get_id(anon, term_token, "B24-2001")
    r_conf = await confirm(anon, term_token, pid, scan_id)
    assert r_conf.status_code == 200, r_conf.text
    job_id = r_conf.json()["print_job_id"]

    r_job = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))
    assert r_job.status_code == 200, r_job.text
    data = r_job.json()
    assert data["job_id"] == job_id
    assert len(data["copies"]) == 2
    for copy in data["copies"]:
        assert base64.b64decode(copy["png_base64"]).startswith(PNG_MAGIC)


# ------------------------------------------------------------------ Критерий 3


async def test_other_printer_agent_does_not_receive_job(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """Агент другого принтера задание не получает (204)."""
    conf = await make_conference(db, badge_type="single")
    tpl = await _make_template(db, conf.id)
    conf.front_template_id = tpl.id
    await db.commit()

    await make_participant(db, conf, external_id="B24-3001")
    printer1, agent_token1 = await devices.printer("Принтер 1")
    _, agent_token2 = await devices.printer("Принтер 2")
    terminal, term_token = await devices.terminal("Терминал 1", printer=printer1)

    pid, scan_id = await scan_and_get_id(anon, term_token, "B24-3001")
    await confirm(anon, term_token, pid, scan_id)

    # Агент принтера 2 не видит задание
    r2 = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token2))
    assert r2.status_code == 204

    # Агент принтера 1 забирает задание
    r1 = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token1))
    assert r1.status_code == 200


# ------------------------------------------------------------------ Критерий 4


async def test_job_result_ok_terminal_status_and_idempotency(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """Результат ok: true -> done, print_count=1, повтор ok: true -> 204, статус терминала."""
    conf = await make_conference(db, badge_type="single")
    tpl = await _make_template(db, conf.id)
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, external_id="B24-4001")
    printer, agent_token = await devices.printer("Принтер 1")
    terminal, term_token = await devices.terminal("Терминал 1", printer=printer)
    other_terminal, other_term_token = await devices.terminal("Терминал 2")

    pid, scan_id = await scan_and_get_id(anon, term_token, "B24-4001")
    r_conf = await confirm(anon, term_token, pid, scan_id)
    job_id = r_conf.json()["print_job_id"]

    await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))

    # Первый результат ok: true
    r_res = await anon.post(
        f"/api/agent/jobs/{job_id}/result",
        headers=agent_auth(agent_token),
        json={"ok": True},
    )
    assert r_res.status_code == 204

    job = await db.scalar(select(PrintJob).where(PrintJob.id == job_id))
    assert job is not None
    assert job.status == PrintJobStatus.DONE

    p_db = await db.scalar(select(Participant).where(Participant.id == p.id))
    assert p_db is not None
    assert p_db.print_count == 1
    assert p_db.sticker_not_printed is False

    ev = await db.scalar(
        select(EventLog).where(EventLog.participant_id == p.id, EventLog.type == "print_ok")
    )
    assert ev is not None

    # Повтор того же результата ничего не меняет
    r_res_replay = await anon.post(
        f"/api/agent/jobs/{job_id}/result",
        headers=agent_auth(agent_token),
        json={"ok": True},
    )
    assert r_res_replay.status_code == 204
    p_db_again = await db.scalar(select(Participant).where(Participant.id == p.id))
    assert p_db_again is not None
    assert p_db_again.print_count == 1

    # Запрос статуса своим терминалом
    r_own = await anon.get(f"/api/terminal/print-jobs/{job_id}", headers=auth(term_token))
    assert r_own.status_code == 200, r_own.text
    assert r_own.json() == {"status": "done", "message": STICKER_PRINTING}

    # Запрос статуса чужим терминалом -> 404
    r_other = await anon.get(f"/api/terminal/print-jobs/{job_id}", headers=auth(other_term_token))
    assert r_other.status_code == 404
    assert r_other.json()["code"] == "print_job_not_found"


# ------------------------------------------------------------------ Критерий 5


async def test_tr08_job_result_error_and_views(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices, login_as: LoginAs
) -> None:
    """TR-08: результат ok: false -> error, sticker_not_printed=True, текст на экране."""
    conf = await make_conference(db, badge_type="single")
    tpl = await _make_template(db, conf.id)
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, external_id="B24-5001")
    printer, agent_token = await devices.printer("Принтер 1")
    terminal, term_token = await devices.terminal("Терминал 1", printer=printer)

    pid, scan_id = await scan_and_get_id(anon, term_token, "B24-5001")
    r_conf = await confirm(anon, term_token, pid, scan_id)
    job_id = r_conf.json()["print_job_id"]

    await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))

    error_text = "Принтер выключен"
    r_res = await anon.post(
        f"/api/agent/jobs/{job_id}/result",
        headers=agent_auth(agent_token),
        json={"ok": False, "error": error_text},
    )
    assert r_res.status_code == 204

    # Задание и участник в БД
    job = await db.scalar(select(PrintJob).where(PrintJob.id == job_id))
    assert job is not None
    assert job.status == PrintJobStatus.ERROR
    assert job.error == error_text

    p_db = await db.scalar(select(Participant).where(Participant.id == p.id))
    assert p_db is not None
    assert p_db.status == "registered"
    assert p_db.sticker_not_printed is True

    ev = await db.scalar(
        select(EventLog).where(EventLog.participant_id == p.id, EventLog.type == "print_error")
    )
    assert ev is not None
    assert ev.payload["reason"] == error_text

    # Терминал видит STICKER_FAILED
    r_term = await anon.get(f"/api/terminal/print-jobs/{job_id}", headers=auth(term_token))
    assert r_term.status_code == 200
    assert r_term.json() == {"status": "error", "message": STICKER_FAILED}

    # Сотрудник видит статус и причину ошибки
    staff = await login_as()
    r_staff = await staff.get(f"/api/print-jobs/{job_id}")
    assert r_staff.status_code == 200
    assert r_staff.json() == {"id": job_id, "status": "error", "error": error_text}


# ------------------------------------------------------------------ Критерий 6


async def test_late_success_after_sent_timeout(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices, settings: Settings
) -> None:
    """Поздний успех: sent просрочен -> error timeout, затем ok: true -> done, print_count=1."""
    conf = await make_conference(db, badge_type="single")
    tpl = await _make_template(db, conf.id)
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, external_id="B24-6001")
    printer, agent_token = await devices.printer("Принтер 1")
    terminal, term_token = await devices.terminal("Терминал 1", printer=printer)

    pid, scan_id = await scan_and_get_id(anon, term_token, "B24-6001")
    r_conf = await confirm(anon, term_token, pid, scan_id)
    job_id = r_conf.json()["print_job_id"]

    await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))

    # Сдвигаем sent_at на 120 с назад
    await db.execute(
        update(PrintJob)
        .where(PrintJob.id == job_id)
        .values(sent_at=func.now() - timedelta(seconds=120))
    )
    await db.commit()

    expired_count = await expire_stale(db, settings)
    assert expired_count == 1

    job_timed_out = await db.scalar(select(PrintJob).where(PrintJob.id == job_id))
    assert job_timed_out is not None
    assert job_timed_out.status == PrintJobStatus.ERROR
    assert job_timed_out.error == "timeout"

    p_timeout = await db.scalar(select(Participant).where(Participant.id == p.id))
    assert p_timeout is not None
    assert p_timeout.sticker_not_printed is True

    # Агент позже присылает ok: true
    r_res = await anon.post(
        f"/api/agent/jobs/{job_id}/result",
        headers=agent_auth(agent_token),
        json={"ok": True},
    )
    assert r_res.status_code == 204

    job_done = await db.scalar(select(PrintJob).where(PrintJob.id == job_id))
    assert job_done is not None
    assert job_done.status == PrintJobStatus.DONE

    p_done = await db.scalar(select(Participant).where(Participant.id == p.id))
    assert p_done is not None
    assert p_done.sticker_not_printed is False
    assert p_done.print_count == 1


# ------------------------------------------------------------------ Критерий 7


async def test_pending_timeout_and_print_sweeper(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices, settings: Settings
) -> None:
    """Просрочка pending -> not_picked_up, не выдаётся агенту; проверка PrintSweeper."""
    conf = await make_conference(db, badge_type="single")
    tpl = await _make_template(db, conf.id)
    conf.front_template_id = tpl.id
    await db.commit()

    await make_participant(db, conf, external_id="B24-7001")
    printer, agent_token = await devices.printer("Принтер 1")
    terminal, term_token = await devices.terminal("Терминал 1", printer=printer)

    pid1, scan_id1 = await scan_and_get_id(anon, term_token, "B24-7001")
    r_conf1 = await confirm(anon, term_token, pid1, scan_id1)
    job1_id = r_conf1.json()["print_job_id"]

    # Сдвигаем created_at на 120 с назад
    await db.execute(
        update(PrintJob)
        .where(PrintJob.id == job1_id)
        .values(created_at=func.now() - timedelta(seconds=120))
    )
    await db.commit()

    expired = await expire_stale(db, settings)
    assert expired >= 1

    job1 = await db.scalar(select(PrintJob).where(PrintJob.id == job1_id))
    assert job1 is not None
    assert job1.status == PrintJobStatus.ERROR
    assert job1.error == "not_picked_up"

    # Агент опрашивает очередь — просроченное pending не выдаётся
    r_next = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))
    assert r_next.status_code == 204

    # Проверка через PrintSweeper.sweep_once()
    await make_participant(db, conf, external_id="B24-7002")
    pid2, scan_id2 = await scan_and_get_id(anon, term_token, "B24-7002")
    r_conf2 = await confirm(anon, term_token, pid2, scan_id2, key="key-2")
    job2_id = r_conf2.json()["print_job_id"]

    await db.execute(
        update(PrintJob)
        .where(PrintJob.id == job2_id)
        .values(created_at=func.now() - timedelta(seconds=120))
    )
    await db.commit()

    @asynccontextmanager
    async def dummy_sessionmaker():
        yield db

    sweeper = PrintSweeper(dummy_sessionmaker, settings)  # type: ignore[arg-type]
    swept = await sweeper.sweep_once()
    assert swept >= 1

    job2 = await db.scalar(select(PrintJob).where(PrintJob.id == job2_id))
    assert job2 is not None
    assert job2.status == PrintJobStatus.ERROR
    assert job2.error == "not_picked_up"


# ------------------------------------------------------------------ Критерий 8


async def test_result_errors_for_pending_other_printer_or_missing(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """Ответ на pending -> 409 print_job_not_sent; чужой принтер или несуществующее -> 404."""
    conf = await make_conference(db, badge_type="single")
    tpl = await _make_template(db, conf.id)
    conf.front_template_id = tpl.id
    await db.commit()

    await make_participant(db, conf, external_id="B24-8001")
    printer1, agent_token1 = await devices.printer("Принтер 1")
    _, agent_token2 = await devices.printer("Принтер 2")
    terminal, term_token = await devices.terminal("Терминал 1", printer=printer1)

    pid, scan_id = await scan_and_get_id(anon, term_token, "B24-8001")
    r_conf = await confirm(anon, term_token, pid, scan_id)
    job_id = r_conf.json()["print_job_id"]

    # 1. Задание ещё в pending -> 409
    r_pending = await anon.post(
        f"/api/agent/jobs/{job_id}/result",
        headers=agent_auth(agent_token1),
        json={"ok": True},
    )
    assert r_pending.status_code == 409
    assert r_pending.json()["code"] == "print_job_not_sent"

    # 2. Агент другого принтера отвечает на задание -> 404
    r_other = await anon.post(
        f"/api/agent/jobs/{job_id}/result",
        headers=agent_auth(agent_token2),
        json={"ok": True},
    )
    assert r_other.status_code == 404
    assert r_other.json()["code"] == "print_job_not_found"

    # 3. Несуществующее задание -> 404
    r_missing = await anon.post(
        "/api/agent/jobs/999999/result",
        headers=agent_auth(agent_token1),
        json={"ok": True},
    )
    assert r_missing.status_code == 404
    assert r_missing.json()["code"] == "print_job_not_found"


# ------------------------------------------------------------------ Критерий 9


async def test_missing_template_fails_and_claims_next_job(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """Нет шаблона -> error template_not_set, пометка участнику, агент забирает следующее."""
    printer, agent_token = await devices.printer("Принтер 1")

    # 1. Конференция без шаблона и неактивная (создаём задание напрямую)
    conf_bad = await make_conference(
        db, badge_type="single", active=False, title="Конференция без шаблона"
    )
    p_bad = await make_participant(db, conf_bad, external_id="BAD-01")
    token_bad = await get_or_create_active_token(db, p_bad.id)

    job_bad = PrintJob(
        conference_id=conf_bad.id,
        participant_id=p_bad.id,
        badge_token_id=token_bad.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        status=PrintJobStatus.PENDING,
        created_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    db.add(job_bad)
    await db.commit()

    # 2. Активная конференция с шаблоном
    conf_good = await make_conference(
        db, badge_type="single", active=True, title="Конференция с шаблоном"
    )
    tpl = await _make_template(db, conf_good.id)
    conf_good.front_template_id = tpl.id
    await db.commit()

    terminal, term_token = await devices.terminal("Терминал 1", printer=printer)
    await make_participant(db, conf_good, external_id="GOOD-01")
    pid_good, scan_id = await scan_and_get_id(anon, term_token, "GOOD-01")
    r_conf = await confirm(anon, term_token, pid_good, scan_id)
    job_good_id = r_conf.json()["print_job_id"]

    # Агент опрашивает очередь: первое задание падает с template_not_set, выдаётся второе
    r = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))
    assert r.status_code == 200, r.text
    assert r.json()["job_id"] == job_good_id

    # Первое задание помечено ошибкой template_not_set
    job_bad_db = await db.scalar(select(PrintJob).where(PrintJob.id == job_bad.id))
    assert job_bad_db is not None
    assert job_bad_db.status == PrintJobStatus.ERROR
    assert job_bad_db.error == "template_not_set"

    # Участнику p_bad выставлена пометка
    p_bad_db = await db.scalar(select(Participant).where(Participant.id == p_bad.id))
    assert p_bad_db is not None
    assert p_bad_db.sticker_not_printed is True


# ------------------------------------------------------------------ Критерий 10


async def test_test_print_outcome_does_not_affect_participant(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """Пробная печать kind=test -> ok: true не меняет print_count и флаг, нет print_ok."""
    conf = await make_conference(db, badge_type="single")
    tpl = await _make_template(db, conf.id)
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, external_id="TEST-01")
    printer, agent_token = await devices.printer("Принтер 1")

    test_job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.TEST,
        sides=1,
        template_id=tpl.id,
        status=PrintJobStatus.PENDING,
    )
    db.add(test_job)
    await db.commit()

    r_claim = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))
    assert r_claim.status_code == 200
    assert r_claim.json()["job_id"] == test_job.id

    r_res = await anon.post(
        f"/api/agent/jobs/{test_job.id}/result",
        headers=agent_auth(agent_token),
        json={"ok": True},
    )
    assert r_res.status_code == 204

    job_db = await db.scalar(select(PrintJob).where(PrintJob.id == test_job.id))
    assert job_db is not None
    assert job_db.status == PrintJobStatus.DONE

    p_db = await db.scalar(select(Participant).where(Participant.id == p.id))
    assert p_db is not None
    assert p_db.print_count == 0
    assert p_db.sticker_not_printed is False

    ev = await db.scalar(
        select(EventLog).where(EventLog.participant_id == p.id, EventLog.type == "print_ok")
    )
    assert ev is None


# ------------------------------------------------------------------ Критерий 11


async def test_older_job_is_claimed_first(
    anon: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """Порядок: из двух заданий принтера выдаётся более старое."""
    conf = await make_conference(db, badge_type="single")
    tpl = await _make_template(db, conf.id)
    conf.front_template_id = tpl.id
    await db.commit()

    p1 = await make_participant(db, conf, external_id="ORD-01")
    p2 = await make_participant(db, conf, external_id="ORD-02")
    t1 = await get_or_create_active_token(db, p1.id)
    t2 = await get_or_create_active_token(db, p2.id)

    printer, agent_token = await devices.printer("Принтер 1")

    job_older = PrintJob(
        conference_id=conf.id,
        participant_id=p1.id,
        badge_token_id=t1.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        status=PrintJobStatus.PENDING,
        created_at=datetime.now(UTC) - timedelta(seconds=20),
    )
    job_newer = PrintJob(
        conference_id=conf.id,
        participant_id=p2.id,
        badge_token_id=t2.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        status=PrintJobStatus.PENDING,
        created_at=datetime.now(UTC) - timedelta(seconds=5),
    )
    db.add_all([job_older, job_newer])
    await db.commit()

    r = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))
    assert r.status_code == 200
    assert r.json()["job_id"] == job_older.id


# ------------------------------------------------------------------ Критерий 12


async def test_long_poll_wait_without_jobs(anon: httpx.AsyncClient, devices: Devices) -> None:
    """Long-poll: jobs/next?wait=1 без заданий отвечает 204 не раньше чем через ~0.9 с."""
    _, agent_token = await devices.printer("Принтер 1")

    t0 = time.monotonic()
    r = await anon.get("/api/agent/jobs/next?wait=1", headers=agent_auth(agent_token))
    elapsed = time.monotonic() - t0

    assert r.status_code == 204
    assert elapsed >= 0.85


# ------------------------------------------------------------------ Критерий 13


async def test_staff_print_job_not_found_and_unauthorized(
    anon: httpx.AsyncClient, login_as: LoginAs
) -> None:
    """GET /api/print-jobs/999999 -> 404 print_job_not_found; без входа -> 401."""
    # Без входа
    r_anon = await anon.get("/api/print-jobs/999999")
    assert r_anon.status_code == 401
    assert r_anon.json()["code"] == "unauthenticated"

    # Вошедший сотрудник
    staff = await login_as()
    r_staff = await staff.get("/api/print-jobs/999999")
    assert r_staff.status_code == 404
    assert r_staff.json()["code"] == "print_job_not_found"
