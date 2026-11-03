"""Карточка участника и его фото: `GET /api/participants/{id}` (B1-12, RG-03)."""

from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conference import ExtraFieldDef
from app.models.participant import BadgeToken, EventLog
from tests.conftest import Devices, LoginAs
from tests.registration_helpers import make_conference, make_participant, utc

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF-test-photo"


@pytest.fixture
def photo_dir(app_db: FastAPI, tmp_path: Path) -> Path:
    """Каталог фото приложения: свой у каждого теста."""
    root = tmp_path / "photos"
    root.mkdir()
    app_db.state.settings = app_db.state.settings.model_copy(update={"photo_dir": root})
    return root


# 1. RG-03: статус «Зарегистрирован», время и номер терминала
async def test_registered_at_terminal_card(
    login_as: LoginAs, db: AsyncSession, devices: Devices
) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    terminal, _ = await devices.terminal("Терминал 2")
    reg_time = utc(2026, 11, 20, 9, 15)
    p = await make_participant(db, conf, registered_at=reg_time, status="registered")
    p.reg_source = "terminal"
    p.reg_terminal_id = terminal.id
    await db.commit()

    r = await c.get(f"/api/participants/{p.id}")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["status"] == "registered"
    assert card["registration"] is not None
    assert card["registration"]["source"] == "terminal"
    assert card["registration"]["terminal_name"] == "Терминал 2"
    assert datetime.fromisoformat(card["registration"]["at"]) == reg_time
    assert card["registration"]["user_login"] is None


# 2. RG-03: повторная попытка сканирования видна в событиях
async def test_rescan_attempt_visible_in_card(
    login_as: LoginAs, db: AsyncSession, devices: Devices
) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    terminal, _ = await devices.terminal("Терминал 2")
    reg_time = utc(2026, 11, 20, 9, 0)
    p = await make_participant(db, conf, registered_at=reg_time, status="registered")
    p.rescan_count = 1
    db.add(
        EventLog(
            conference_id=conf.id,
            participant_id=p.id,
            type="scan_rescan",
            terminal_id=terminal.id,
            created_at=utc(2026, 11, 20, 9, 30),
        )
    )
    await db.commit()

    r = await c.get(f"/api/participants/{p.id}")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["rescan_count"] == 1
    events = [e for e in card["events"] if e["type"] == "scan_rescan"]
    assert len(events) >= 1
    assert events[0]["terminal_name"] == "Терминал 2"


# 3. Незарегистрированный и зарегистрированный участник: can_register и подсказка
async def test_not_registered_and_registered_actions(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view", "registration.desk")
    conf = await make_conference(db)
    unreg = await make_participant(db, conf, "P-UNREG")
    reg = await make_participant(
        db,
        conf,
        "P-REG",
        registered_at=utc(2026, 11, 20, 9, 0),
        status="registered",
    )

    r_unreg = await c.get(f"/api/participants/{unreg.id}")
    assert r_unreg.status_code == 200, r_unreg.text
    card_unreg = r_unreg.json()
    assert card_unreg["status"] == "not_registered"
    assert card_unreg["registration"] is None
    assert card_unreg["actions"]["can_register"] is True

    r_reg = await c.get(f"/api/participants/{reg.id}")
    assert r_reg.status_code == 200, r_reg.text
    card_reg = r_reg.json()
    assert card_reg["actions"]["can_register"] is False
    assert "Уже зарегистрирован" in card_reg["actions"]["reasons"]["can_register"]


# 4. Регистрация со стойки: логин сотрудника и terminal_name is None
async def test_registration_from_desk_shows_user_login(login_as: LoginAs, db: AsyncSession) -> None:
    staff = await login_as("participants.view", "registration.desk")
    conf = await make_conference(db)
    reg_time = utc(2026, 11, 20, 9, 20)
    p = await make_participant(db, conf, registered_at=reg_time, status="registered")
    p.reg_source = "desk"
    p.reg_user_id = staff.user_id
    await db.commit()

    r = await staff.get(f"/api/participants/{p.id}")
    assert r.status_code == 200, r.text
    reg = r.json()["registration"]
    assert reg is not None
    assert reg["source"] == "desk"
    assert reg["user_login"] == staff.login
    assert reg["terminal_name"] is None


# 5. Данные и дополнительные поля участника
async def test_extra_fields_and_participant_details(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    db.add_all(
        [
            ExtraFieldDef(conference_id=conf.id, key="section", label="Секция", sort_order=0),
            ExtraFieldDef(conference_id=conf.id, key="hall", label="Зал", sort_order=1),
        ]
    )
    p = await make_participant(
        db,
        conf,
        external_id="B24-1001",
        last_name="Кузнецов",
        first_name="Алексей",
        middle_name="Михайлович",
        position="Инженер",
        organization="ООО Ромашка",
    )
    p.extra = {"section": "A"}
    await db.commit()

    r = await c.get(f"/api/participants/{p.id}")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["extra"] == [
        {"key": "section", "label": "Секция", "value": "A"},
        {"key": "hall", "label": "Зал", "value": None},
    ]
    assert card["last_name"] == "Кузнецов"
    assert card["first_name"] == "Алексей"
    assert card["middle_name"] == "Михайлович"
    assert card["position"] == "Инженер"
    assert card["organization"] == "ООО Ромашка"
    assert card["external_id"] == "B24-1001"


# 6. Пометки: порядок кодов и атрибуты at/by
async def test_flags_order_and_attributes(login_as: LoginAs, db: AsyncSession) -> None:
    staff = await login_as("participants.view")
    conf = await make_conference(db)
    p = await make_participant(db, conf)
    err_time = utc(2026, 11, 20, 8, 45)
    foreign_time = utc(2026, 11, 20, 9, 10)
    p.error_reported_at = err_time
    p.sticker_not_printed = True
    p.foreign_code_at = foreign_time
    p.foreign_code_by = staff.user_id
    await db.commit()

    r = await staff.get(f"/api/participants/{p.id}")
    assert r.status_code == 200, r.text
    flags = r.json()["flags"]
    assert [f["code"] for f in flags] == ["error_reported", "sticker_not_printed", "foreign_code"]
    err_flag = next(f for f in flags if f["code"] == "error_reported")
    assert datetime.fromisoformat(err_flag["at"]) == err_time
    foreign_flag = next(f for f in flags if f["code"] == "foreign_code")
    assert foreign_flag["by"] == staff.login


# 7. Фото: URL и отдача байтов, 404 без фото
async def test_photo_url_and_content_or_not_found(
    login_as: LoginAs, db: AsyncSession, photo_dir: Path
) -> None:
    (photo_dir / "5.jpg").write_bytes(JPEG)
    c = await login_as("participants.view")
    conf = await make_conference(db)
    p = await make_participant(db, conf)
    p.photo_path = "5.jpg"
    p_no_photo = await make_participant(db, conf, "B24-1002", last_name="Сидоров")
    await db.commit()

    r = await c.get(f"/api/participants/{p.id}")
    assert r.status_code == 200, r.text
    assert r.json()["photo_url"] == f"/api/participants/{p.id}/photo"

    photo_r = await c.get(f"/api/participants/{p.id}/photo")
    assert photo_r.status_code == 200, photo_r.text
    assert photo_r.headers["content-type"] == "image/jpeg"
    assert photo_r.content == JPEG

    r_no = await c.get(f"/api/participants/{p_no_photo.id}")
    assert r_no.status_code == 200, r_no.text
    assert r_no.json()["photo_url"] is None

    photo_no_r = await c.get(f"/api/participants/{p_no_photo.id}/photo")
    assert photo_no_r.status_code == 404, photo_no_r.text
    assert photo_no_r.json()["code"] == "photo_not_found"


# 8. Профиль: ссылка по активному коду бейджа
async def test_public_profile_url_with_active_token(
    login_as: LoginAs, db: AsyncSession, app_db: FastAPI
) -> None:
    app_db.state.settings = app_db.state.settings.model_copy(
        update={"public_base_url": "https://reg.example.ru"}
    )
    c = await login_as("participants.view")
    conf = await make_conference(db)
    p_token = await make_participant(db, conf, "P-TOKEN")
    db.add(BadgeToken(participant_id=p_token.id, token="Zk3x9QnS7Vb2LmT4", status="active"))
    p_no_token = await make_participant(db, conf, "P-NO-TOKEN")
    await db.commit()

    r = await c.get(f"/api/participants/{p_token.id}")
    assert r.status_code == 200, r.text
    assert r.json()["profile_url"] == "https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4"

    r_no = await c.get(f"/api/participants/{p_no_token.id}")
    assert r_no.status_code == 200, r_no.text
    assert r_no.json()["profile_url"] is None


# 9. Счётчик печати: берётся из участника
async def test_print_count_from_participant(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    p = await make_participant(db, conf)
    p.print_count = 2
    await db.commit()

    r = await c.get(f"/api/participants/{p.id}")
    assert r.status_code == 200, r.text
    assert r.json()["print_count"] == 2


# 10. 404 participant_not_found: несуществующий id и неактивная конференция
async def test_participant_not_found_or_inactive_conference(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view")
    r = await c.get("/api/participants/999999")
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "participant_not_found"

    old_conf = await make_conference(db, active=False, title="Прошлая")
    p_old = await make_participant(db, old_conf, "OLD-1")
    r_old = await c.get(f"/api/participants/{p_old.id}")
    assert r_old.status_code == 404, r_old.text
    assert r_old.json()["code"] == "participant_not_found"


# 11. Без права participants.view: 403 forbidden
async def test_participant_card_forbidden_without_permission(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("users.manage")
    conf = await make_conference(db)
    p = await make_participant(db, conf)

    r = await c.get(f"/api/participants/{p.id}")
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "forbidden"
