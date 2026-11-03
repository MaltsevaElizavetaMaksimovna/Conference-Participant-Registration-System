"""Правка данных участника: `PATCH /api/participants/{id}` (B1-12, RG-06, ER-02, ER-03)."""

from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.participant import EventLog, Participant
from tests.conftest import LoginAs
from tests.registration_helpers import make_conference, make_participant, utc


# 1. RG-06: исправить фамилию -> пометка data_changed, логин сотрудника, поиск обновлён
async def test_edit_last_name_and_data_changed_flag_and_search(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1001", last_name="Ивнов", first_name="Пётр")

    r = await c.patch(f"/api/participants/{p.id}", json={"last_name": "Иванов"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["last_name"] == "Иванов"
    flags = card["flags"]
    assert "data_changed" in [f["code"] for f in flags]
    flag = next(f for f in flags if f["code"] == "data_changed")
    assert flag["by"] == c.login

    search_r = await c.get("/api/participants", params={"q": "иванов"})
    assert search_r.status_code == 200, search_r.text
    found_ids = [item["id"] for item in search_r.json()["items"]]
    assert p.id in found_ids


# 2. RG-06: стереть фамилию или имя -> 422, подсказки, данные в БД не изменились
async def test_blank_last_name_and_first_name_validation(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1002", last_name="Сидоров", first_name="Алексей")

    r_spaces_last = await c.patch(f"/api/participants/{p.id}", json={"last_name": "   "})
    assert r_spaces_last.status_code == 422, r_spaces_last.text
    assert r_spaces_last.json()["code"] == "validation_error"
    assert r_spaces_last.json()["details"]["fields"]["last_name"] == "Укажите фамилию"

    r_null_last = await c.patch(f"/api/participants/{p.id}", json={"last_name": None})
    assert r_null_last.status_code == 422, r_null_last.text
    assert r_null_last.json()["code"] == "validation_error"
    assert r_null_last.json()["details"]["fields"]["last_name"] == "Укажите фамилию"

    r_spaces_first = await c.patch(f"/api/participants/{p.id}", json={"first_name": "   "})
    assert r_spaces_first.status_code == 422, r_spaces_first.text
    assert r_spaces_first.json()["code"] == "validation_error"
    assert r_spaces_first.json()["details"]["fields"]["first_name"] == "Укажите имя"

    r_null_first = await c.patch(f"/api/participants/{p.id}", json={"first_name": None})
    assert r_null_first.status_code == 422, r_null_first.text
    assert r_null_first.json()["code"] == "validation_error"
    assert r_null_first.json()["details"]["fields"]["first_name"] == "Укажите имя"

    p_db = await db.scalar(
        select(Participant).where(Participant.id == p.id).execution_options(populate_existing=True)
    )
    assert p_db is not None
    assert p_db.last_name == "Сидоров"
    assert p_db.first_name == "Алексей"


# 3. Пробелы = пусто, лишние пробелы обрезаются
async def test_spaces_become_none_and_strip_position(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1003", organization="ООО Ромашка", position=None)

    r = await c.patch(
        f"/api/participants/{p.id}",
        json={"organization": "   ", "position": "  Инженер  "},
    )
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["organization"] is None
    assert card["position"] == "Инженер"


# 4. ER-03: исправление организации записывается в историю изменений
async def test_edit_organization_creates_history_record(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1004", organization="Ромашка")

    r = await c.patch(f"/api/participants/{p.id}", json={"organization": "ООО Ромашка"})
    assert r.status_code == 200, r.text
    history = r.json()["history"]
    assert len(history) == 1
    item = history[0]
    assert item["field"] == "organization"
    assert item["old"] == "Ромашка"
    assert item["new"] == "ООО Ромашка"
    assert item["source"] == "manual"
    assert item["user_login"] == c.login
    assert bool(item["at"])


# 5. ER-03: повторное исправление того же поля добавляет вторую запись в историю
async def test_edit_same_field_twice_creates_two_history_records(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1005", organization="Первая")

    r1 = await c.patch(f"/api/participants/{p.id}", json={"organization": "Вторая"})
    assert r1.status_code == 200, r1.text

    r2 = await c.patch(f"/api/participants/{p.id}", json={"organization": "Третья"})
    assert r2.status_code == 200, r2.text
    history = r2.json()["history"]
    assert len(history) == 2
    assert history[0]["field"] == "organization"
    assert history[0]["old"] == "Первая"
    assert history[0]["new"] == "Вторая"
    assert history[1]["field"] == "organization"
    assert history[1]["old"] == "Вторая"
    assert history[1]["new"] == "Третья"


# 6. Регистрация не отменяется при правке данных
async def test_edit_participant_preserves_registration(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    reg_time = utc(2026, 11, 20, 9, 45)
    p = await make_participant(db, conf, "B24-1006", registered_at=reg_time, status="registered")

    r = await c.patch(f"/api/participants/{p.id}", json={"position": "Ведущий инженер"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["status"] == "registered"
    assert card["registration"] is not None
    assert datetime.fromisoformat(card["registration"]["at"]) == reg_time


# 7. Без изменений: история пустая, пометки data_changed нет
async def test_edit_without_changes_produces_no_history_or_flag(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1007", organization="ООО Ромашка")

    r = await c.patch(f"/api/participants/{p.id}", json={"organization": "ООО Ромашка"})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["history"] == []
    flags = [f["code"] for f in card["flags"]]
    assert "data_changed" not in flags


# 8. Изменение manual_fields в БД и событие data_changed в event_log
async def test_edit_updates_manual_fields_and_writes_event_log(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1008", organization="ООО Старт")

    r = await c.patch(f"/api/participants/{p.id}", json={"organization": "ООО Финиш"})
    assert r.status_code == 200, r.text

    p_db = await db.scalar(
        select(Participant).where(Participant.id == p.id).execution_options(populate_existing=True)
    )
    assert p_db is not None
    assert "organization" in p_db.manual_fields

    event = await db.scalar(
        select(EventLog).where(
            EventLog.participant_id == p.id,
            EventLog.type == "data_changed",
        )
    )
    assert event is not None
    assert event.user_id == c.user_id
    assert event.payload.get("fields") == ["organization"]


# 9. ER-03: триггер запрещает UPDATE и DELETE в change_log
async def test_change_log_cannot_be_updated_or_deleted(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1009", organization="ООО Старт")
    r = await c.patch(f"/api/participants/{p.id}", json={"organization": "ООО Финиш"})
    assert r.status_code == 200, r.text

    for sql in (
        "UPDATE change_log SET old_value = 'взлом' WHERE participant_id = :pid",
        "DELETE FROM change_log WHERE participant_id = :pid",
    ):
        # ошибка откатывает только savepoint, тестовая транзакция остаётся рабочей
        with pytest.raises(DBAPIError, match="append-only"):
            async with db.begin_nested():
                await db.execute(text(sql), {"pid": p.id})


# 10. ER-02: флаг data_changed виден в списке участников для печати
async def test_edited_participant_has_data_changed_flag_in_list(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1010", organization="ООО До")

    r_patch = await c.patch(f"/api/participants/{p.id}", json={"organization": "ООО После"})
    assert r_patch.status_code == 200, r_patch.text

    r_list = await c.get("/api/participants")
    assert r_list.status_code == 200, r_list.text
    items = r_list.json()["items"]
    matched = [item for item in items if item["id"] == p.id]
    assert len(matched) == 1
    assert "data_changed" in matched[0]["flags"]


# 11. 404 participant_not_found и 403 forbidden без права participants.edit
async def test_edit_participant_not_found_and_forbidden(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view", "participants.edit")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1011")

    r_404 = await c.patch("/api/participants/999999", json={"position": "Директор"})
    assert r_404.status_code == 404, r_404.text
    assert r_404.json()["code"] == "participant_not_found"

    c_view_only = await login_as("participants.view")
    r_403 = await c_view_only.patch(f"/api/participants/{p.id}", json={"position": "Директор"})
    assert r_403.status_code == 403, r_403.text
    assert r_403.json()["code"] == "forbidden"
