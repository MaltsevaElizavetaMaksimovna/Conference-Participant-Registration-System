"""Автотесты отметки «Зарегистрирован по чужому коду» (B2-14, QR-03)."""

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.tokens import new_badge_token
from app.core.enums import (
    BadgeTokenStatus,
    BadgeType,
    EventType,
    PrintJobKind,
)
from app.models.conference import Conference
from app.models.device import Printer
from app.models.participant import BadgeToken, EventLog, Participant
from app.models.printing import PrintJob
from tests.conftest import Devices, LoginAs, StaffClient
from tests.registration_helpers import (
    confirm,
    make_conference,
    make_participant,
    scan_and_get_id,
)


async def _make_staff_with_printer(
    login_as: LoginAs,
    devices: Devices,
    *extra_permissions: str,
) -> tuple[StaffClient, Printer]:
    """Сотрудник с правами регистрации по чужому коду и выбранным принтером в панели."""
    perms = (
        "registration.foreign_code",
        "participants.view",
        "stickers.print",
        *extra_permissions,
    )
    client = await login_as(*perms)
    panel_printer, _ = await devices.printer("Принтер стойки")
    r = await client.put("/api/auth/me/printer", json={"printer_id": panel_printer.id})
    assert r.status_code == 200, r.text
    return client, panel_printer


async def _register_via_terminal(
    anon: httpx.AsyncClient,
    db: AsyncSession,
    devices: Devices,
    conf: Conference,
    external_id: str = "B24-1001",
    **fields: Any,
) -> tuple[Participant, BadgeToken, Printer]:
    """Регистрация участника через терминал с созданием действующего кода бейджа."""
    printer, _ = await devices.printer()
    _, term_token = await devices.terminal(printer=printer)
    await make_participant(db, conf, external_id=external_id, **fields)
    pid, scan_id = await scan_and_get_id(anon, term_token, external_id)
    r = await confirm(anon, term_token, pid, scan_id)
    assert r.status_code == 200, r.text
    token = await db.scalar(
        select(BadgeToken).where(
            BadgeToken.participant_id == pid,
            BadgeToken.status == BadgeTokenStatus.ACTIVE,
        )
    )
    assert token is not None
    p_fresh = await db.scalar(select(Participant).where(Participant.id == pid))
    assert p_fresh is not None
    return p_fresh, token, printer


# ------------------------------------------------------------------ Критерий 1


async def test_foreign_code_button_success(
    anon: httpx.AsyncClient,
    db: AsyncSession,
    devices: Devices,
    login_as: LoginAs,
) -> None:
    """QR-03 «нажать кнопку»: отметка по чужому коду, задание печати на принтер панели."""
    conf = await make_conference(db, badge_type="single")
    staff_client, panel_printer = await _make_staff_with_printer(login_as, devices)
    p_initial, old_token, _ = await _register_via_terminal(anon, db, devices, conf, "B24-1001")

    initial_status = p_initial.status
    initial_registered_at = p_initial.registered_at
    initial_reg_source = p_initial.reg_source
    initial_reg_terminal_id = p_initial.reg_terminal_id
    assert initial_reg_terminal_id is not None

    r = await staff_client.post(f"/api/participants/{p_initial.id}/foreign-code")
    assert r.status_code == 200, r.text
    data = r.json()
    job_id = data["print_job_id"]
    assert isinstance(job_id, int)

    # Задание печати на принтер панели сотрудника с новым токеном
    job = await db.scalar(select(PrintJob).where(PrintJob.id == job_id))
    assert job is not None
    assert job.kind == PrintJobKind.FOREIGN
    assert job.printer_id == panel_printer.id
    assert job.created_by_user_id == staff_client.user_id
    assert job.sides == 1
    assert job.badge_token_id is not None

    new_token = await db.scalar(select(BadgeToken).where(BadgeToken.id == job.badge_token_id))
    assert new_token is not None
    assert new_token.status == BadgeTokenStatus.ACTIVE
    assert new_token.id != old_token.id

    # Данные участника: пометка чужого кода, остальные поля регистрации не изменились
    p_fresh = await db.scalar(select(Participant).where(Participant.id == p_initial.id))
    assert p_fresh is not None
    assert p_fresh.foreign_code_at is not None
    assert p_fresh.foreign_code_by == staff_client.user_id
    assert p_fresh.status == initial_status
    assert p_fresh.registered_at == initial_registered_at
    assert p_fresh.reg_source == initial_reg_source
    assert p_fresh.reg_terminal_id == initial_reg_terminal_id

    # Событие в журнале с user_id и принтером панели
    ev = await db.scalar(
        select(EventLog).where(
            EventLog.participant_id == p_initial.id,
            EventLog.type == EventType.FOREIGN_CODE,
        )
    )
    assert ev is not None
    assert ev.user_id == staff_client.user_id
    assert ev.conference_id == conf.id
    assert ev.payload == {"printer_id": panel_printer.id}

    # Карточка GET /api/participants/{id} содержит пометку foreign_code во flags
    r_card = await staff_client.get(f"/api/participants/{p_initial.id}")
    assert r_card.status_code == 200, r_card.text
    flags = r_card.json()["flags"]
    foreign_flag = next((f for f in flags if f["code"] == "foreign_code"), None)
    assert foreign_flag is not None
    assert foreign_flag["by"] == staff_client.login
    assert foreign_flag["at"] is not None


# ------------------------------------------------------------------ Критерий 2


async def test_foreign_code_tokens_and_profile_status(
    anon: httpx.AsyncClient,
    db: AsyncSession,
    devices: Devices,
    login_as: LoginAs,
) -> None:
    """QR-03 «старая ссылка» отозвана, «новая ссылка» активна, ровно один действующий токен."""
    conf = await make_conference(db, badge_type="single")
    staff_client, _ = await _make_staff_with_printer(login_as, devices)
    p_initial, old_token, _ = await _register_via_terminal(
        anon,
        db,
        devices,
        conf,
        "B24-1002",
        last_name="Сидоров",
        first_name="Алексей",
        middle_name="Петрович",
    )

    r = await staff_client.post(f"/api/participants/{p_initial.id}/foreign-code")
    assert r.status_code == 200, r.text
    job_id = r.json()["print_job_id"]
    job = await db.scalar(select(PrintJob).where(PrintJob.id == job_id))
    assert job is not None

    new_token = await db.scalar(select(BadgeToken).where(BadgeToken.id == job.badge_token_id))
    assert new_token is not None

    # Новый токен отличается от старого
    assert new_token.token != old_token.token

    # У участника ровно один действующий код
    tokens = list(
        (
            await db.scalars(select(BadgeToken).where(BadgeToken.participant_id == p_initial.id))
        ).all()
    )
    active_tokens = [t for t in tokens if t.status == BadgeTokenStatus.ACTIVE]
    assert len(active_tokens) == 1
    assert active_tokens[0].token == new_token.token

    # Старый код отозван навсегда (revoked_at, revoked_by = id сотрудника)
    old_in_db = await db.scalar(select(BadgeToken).where(BadgeToken.id == old_token.id))
    assert old_in_db is not None
    assert old_in_db.status == BadgeTokenStatus.REVOKED
    assert old_in_db.revoked_at is not None
    assert old_in_db.revoked_by == staff_client.user_id

    # Публичный профиль: старая ссылка -> revoked, новая ссылка -> active
    r_old = await anon.get(f"/api/public/profile/{old_token.token}")
    assert r_old.status_code == 200, r_old.text
    assert r_old.json() == {"status": "revoked"}

    r_new = await anon.get(f"/api/public/profile/{new_token.token}")
    assert r_new.status_code == 200, r_new.text
    data_new = r_new.json()
    assert data_new["status"] == "active"
    assert data_new["full_name"] == "Сидоров Алексей Петрович"


# ------------------------------------------------------------------ Критерий 3


async def test_foreign_code_repeat_revokes_previous(
    anon: httpx.AsyncClient,
    db: AsyncSession,
    devices: Devices,
    login_as: LoginAs,
) -> None:
    """Повторное нажатие: третий код, второй отозван, отозванные никогда не станут активными."""
    conf = await make_conference(db, badge_type="single")
    staff_client, _ = await _make_staff_with_printer(login_as, devices)
    p_initial, token1, _ = await _register_via_terminal(anon, db, devices, conf, "B24-1003")

    # Первое нажатие
    r1 = await staff_client.post(f"/api/participants/{p_initial.id}/foreign-code")
    assert r1.status_code == 200, r1.text
    job1_id = r1.json()["print_job_id"]
    job1 = await db.scalar(select(PrintJob).where(PrintJob.id == job1_id))
    assert job1 is not None
    token2 = await db.scalar(select(BadgeToken).where(BadgeToken.id == job1.badge_token_id))
    assert token2 is not None

    # Второе (повторное) нажатие
    r2 = await staff_client.post(f"/api/participants/{p_initial.id}/foreign-code")
    assert r2.status_code == 200, r2.text
    job2_id = r2.json()["print_job_id"]
    job2 = await db.scalar(select(PrintJob).where(PrintJob.id == job2_id))
    assert job2 is not None
    token3 = await db.scalar(select(BadgeToken).where(BadgeToken.id == job2.badge_token_id))
    assert token3 is not None

    # Все три токена разные
    assert len({token1.token, token2.token, token3.token}) == 3

    # Токен 3 активен, токены 1 и 2 отозваны
    assert token3.status == BadgeTokenStatus.ACTIVE

    t1_db = await db.scalar(select(BadgeToken).where(BadgeToken.id == token1.id))
    assert t1_db is not None and t1_db.status == BadgeTokenStatus.REVOKED
    assert t1_db.revoked_by == staff_client.user_id

    t2_db = await db.scalar(select(BadgeToken).where(BadgeToken.id == token2.id))
    assert t2_db is not None and t2_db.status == BadgeTokenStatus.REVOKED
    assert t2_db.revoked_by == staff_client.user_id

    # Ровно один действующий код
    tokens = list(
        (
            await db.scalars(select(BadgeToken).where(BadgeToken.participant_id == p_initial.id))
        ).all()
    )
    active_tokens = [t for t in tokens if t.status == BadgeTokenStatus.ACTIVE]
    assert len(active_tokens) == 1
    assert active_tokens[0].id == token3.id

    # Отозванные коды никогда не становятся действующими
    assert (await anon.get(f"/api/public/profile/{token1.token}")).json() == {"status": "revoked"}
    assert (await anon.get(f"/api/public/profile/{token2.token}")).json() == {"status": "revoked"}
    assert (await anon.get(f"/api/public/profile/{token3.token}")).json()["status"] == "active"


# ------------------------------------------------------------------ Критерий 4


async def test_foreign_code_unregistered_participant_conflict(
    db: AsyncSession,
    devices: Devices,
    login_as: LoginAs,
) -> None:
    """Незарегистрированный участник: 409 participant_not_registered, ничего не изменено."""
    conf = await make_conference(db, badge_type="single")
    staff_client, _ = await _make_staff_with_printer(login_as, devices)

    p = await make_participant(db, conf, external_id="B24-1004")
    token = BadgeToken(
        participant_id=p.id,
        token=new_badge_token(),
        status=BadgeTokenStatus.ACTIVE,
    )
    db.add(token)
    await db.commit()

    r = await staff_client.post(f"/api/participants/{p.id}/foreign-code")
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "participant_not_registered"

    # Код не отозван
    token_db = await db.scalar(select(BadgeToken).where(BadgeToken.id == token.id))
    assert token_db is not None
    assert token_db.status == BadgeTokenStatus.ACTIVE
    assert token_db.revoked_at is None

    # Заданий печати нет
    jobs = list((await db.scalars(select(PrintJob).where(PrintJob.participant_id == p.id))).all())
    assert len(jobs) == 0

    # Пометки нет
    p_db = await db.scalar(select(Participant).where(Participant.id == p.id))
    assert p_db is not None
    assert p_db.foreign_code_at is None
    assert p_db.foreign_code_by is None


# ------------------------------------------------------------------ Критерий 5


async def test_foreign_code_printer_not_selected_conflict(
    anon: httpx.AsyncClient,
    db: AsyncSession,
    devices: Devices,
    login_as: LoginAs,
) -> None:
    """В панели сотрудника не выбран принтер: 409 printer_not_selected, ничего не изменено."""
    conf = await make_conference(db, badge_type="single")
    # Сотрудник без выбранного принтера панели
    staff_client = await login_as("registration.foreign_code", "participants.view")
    p, token, _ = await _register_via_terminal(anon, db, devices, conf, "B24-1005")

    r = await staff_client.post(f"/api/participants/{p.id}/foreign-code")
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "printer_not_selected"

    # Код не отозван
    token_db = await db.scalar(select(BadgeToken).where(BadgeToken.id == token.id))
    assert token_db is not None
    assert token_db.status == BadgeTokenStatus.ACTIVE
    assert token_db.revoked_at is None

    # Пометки чужого кода нет
    p_db = await db.scalar(select(Participant).where(Participant.id == p.id))
    assert p_db is not None
    assert p_db.foreign_code_at is None
    assert p_db.foreign_code_by is None

    # Задания печати foreign нет
    foreign_jobs = list(
        (
            await db.scalars(
                select(PrintJob).where(
                    PrintJob.participant_id == p.id,
                    PrintJob.kind == PrintJobKind.FOREIGN,
                )
            )
        ).all()
    )
    assert len(foreign_jobs) == 0


# ------------------------------------------------------------------ Критерий 6


async def test_foreign_code_permissions(
    anon: httpx.AsyncClient,
    db: AsyncSession,
    login_as: LoginAs,
) -> None:
    """QR-03 «роль без разрешения»: 403 при нехватке прав, 401 без авторизации."""
    conf = await make_conference(db, badge_type="single")
    p = await make_participant(
        db,
        conf,
        external_id="B24-1006",
        registered_at=datetime.now(UTC),
        status="registered",
    )

    # Сотрудник без права registration.foreign_code
    viewer = await login_as("participants.view")
    r_forbidden = await viewer.post(f"/api/participants/{p.id}/foreign-code")
    assert r_forbidden.status_code == 403, r_forbidden.text
    assert r_forbidden.json()["code"] == "forbidden"

    # Запрос без входа
    r_unauth = await anon.post(f"/api/participants/{p.id}/foreign-code")
    assert r_unauth.status_code == 401, r_unauth.text
    assert r_unauth.json()["code"] == "unauthenticated"


# ------------------------------------------------------------------ Критерий 7


async def test_foreign_code_inactive_conference_or_not_found(
    db: AsyncSession,
    devices: Devices,
    login_as: LoginAs,
) -> None:
    """Участник неактивной конференции или несуществующий: 404 participant_not_found."""
    conf_inactive = await make_conference(db, active=False, title="Неактивная")
    staff_client, _ = await _make_staff_with_printer(login_as, devices)

    p_inactive = await make_participant(
        db,
        conf_inactive,
        external_id="B24-1007",
        registered_at=datetime.now(UTC),
        status="registered",
    )

    # Участник неактивной конференции
    r_inactive = await staff_client.post(f"/api/participants/{p_inactive.id}/foreign-code")
    assert r_inactive.status_code == 404, r_inactive.text
    assert r_inactive.json()["code"] == "participant_not_found"

    # Несуществующий id
    r_missing = await staff_client.post("/api/participants/999999/foreign-code")
    assert r_missing.status_code == 404, r_missing.text
    assert r_missing.json()["code"] == "participant_not_found"


# ------------------------------------------------------------------ Критерий 8


async def test_foreign_code_double_sided_badge(
    anon: httpx.AsyncClient,
    db: AsyncSession,
    devices: Devices,
    login_as: LoginAs,
) -> None:
    """Двусторонняя конференция: задание печати создаётся с sides == 2."""
    conf = await make_conference(db, badge_type="double")
    staff_client, panel_printer = await _make_staff_with_printer(login_as, devices)
    p, _, _ = await _register_via_terminal(anon, db, devices, conf, "B24-1008")

    r = await staff_client.post(f"/api/participants/{p.id}/foreign-code")
    assert r.status_code == 200, r.text
    job_id = r.json()["print_job_id"]

    job = await db.scalar(select(PrintJob).where(PrintJob.id == job_id))
    assert job is not None
    assert job.kind == PrintJobKind.FOREIGN
    assert job.sides == 2
    assert job.printer_id == panel_printer.id


# ------------------------------------------------------------------ Критерий 9


async def test_foreign_code_no_badge_conference_conflict(
    db: AsyncSession,
    devices: Devices,
    login_as: LoginAs,
) -> None:
    """Конференция без бейджа: 409 no_badge, код не отозван, пометки нет."""
    conf = await make_conference(db, badge_type=BadgeType.NONE)
    staff_client, _ = await _make_staff_with_printer(login_as, devices)

    p = await make_participant(
        db,
        conf,
        external_id="B24-1009",
        registered_at=datetime.now(UTC),
        status="registered_no_sticker",
    )
    token = BadgeToken(
        participant_id=p.id,
        token=new_badge_token(),
        status=BadgeTokenStatus.ACTIVE,
    )
    db.add(token)
    await db.commit()

    r = await staff_client.post(f"/api/participants/{p.id}/foreign-code")
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "no_badge"

    # Код не отозван
    token_db = await db.scalar(select(BadgeToken).where(BadgeToken.id == token.id))
    assert token_db is not None
    assert token_db.status == BadgeTokenStatus.ACTIVE
    assert token_db.revoked_at is None

    # Пометки нет
    p_db = await db.scalar(select(Participant).where(Participant.id == p.id))
    assert p_db is not None
    assert p_db.foreign_code_at is None
    assert p_db.foreign_code_by is None

    # Заданий печати нет
    jobs = list((await db.scalars(select(PrintJob).where(PrintJob.participant_id == p.id))).all())
    assert len(jobs) == 0
