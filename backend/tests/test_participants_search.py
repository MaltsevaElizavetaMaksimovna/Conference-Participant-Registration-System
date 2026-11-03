"""Список и поиск участников: `GET /api/participants` (B1-09, RG-02, NF-01)."""

import time
from datetime import UTC, datetime

import httpx
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.text import normalize_search
from app.models.conference import Conference
from app.models.participant import Participant
from tests.conftest import LoginAs, StaffClient
from tests.registration_helpers import make_conference, make_participant, utc

URL = "/api/participants"


async def names(c: httpx.AsyncClient, query: str = "") -> list[str]:
    r = await c.get(f"{URL}?{query}")
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == len(page["items"])
    return [p["full_name"] for p in page["items"]]


async def people(db: AsyncSession, conf: Conference) -> None:
    await make_participant(db, conf, "P-1")  # Иванов Пётр Сергеевич
    await make_participant(
        db, conf, "P-2", last_name="Петров", first_name="Иван", middle_name="Ильич"
    )
    await make_participant(
        db, conf, "P-3", last_name="Фёдоров", first_name="Олег", middle_name=None
    )
    await make_participant(
        db, conf, "P-4", last_name="Иванова", first_name="Анна", middle_name="Олеговна"
    )


async def viewer(login_as: LoginAs, db: AsyncSession) -> tuple[StaffClient, Conference]:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    await people(db, conf)
    return c, conf


# ---------------------------------------------------------------- RG-02: «Как проверить»


async def test_case_insensitive_part_of_word(login_as: LoginAs, db: AsyncSession) -> None:
    c, _ = await viewer(login_as, db)
    assert await names(c, "q=ИВАН") == [
        "Иванов Пётр Сергеевич",
        "Иванова Анна Олеговна",
        "Петров Иван Ильич",
    ]


async def test_yo_and_ye_are_the_same(login_as: LoginAs, db: AsyncSession) -> None:
    c, _ = await viewer(login_as, db)
    assert await names(c, "q=Федоров") == ["Фёдоров Олег"]
    assert await names(c, "q=фёдОРОВ") == ["Фёдоров Олег"]
    assert await names(c, "q=петр") == ["Иванов Пётр Сергеевич", "Петров Иван Ильич"]


async def test_several_words_in_any_order(login_as: LoginAs, db: AsyncSession) -> None:
    c, _ = await viewer(login_as, db)
    assert await names(c, "q=Пётр Иванов") == ["Иванов Пётр Сергеевич"]
    assert await names(c, "q=  олег   ФЁД ") == ["Фёдоров Олег"]
    # слова объединяются по И: ни у кого нет сразу «петр» и «олег»
    assert await names(c, "q=Пётр Олег") == []


async def test_nothing_found(login_as: LoginAs, db: AsyncSession) -> None:
    c, _ = await viewer(login_as, db)
    r = await c.get(URL, params={"q": "ыыыы"})
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "total": 0}


# ---------------------------------------------------------------- детали поиска


async def test_search_starts_from_min_chars(
    login_as: LoginAs, db: AsyncSession, settings: Settings
) -> None:
    c, _ = await viewer(login_as, db)
    assert settings.search_min_chars == 2
    everyone = await names(c)
    assert len(everyone) == 4
    # короче порога (и пустая строка) — поиска нет, отдаётся весь список
    assert await names(c, "q=ф") == everyone
    assert await names(c, "q=  ") == everyone
    assert await names(c, "q=") == everyone
    assert await names(c, "q=фё") == ["Фёдоров Олег"]


async def test_like_wildcards_are_plain_text(login_as: LoginAs, db: AsyncSession) -> None:
    c, _ = await viewer(login_as, db)
    assert await names(c, "q=%25%25") == []
    assert await names(c, "q=__") == []
    assert await names(c, "q=ив%25") == []


async def test_only_active_conference(login_as: LoginAs, db: AsyncSession) -> None:
    c, _ = await viewer(login_as, db)
    old = await make_conference(db, active=False, title="Прошлая")
    await make_participant(db, old, "OLD-1", last_name="Иванчук")
    assert "Иванчук Пётр Сергеевич" not in await names(c, "q=иван")
    assert len(await names(c)) == 4


async def test_no_active_conference_is_empty(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    old = await make_conference(db, active=False)
    await make_participant(db, old)
    r = await c.get(URL, params={"q": "иван"})
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "total": 0}


async def test_item_shape_and_flags(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    plain = await make_participant(db, conf, "P-1", organization=None)
    flagged = await make_participant(
        db,
        conf,
        "P-2",
        last_name="Петрова",
        first_name="Анна",
        middle_name=None,
        registered_at=utc(2026, 11, 20, 9, 15),
        status="registered_no_sticker",
    )
    flagged.error_reported_at = utc(2026, 11, 20, 9, 0)
    flagged.sticker_not_printed = True
    flagged.manual_fields = ["organization"]
    flagged.foreign_code_at = utc(2026, 11, 20, 9, 20)
    manual = await make_participant(db, conf, None, last_name="Сидоров", first_name="Олег")
    manual.is_manual_added = True
    await db.commit()

    r = await c.get(URL)
    assert r.status_code == 200, r.text
    items = {p["id"]: p for p in r.json()["items"]}
    assert items[plain.id] == {
        "id": plain.id,
        "full_name": "Иванов Пётр Сергеевич",
        "organization": None,
        "status": "not_registered",
        "flags": [],
    }
    assert items[flagged.id]["full_name"] == "Петрова Анна"
    assert items[flagged.id]["status"] == "registered_no_sticker"
    assert items[flagged.id]["flags"] == [
        "error_reported",
        "sticker_not_printed",
        "data_changed",
        "foreign_code",
    ]
    assert items[manual.id]["flags"] == ["data_changed", "manual_added"]


# ---------------------------------------------------------------- фильтры и сортировка


async def test_filters(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    await make_participant(db, conf, "P-1", registered_at=utc(2026, 11, 20, 9, 0))
    await make_participant(db, conf, "P-2", last_name="Петрова", first_name="Анна")
    no_sticker = await make_participant(
        db,
        conf,
        "P-3",
        last_name="Сидоров",
        first_name="Олег",
        registered_at=utc(2026, 11, 20, 9, 5),
        status="registered_no_sticker",
    )
    no_sticker.sticker_not_printed = True
    await db.commit()

    assert await names(c, "filter=all") == [
        "Иванов Пётр Сергеевич",
        "Петрова Анна Сергеевич",
        "Сидоров Олег Сергеевич",
    ]
    assert await names(c, "filter=registered") == [
        "Иванов Пётр Сергеевич",
        "Сидоров Олег Сергеевич",
    ]
    assert await names(c, "filter=not_registered") == ["Петрова Анна Сергеевич"]
    assert await names(c, "filter=flagged") == ["Сидоров Олег Сергеевич"]
    assert await names(c, "filter=registered&q=сид") == ["Сидоров Олег Сергеевич"]
    bad = await c.get(URL, params={"filter": "nope"})
    assert bad.status_code == 422
    assert bad.json()["code"] == "validation_error"


async def test_sort(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    await make_participant(db, conf, "P-1", last_name="Яковлев", registered_at=utc(2026, 11, 20, 9))
    await make_participant(db, conf, "P-2", last_name="Борисов")
    await make_participant(db, conf, "P-3", last_name="Ёлкин", registered_at=utc(2026, 11, 20, 8))
    await make_participant(db, conf, "P-4", last_name="Елисеев")

    by_name = ["Борисов", "Елисеев", "Ёлкин", "Яковлев"]
    assert [n.split()[0] for n in await names(c)] == by_name
    assert [n.split()[0] for n in await names(c, "sort=name")] == by_name
    # незарегистрированные всегда в конце, между собой — по ФИО
    assert [n.split()[0] for n in await names(c, "sort=registered_at")] == [
        "Ёлкин",
        "Яковлев",
        "Борисов",
        "Елисеев",
    ]
    assert [n.split()[0] for n in await names(c, "sort=-registered_at")] == [
        "Яковлев",
        "Ёлкин",
        "Борисов",
        "Елисеев",
    ]
    bad = await c.get(URL, params={"sort": "id"})
    assert bad.status_code == 422


async def test_pagination(login_as: LoginAs, db: AsyncSession) -> None:
    c, _ = await viewer(login_as, db)
    r = await c.get(URL, params={"limit": 2, "offset": 1})
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 4
    assert [p["full_name"] for p in page["items"]] == [
        "Иванова Анна Олеговна",
        "Петров Иван Ильич",
    ]
    r = await c.get(URL, params={"q": "иван", "limit": 1})
    assert r.json()["total"] == 3
    assert len(r.json()["items"]) == 1


# ---------------------------------------------------------------- NF-01: 1000 участников


async def test_search_1000_participants_within_limit(
    login_as: LoginAs, db: AsyncSession, settings: Settings
) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    rows = []
    for i in range(1000):
        last, first, middle = f"Фамилия{i:04d}", f"Имя{i % 37}", f"Отчество{i % 11}"
        rows.append(
            {
                "conference_id": conf.id,
                "external_id": f"B-{i}",
                "last_name": last,
                "first_name": first,
                "middle_name": middle,
                "search_norm": normalize_search(f"{last} {first} {middle}"),
                "status": "registered" if i % 3 == 0 else "not_registered",
                "registered_at": datetime(2026, 11, 20, 9, tzinfo=UTC) if i % 3 == 0 else None,
            }
        )
    await db.execute(insert(Participant), rows)
    await db.commit()

    for query in ("фамилия05", "имя3 отчество1", "фам", "ыыыы"):
        started = time.perf_counter()
        r = await c.get(URL, params={"q": query, "limit": 200})
        elapsed = time.perf_counter() - started
        assert r.status_code == 200, r.text
        assert elapsed < settings.search_timeout_s, (query, elapsed)
    assert r.json()["total"] == 0
    r = await c.get(URL, params={"q": "фамилия05"})
    assert r.json()["total"] == 100
