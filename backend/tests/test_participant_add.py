"""Добавление участника на месте и поиск дублей: `POST /api/participants` (B1-13, RG-07)."""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conference import Conference
from app.models.participant import EventLog, Participant
from app.models.printing import PrintJob
from app.models.staff import StaffUser
from tests.conftest import Devices, LoginAs
from tests.registration_helpers import make_conference, make_participant

# ---------------------------------------------------------------------------
# A. POST /api/participants/check-duplicates
# ---------------------------------------------------------------------------


# 1. RG-07: Добавить «Иванов Пётр», когда есть «Иванов Пётр Сергеевич» -> возможный дубль
async def test_check_duplicates_finds_similar_participant(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    conf = await make_conference(db)
    p = await make_participant(
        db,
        conf,
        "B24-1001",
        last_name="Иванов",
        first_name="Пётр",
        middle_name="Сергеевич",
        organization="ООО Ромашка",
    )

    r = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "Иванов", "first_name": "Пётр"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["id"] == p.id
    assert item["full_name"] == "Иванов Пётр Сергеевич"
    assert item["organization"] == "ООО Ромашка"
    assert item["status"] == "not_registered"
    assert isinstance(item["flags"], list)


# 2. Регистр и буква ё
async def test_check_duplicates_case_and_yo_insensitive(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    conf = await make_conference(db)
    p = await make_participant(
        db,
        conf,
        "B24-1002",
        last_name="Иванов",
        first_name="Пётр",
        middle_name="Сергеевич",
    )

    r = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "ИВАНОВ", "first_name": "петр"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(item["id"] == p.id for item in items)


# 3. Опечатка в фамилии
async def test_check_duplicates_typo_tolerance(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.add")
    conf = await make_conference(db)
    p = await make_participant(
        db,
        conf,
        "B24-1003",
        last_name="Иванов",
        first_name="Пётр",
        middle_name="Сергеевич",
    )

    r = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "Ивнов", "first_name": "Пётр"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(item["id"] == p.id for item in items)


# 4. Перестановка фамилии и имени
async def test_check_duplicates_swapped_names(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.add")
    conf = await make_conference(db)
    p = await make_participant(
        db,
        conf,
        "B24-1004",
        last_name="Иванов",
        first_name="Пётр",
        middle_name="Сергеевич",
    )

    r = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "Пётр", "first_name": "Иванов"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert any(item["id"] == p.id for item in items)


# 5. Не дубли: «Петров Пётр» и «Иванов Олег» не попадают в выдачу
async def test_check_duplicates_different_people_not_found(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    conf = await make_conference(db)
    p1 = await make_participant(db, conf, "B24-1005", last_name="Петров", first_name="Пётр")
    p2 = await make_participant(db, conf, "B24-1006", last_name="Иванов", first_name="Олег")

    r = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "Иванов", "first_name": "Пётр"},
    )
    assert r.status_code == 200, r.text
    found_ids = [item["id"] for item in r.json()["items"]]
    assert p1.id not in found_ids
    assert p2.id not in found_ids


# 6. Порядок: точное совпадение идёт раньше опечатки
async def test_check_duplicates_sort_order_exact_match_first(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    conf = await make_conference(db)
    p_exact = await make_participant(
        db,
        conf,
        "B24-1007",
        last_name="Иванов",
        first_name="Пётр",
        middle_name="Сергеевич",
    )
    p_similar = await make_participant(
        db,
        conf,
        "B24-1008",
        last_name="Иванова",
        first_name="Пётр",
        middle_name="Ильич",
    )

    r = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "Иванов", "first_name": "Пётр"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) >= 2
    assert items[0]["id"] == p_exact.id
    assert items[1]["id"] == p_similar.id


# 7. Участник неактивной конференции не попадает; без активной конференции — пустой список
async def test_check_duplicates_inactive_conference_ignored_or_empty(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    conf_old = await make_conference(db, active=False, title="Прошлая")
    await make_participant(
        db,
        conf_old,
        "B24-OLD",
        last_name="Иванов",
        first_name="Пётр",
        middle_name="Сергеевич",
    )
    conf_act = await make_conference(db, active=True, title="Текущая")

    r = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "Иванов", "first_name": "Пётр"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []

    await db.execute(update(Conference).where(Conference.id == conf_act.id).values(is_active=False))
    await db.commit()

    r_no_conf = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "Иванов", "first_name": "Пётр"},
    )
    assert r_no_conf.status_code == 200, r_no_conf.text
    assert r_no_conf.json() == {"items": []}


# 8. Не больше 10 похожих участников
async def test_check_duplicates_limit_ten(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.add")
    conf = await make_conference(db)
    for i in range(12):
        await make_participant(
            db,
            conf,
            f"B24-10{i:02d}",
            last_name="Иванов",
            first_name="Пётр",
            middle_name=f"Отчество{i}",
        )

    r = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "Иванов", "first_name": "Пётр"},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 10


# 9. Валидация: пустая фамилия -> 422 validation_error
async def test_check_duplicates_empty_last_name_validation(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    await make_conference(db)

    r = await c.post(
        "/api/participants/check-duplicates",
        json={"last_name": "", "first_name": "Пётр"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "validation_error"


# 10. Без права participants.add -> 403 forbidden
async def test_check_duplicates_forbidden_without_permission(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c_view = await login_as("participants.view")
    await make_conference(db)

    r = await c_view.post(
        "/api/participants/check-duplicates",
        json={"last_name": "Иванов", "first_name": "Пётр"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "forbidden"


# ---------------------------------------------------------------------------
# B. POST /api/participants
# ---------------------------------------------------------------------------


# 1. RG-07: Добавить участника с печатью наклейки на принтер панели
async def test_add_participant_with_sticker_and_printer(
    login_as: LoginAs, db: AsyncSession, devices: Devices
) -> None:
    c = await login_as("participants.view", "participants.add", "stickers.print")
    await make_conference(db, badge_type="single")
    printer, _ = await devices.printer("Принтер 1")
    await db.execute(
        update(StaffUser).where(StaffUser.id == c.user_id).values(panel_printer_id=printer.id)
    )
    await db.commit()

    r = await c.post("/api/participants", json={"last_name": "Смирнова", "first_name": "Анна"})
    assert r.status_code == 201, r.text
    data = r.json()
    card = data["participant"]
    assert card["status"] == "registered"
    assert card["external_id"] is None
    flag_codes = [f["code"] for f in card["flags"]]
    assert "manual_added" in flag_codes
    assert "data_changed" in flag_codes
    assert card["registration"] is not None
    assert card["registration"]["source"] == "desk"
    assert card["registration"]["user_login"] == c.login
    assert card["registration"]["terminal_name"] is None

    print_job_id = data["print_job_id"]
    assert isinstance(print_job_id, int)
    job = await db.scalar(select(PrintJob).where(PrintJob.id == print_job_id))
    assert job is not None
    assert job.participant_id == card["id"]
    assert job.printer_id == printer.id

    search_r = await c.get("/api/participants", params={"q": "смирнова"})
    assert search_r.status_code == 200, search_r.text
    items = search_r.json()["items"]
    matched = [it for it in items if it["id"] == card["id"]]
    assert len(matched) == 1
    assert matched[0]["status"] == "registered"
    assert "manual_added" in matched[0]["flags"]


# 2. Без наклейки: with_sticker=false
async def test_add_participant_without_sticker(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.add")
    await make_conference(db, badge_type="single")

    r = await c.post(
        "/api/participants",
        json={"last_name": "Кузнецов", "first_name": "Алексей", "with_sticker": False},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["participant"]["status"] == "registered_no_sticker"
    assert data["print_job_id"] is None


# 3. with_sticker=true без права stickers.print -> 403, участник не создан
async def test_add_participant_with_sticker_missing_print_permission(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    await make_conference(db, badge_type="single")

    r = await c.post(
        "/api/participants",
        json={"last_name": "Николаев", "first_name": "Илья", "with_sticker": True},
    )
    assert r.status_code == 403, r.text
    data = r.json()
    assert data["code"] == "forbidden"
    assert "stickers.print" in data["details"]["missing"]

    p = await db.scalar(select(Participant).where(Participant.last_name == "Николаев"))
    assert p is None


# 4. Нет принтера в панели -> 201, status registered, sticker_not_printed во flags
async def test_add_participant_no_panel_printer_selected(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add", "stickers.print")
    await make_conference(db, badge_type="single")

    r = await c.post(
        "/api/participants",
        json={"last_name": "Попов", "first_name": "Михаил", "with_sticker": True},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    card = data["participant"]
    assert card["status"] == "registered"
    assert data["print_job_id"] is None
    flag_codes = [f["code"] for f in card["flags"]]
    assert "sticker_not_printed" in flag_codes


# 5. Конференция без бейджей (badge_type="none") -> registered_no_sticker
async def test_add_participant_conference_without_badges(
    login_as: LoginAs, db: AsyncSession, devices: Devices
) -> None:
    c = await login_as("participants.add", "stickers.print")
    await make_conference(db, badge_type="none")
    printer, _ = await devices.printer("Принтер 1")
    await db.execute(
        update(StaffUser).where(StaffUser.id == c.user_id).values(panel_printer_id=printer.id)
    )
    await db.commit()

    r = await c.post(
        "/api/participants",
        json={"last_name": "Григорьев", "first_name": "Павел", "with_sticker": True},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["participant"]["status"] == "registered_no_sticker"
    assert data["print_job_id"] is None


# 6. Пробелы в полях и валидация обязательных полей
async def test_add_participant_whitespace_stripping_and_validation(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    await make_conference(db)

    r_ok = await c.post(
        "/api/participants",
        json={
            "last_name": "Васильев",
            "first_name": "Сергей",
            "middle_name": "   ",
            "organization": "  ООО Ромашка  ",
            "with_sticker": False,
        },
    )
    assert r_ok.status_code == 201, r_ok.text
    card = r_ok.json()["participant"]
    assert card["middle_name"] is None
    assert card["organization"] == "ООО Ромашка"

    r_blank_last = await c.post(
        "/api/participants",
        json={"last_name": "  ", "first_name": "Сергей", "with_sticker": False},
    )
    assert r_blank_last.status_code == 422, r_blank_last.text
    assert r_blank_last.json()["code"] == "validation_error"
    assert r_blank_last.json()["details"]["fields"]["last_name"] == "Укажите фамилию"

    r_no_first = await c.post(
        "/api/participants",
        json={"last_name": "Васильев", "with_sticker": False},
    )
    assert r_no_first.status_code == 422, r_no_first.text
    assert r_no_first.json()["code"] == "validation_error"


# 7. События manual_added и registered в event_log
async def test_add_participant_creates_manual_added_and_registered_events(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    await make_conference(db)

    r = await c.post(
        "/api/participants",
        json={"last_name": "Семенов", "first_name": "Константин", "with_sticker": False},
    )
    assert r.status_code == 201, r.text
    pid = r.json()["participant"]["id"]

    ev_manual = await db.scalar(
        select(EventLog).where(
            EventLog.participant_id == pid,
            EventLog.type == "manual_added",
        )
    )
    assert ev_manual is not None
    assert ev_manual.user_id == c.user_id

    ev_registered = await db.scalar(
        select(EventLog).where(
            EventLog.participant_id == pid,
            EventLog.type == "registered",
        )
    )
    assert ev_registered is not None
    assert ev_registered.user_id == c.user_id


# 8. Счётчик /api/participants/stats вырастает на 1
async def test_add_participant_increments_stats_counters(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view", "participants.add")
    await make_conference(db)

    r_before = await c.get("/api/participants/stats")
    assert r_before.status_code == 200, r_before.text
    stats_before = r_before.json()

    r_add = await c.post(
        "/api/participants",
        json={"last_name": "Зайцев", "first_name": "Роман", "with_sticker": False},
    )
    assert r_add.status_code == 201, r_add.text

    r_after = await c.get("/api/participants/stats")
    assert r_after.status_code == 200, r_after.text
    stats_after = r_after.json()

    assert stats_after["registered"] == stats_before["registered"] + 1
    assert stats_after["total"] == stats_before["total"] + 1


# 9. Нет активной конференции -> 409 no_active_conference
async def test_add_participant_no_active_conference_conflict(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.add")
    await make_conference(db, active=False, title="Прошлая")

    r = await c.post(
        "/api/participants",
        json={"last_name": "Борисов", "first_name": "Глеб", "with_sticker": False},
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "no_active_conference"


# 10. Без права participants.add -> 403 forbidden
async def test_add_participant_forbidden_without_permission(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await login_as("participants.view")
    await make_conference(db)

    r = await c.post(
        "/api/participants",
        json={"last_name": "Тихонов", "first_name": "Егор", "with_sticker": False},
    )
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "forbidden"
