"""Служебные команды: `python -m app.cli <migrate|bootstrap|seed-demo>`."""

import argparse
import asyncio
import contextlib
import random
import sys
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.enums import BadgeType
from app.core.loop import selector_loop_factory
from app.core.permissions import ADMIN_ROLE, DEFAULT_ROLES
from app.core.text import full_name, normalize_search
from app.models import (
    Conference,
    ExtraFieldDef,
    Participant,
    Printer,
    Role,
    RolePermission,
    StaffUser,
    Terminal,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent

DEMO_CONFERENCE_TITLE = "Демо-конференция"
DEMO_PARTICIPANTS = 300
DEMO_FIRST_ID = 1001
DEMO_SEED = 20240601


# --------------------------------------------------------------------------- migrate


def alembic_config(url: str | None = None) -> Config:
    """Конфиг Alembic; без `url` адрес БД берётся из настроек (RS_DATABASE_URL)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations").replace("%", "%%"))
    if url:
        cfg.attributes["url"] = url
    return cfg


def migrate(url: str | None = None) -> None:
    command.upgrade(alembic_config(url), "head")


# ------------------------------------------------------------------------- bootstrap


@dataclass
class BootstrapResult:
    created_roles: list[str] = field(default_factory=list)
    added_permissions: dict[str, list[str]] = field(default_factory=dict)
    admin_login: str | None = None


async def bootstrap(session: AsyncSession, settings: Settings) -> BootstrapResult:
    """Идемпотентно: системные роли с правами по умолчанию и первый администратор.

    Недостающие права у существующих ролей добавляются, лишние не удаляются.
    Коммит — на вызывающем.
    """
    result = BootstrapResult()
    roles: dict[str, Role] = {
        r.name: r for r in (await session.scalars(select(Role).where(Role.name.in_(DEFAULT_ROLES))))
    }
    for name in DEFAULT_ROLES:
        if name not in roles:
            role = Role(name=name, is_system=True)
            session.add(role)
            roles[name] = role
            result.created_roles.append(name)
    await session.flush()

    for name, perms in DEFAULT_ROLES.items():
        role = roles[name]
        have = set(
            await session.scalars(
                select(RolePermission.permission).where(RolePermission.role_id == role.id)
            )
        )
        missing = sorted(str(p) for p in perms if str(p) not in have)
        if missing:
            session.add_all(RolePermission(role_id=role.id, permission=p) for p in missing)
            result.added_permissions[name] = missing
    await session.flush()

    login, password = settings.bootstrap_admin_login, settings.bootstrap_admin_password
    staff_count = await session.scalar(select(func.count()).select_from(StaffUser))
    if not staff_count and login and password:
        session.add(
            StaffUser(
                full_name="Администратор",
                login=login,
                password_hash=PasswordHasher().hash(password),
                role_id=roles[ADMIN_ROLE].id,
            )
        )
        await session.flush()
        result.admin_login = login
    return result


# ------------------------------------------------------------------------ seed-demo

_MALE_LAST = [
    "Иванов", "Петров", "Сидоров", "Смирнов", "Кузнецов", "Попов", "Васильев", "Соколов",
    "Михайлов", "Новиков", "Фёдоров", "Морозов", "Волков", "Алексеев", "Лебедев", "Козлов",
    "Павлов", "Захаров", "Борисов", "Никитин", "Орлов", "Тихонов", "Беляев", "Комаров",
]  # fmt: skip
_FEMALE_LAST = [
    "Иванова", "Петрова", "Сидорова", "Смирнова", "Кузнецова", "Попова", "Васильева",
    "Соколова", "Михайлова", "Новикова", "Фёдорова", "Морозова", "Волкова", "Алексеева",
    "Лебедева", "Козлова", "Павлова", "Захарова", "Борисова", "Никитина", "Орлова",
    "Тихонова", "Беляева", "Комарова",
]  # fmt: skip
_MALE_LAST_YO = ["Королёв", "Семёнов", "Тёркин", "Пушкарёв", "Лазарев", "Жемчужников"]
_FEMALE_LAST_YO = ["Королёва", "Семёнова", "Тёркина", "Пушкарёва", "Лазарева", "Жемчужникова"]
_MALE_FIRST = [
    "Александр", "Дмитрий", "Максим", "Сергей", "Андрей", "Алексей", "Артём", "Илья",
    "Кирилл", "Михаил", "Никита", "Матвей", "Роман", "Егор", "Арсений", "Пётр", "Фёдор",
    "Владимир", "Николай", "Олег",
]  # fmt: skip
_FEMALE_FIRST = [
    "Анна", "Мария", "Елена", "Ольга", "Наталья", "Екатерина", "Татьяна", "Ирина",
    "Светлана", "Юлия", "Алёна", "Дарья", "Полина", "Ксения", "Вера", "Надежда",
    "Людмила", "Софья", "Алина", "Виктория",
]  # fmt: skip
_MALE_MIDDLE = [
    "Александрович", "Дмитриевич", "Сергеевич", "Андреевич", "Алексеевич", "Иванович",
    "Михайлович", "Николаевич", "Владимирович", "Петрович", "Артёмович", "Олегович",
]  # fmt: skip
_FEMALE_MIDDLE = [
    "Александровна", "Дмитриевна", "Сергеевна", "Андреевна", "Алексеевна", "Ивановна",
    "Михайловна", "Николаевна", "Владимировна", "Петровна", "Артёмовна", "Олеговна",
]  # fmt: skip
_POSITIONS = [
    ("Доцент", "Associate Professor"),
    ("Профессор", "Professor"),
    ("Старший научный сотрудник", "Senior Researcher"),
    ("Аспирант", "PhD Student"),
    ("Руководитель отдела", "Head of Department"),
    ("Инженер-программист", "Software Engineer"),
    ("Директор", "Director"),
    ("Ведущий аналитик", "Lead Analyst"),
]
_ORGANIZATIONS = [
    ("МГУ имени М. В. Ломоносова", "Lomonosov Moscow State University"),
    ("НИУ ВШЭ", "HSE University"),
    ("СПбГУ", "Saint Petersburg State University"),
    ("ООО «Ромашка»", "Romashka LLC"),
    ("АО «Технопарк»", "Technopark JSC"),
    ("Институт системного программирования РАН", "Ivannikov ISP RAS"),
    ("Казанский федеральный университет", "Kazan Federal University"),
    ("МФТИ", "MIPT"),
]
_SECTIONS = ["Алгоритмы", "Базы данных", "Безопасность", "Машинное обучение", "Робототехника"]

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}  # fmt: skip


def translit(s: str) -> str:
    out = "".join(_TRANSLIT.get(ch, _TRANSLIT.get(ch.lower(), ch)) for ch in s)
    return out[:1].upper() + out[1:]


def _long_organization(n: int) -> str:
    """Организация длиной ровно 120 символов (проверка вёрстки наклейки)."""
    base = f"Федеральное государственное бюджетное образовательное учреждение №{n} «"
    filler = "Демонстрационный университет имени Тестового Примера "
    return (base + filler * 3)[:119] + "»"


def demo_participant_rows(
    conference_id: int, count: int = DEMO_PARTICIPANTS
) -> list[dict[str, Any]]:
    """Детерминированный набор участников (один и тот же при каждом запуске)."""
    rng = random.Random(DEMO_SEED)
    rows: list[dict[str, Any]] = []
    for i in range(count):
        female = rng.random() < 0.5
        if female:
            last_pool, first_pool, middle_pool = _FEMALE_LAST, _FEMALE_FIRST, _FEMALE_MIDDLE
            last_yo = _FEMALE_LAST_YO
        else:
            last_pool, first_pool, middle_pool = _MALE_LAST, _MALE_FIRST, _MALE_MIDDLE
            last_yo = _MALE_LAST_YO
        last = rng.choice(last_yo if i % 10 == 0 else last_pool)  # каждый десятый — с «ё»
        first, middle = rng.choice(first_pool), rng.choice(middle_pool)
        position_ru, position_en = rng.choice(_POSITIONS)
        organization, organization_en = rng.choice(_ORGANIZATIONS)
        section = rng.choice(_SECTIONS)

        organization_ru: str | None = organization
        if i % 17 == 0:
            organization_ru = None  # пустая организация
        elif i % 50 == 7:
            organization_ru = _long_organization(i)
        with_en = i % 5 == 0  # английские поля есть у каждого пятого
        extra = {"section": section} if i % 4 != 3 else {}

        row: dict[str, Any] = {
            "conference_id": conference_id,
            "external_id": f"B24-{DEMO_FIRST_ID + i}",
            "last_name": last,
            "first_name": first,
            "middle_name": middle,
            "position": position_ru,
            "organization": organization_ru,
            "last_name_en": translit(last) if with_en else None,
            "first_name_en": translit(first) if with_en else None,
            "middle_name_en": translit(middle) if with_en else None,
            "position_en": position_en if with_en else None,
            "organization_en": organization_en if with_en and organization_ru else None,
            "extra": extra,
            "search_norm": normalize_search(full_name(last, first, middle)),
        }
        row["source_data"] = {
            k: row[k]
            for k in ("last_name", "first_name", "middle_name", "position", "organization")
        } | extra
        rows.append(row)
    return rows


@dataclass
class SeedResult:
    conference_id: int
    participants_added: int
    terminals_added: int
    printers_added: int
    conference_active: bool


async def seed_demo(session: AsyncSession) -> SeedResult:
    """Демо-данные для разработки; повторный запуск дублей не создаёт. Коммит — на вызывающем."""
    conference = await session.scalar(
        select(Conference).where(Conference.title == DEMO_CONFERENCE_TITLE)
    )
    if conference is None:
        # Активной может быть только одна: чужую активную не трогаем
        other_active = await session.scalar(
            select(func.count()).select_from(Conference).where(Conference.is_active.is_(True))
        )
        conference = Conference(
            title=DEMO_CONFERENCE_TITLE,
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 3),
            badge_type=BadgeType.SINGLE.value,
            is_active=not other_active,
        )
        session.add(conference)
        await session.flush()

    has_section = await session.scalar(
        select(ExtraFieldDef.id).where(
            ExtraFieldDef.conference_id == conference.id, ExtraFieldDef.key == "section"
        )
    )
    if has_section is None:
        session.add(
            ExtraFieldDef(conference_id=conference.id, key="section", label="Секция", sort_order=1)
        )

    existing = set(
        await session.scalars(
            select(Participant.external_id).where(Participant.conference_id == conference.id)
        )
    )
    new_rows = [r for r in demo_participant_rows(conference.id) if r["external_id"] not in existing]
    if new_rows:
        await session.execute(insert(Participant), new_rows)

    printers_added = terminals_added = 0
    for n in range(1, 4):
        printer = await session.scalar(select(Printer).where(Printer.name == f"Принтер {n}"))
        if printer is None:
            printer = Printer(name=f"Принтер {n}")
            session.add(printer)
            await session.flush()
            printers_added += 1
        terminal = await session.scalar(select(Terminal).where(Terminal.name == f"Терминал {n}"))
        if terminal is None:
            session.add(Terminal(name=f"Терминал {n}", printer_id=printer.id))
            terminals_added += 1
    await session.flush()
    return SeedResult(
        conference_id=conference.id,
        participants_added=len(new_rows),
        terminals_added=terminals_added,
        printers_added=printers_added,
        conference_active=conference.is_active,
    )


# ------------------------------------------------------------------------------ main


def _run(coro: Coroutine[Any, Any, None]) -> None:
    # Selector-цикл: psycopg async не работает на Proactor (Windows)
    asyncio.run(coro, loop_factory=selector_loop_factory)


async def _with_session(settings: Settings, action: str) -> None:
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)
    try:
        async with make_sessionmaker(engine)() as session:
            if action == "bootstrap":
                res = await bootstrap(session, settings)
                await session.commit()
                print(f"Новые роли: {', '.join(res.created_roles) or '—'}")
                for role, perms in res.added_permissions.items():
                    print(f"Добавлены права роли «{role}»: {', '.join(perms)}")
                if res.admin_login:
                    print(f"Создан администратор: {res.admin_login}")
            else:
                seeded = await seed_demo(session)
                await session.commit()
                print(
                    f"Демо-конференция (id={seeded.conference_id}"
                    f"{', активна' if seeded.conference_active else ', не активна'}): "
                    f"добавлено участников {seeded.participants_added}, "
                    f"терминалов {seeded.terminals_added}, принтеров {seeded.printers_added}"
                )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="применить миграции (alembic upgrade head)")
    sub.add_parser("bootstrap", help="системные роли и первый администратор (идемпотентно)")
    sub.add_parser("seed-demo", help="демо-данные для разработки (не в prod)")
    args = parser.parse_args(argv)

    # Русский текст в консоли Windows (cp1251/cp866) без падения
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(OSError, ValueError):
                stream.reconfigure(encoding="utf-8", errors="replace")

    settings = get_settings()
    if args.cmd == "migrate":
        migrate()
        print("Миграции применены")
    elif args.cmd == "bootstrap":
        _run(_with_session(settings, "bootstrap"))
    elif args.cmd == "seed-demo":
        if settings.env == "prod":
            print("seed-demo запрещён при RS_ENV=prod", file=sys.stderr)
            return 1
        _run(_with_session(settings, "seed-demo"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
