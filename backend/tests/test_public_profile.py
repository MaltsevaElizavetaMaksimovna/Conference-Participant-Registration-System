"""GET /api/public/profile/{token} и .../photo (B2-13): QR-01, QR-02, NF-06."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.ratelimit import PublicRateLimiter
from app.badges.tokens import new_badge_token
from app.models.participant import BadgeToken, Participant
from tests.registration_helpers import make_conference, make_participant

NOT_FOUND = {"code": "profile_not_found", "message": "Профиль не найден", "details": {}}
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF-test-photo"
SECURITY_HEADERS = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
    "x-robots-tag": "noindex, nofollow",
    "x-content-type-options": "nosniff",
}
PROFILE_KEYS = {"status", "full_name", "position", "organization", "photo_url"}


@pytest.fixture
def photo_dir(app_db: FastAPI, tmp_path: Path) -> Path:
    """Каталог фото приложения: свой у каждого теста; рядом лежит «секретный» файл снаружи."""
    root = tmp_path / "photos"
    root.mkdir()
    (tmp_path / "secret.jpg").write_bytes(b"\xff\xd8\xffSECRET")
    app_db.state.settings = app_db.state.settings.model_copy(update={"photo_dir": root})
    return root


async def make_badge(
    db: AsyncSession,
    *,
    status: str = "active",
    photo_path: str | None = None,
    external_id: str = "B24-1",
    **fields: Any,
) -> tuple[Participant, str]:
    conference = await make_conference(db, active=False)
    participant = await make_participant(db, conference, external_id, **fields)
    participant.photo_path = photo_path
    token = new_badge_token()
    db.add(BadgeToken(participant_id=participant.id, token=token, status=status))
    await db.commit()
    return participant, token


def assert_security_headers(r: httpx.Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert r.headers[name] == value, (name, r.status_code)


# ----------------------------------------------------------------- действующий код


async def test_active_profile_has_exactly_the_allowed_fields(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    (photo_dir / "1.jpg").write_bytes(JPEG)
    _, token = await make_badge(db, photo_path="1.jpg")

    r = await anon.get(f"/api/public/profile/{token}")

    assert r.status_code == 200
    body = r.json()
    assert set(body) == PROFILE_KEYS  # контакты, время регистрации, пометки, история — нет
    assert body == {
        "status": "active",
        "full_name": "Иванов Пётр Сергеевич",
        "position": "Инженер",
        "organization": "ООО Ромашка",
        "photo_url": f"/api/public/profile/{token}/photo",
    }


async def test_no_photo_gives_null_photo_url(anon: httpx.AsyncClient, db: AsyncSession) -> None:
    _, token = await make_badge(db, photo_path=None)

    r = await anon.get(f"/api/public/profile/{token}")

    assert r.status_code == 200
    assert r.json()["photo_url"] is None


async def test_empty_position_and_organization_are_null(
    anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    _, token = await make_badge(db, position="", organization=None, middle_name=None)

    body = (await anon.get(f"/api/public/profile/{token}")).json()

    assert body["position"] is None
    assert body["organization"] is None
    assert body["full_name"] == "Иванов Пётр"


async def test_photo_is_served_as_jpeg(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    (photo_dir / "sub").mkdir()
    (photo_dir / "sub" / "p.jpg").write_bytes(JPEG)
    _, token = await make_badge(db, photo_path="sub/p.jpg")

    r = await anon.get(f"/api/public/profile/{token}/photo")

    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == JPEG


async def test_participant_without_photo_has_photo_not_found(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    _, token = await make_badge(db, photo_path=None)

    r = await anon.get(f"/api/public/profile/{token}/photo")

    assert r.status_code == 404
    assert r.json()["code"] == "photo_not_found"
    assert_security_headers(r)


async def test_missing_photo_file_is_photo_not_found(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    _, token = await make_badge(db, photo_path="gone.jpg")

    r = await anon.get(f"/api/public/profile/{token}/photo")

    assert (r.status_code, r.json()["code"]) == (404, "photo_not_found")


# ------------------------------------------------------------------- отозванный код


async def test_revoked_gives_status_only_and_no_photo(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    (photo_dir / "1.jpg").write_bytes(JPEG)
    _, token = await make_badge(db, status="revoked", photo_path="1.jpg")

    r = await anon.get(f"/api/public/profile/{token}")
    photo = await anon.get(f"/api/public/profile/{token}/photo")

    assert r.status_code == 200
    assert r.json() == {"status": "revoked"}
    assert (photo.status_code, photo.json()) == (404, NOT_FOUND)
    assert photo.content != JPEG


# ------------------------------------------------------- неизвестный и неверный код


async def test_unknown_token_is_not_found(anon: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_badge(db)
    unknown = new_badge_token()

    for suffix in ("", "/photo"):
        r = await anon.get(f"/api/public/profile/{unknown}{suffix}")
        assert (r.status_code, r.json()) == (404, NOT_FOUND)


async def test_one_changed_character_is_not_found(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    (photo_dir / "1.jpg").write_bytes(JPEG)
    _, token = await make_badge(db, photo_path="1.jpg")
    assert (await anon.get(f"/api/public/profile/{token}")).status_code == 200

    for i in (0, len(token) // 2, len(token) - 1):
        changed = token[:i] + ("B" if token[i] == "A" else "A") + token[i + 1 :]
        for suffix in ("", "/photo"):
            r = await anon.get(f"/api/public/profile/{changed}{suffix}")
            assert (r.status_code, r.json()) == (404, NOT_FOUND), (i, suffix)


@pytest.mark.parametrize(
    "bad",
    [
        "a",
        "a" * 15,
        "a" * 65,
        "a" * 21 + "%21",  # «!»
        "a" * 21 + ".",
        "a" * 21 + "%0A",  # перевод строки в конце
        "a" * 21 + "%20",
        "%D0%B0" * 11,  # кириллица
        "a" * 8 + "%2e%2e" + "a" * 8,
    ],
)
async def test_malformed_token_is_not_found_without_db_query(
    anon: httpx.AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("запрос к БД для заведомо неверного токена")

    monkeypatch.setattr(db, "execute", forbidden)
    monkeypatch.setattr(db, "scalar", forbidden)

    for suffix in ("", "/photo"):
        r = await anon.get(f"/api/public/profile/{bad}{suffix}")
        assert (r.status_code, r.json()) == (404, NOT_FOUND), suffix
        assert_security_headers(r)


# ----------------------------------------------------------- защита от выхода из каталога


@pytest.mark.parametrize("dangerous", ["../secret.jpg", "sub/../../secret.jpg", "..\\secret.jpg"])
async def test_photo_path_cannot_leave_photo_dir(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path, dangerous: str
) -> None:
    (photo_dir / "sub").mkdir()
    _, token = await make_badge(db, photo_path=dangerous)

    r = await anon.get(f"/api/public/profile/{token}/photo")

    assert (r.status_code, r.json()["code"]) == (404, "photo_not_found")
    assert b"SECRET" not in r.content


async def test_absolute_photo_path_is_not_served(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    secret = photo_dir.parent / "secret.jpg"
    _, token = await make_badge(db, photo_path=str(secret))

    r = await anon.get(f"/api/public/profile/{token}/photo")

    assert (r.status_code, r.json()["code"]) == (404, "photo_not_found")


# ------------------------------------------------------------------------- заголовки


async def test_security_headers_on_every_response(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    (photo_dir / "1.jpg").write_bytes(JPEG)
    _, active = await make_badge(db, photo_path="1.jpg")
    _, revoked = await make_badge(db, status="revoked", external_id="B24-2")

    urls = [
        f"/api/public/profile/{active}",
        f"/api/public/profile/{active}/photo",
        f"/api/public/profile/{revoked}",
        f"/api/public/profile/{revoked}/photo",
        f"/api/public/profile/{new_badge_token()}",
        "/api/public/profile/short",
    ]
    for url in urls:
        assert_security_headers(await anon.get(url))


# ------------------------------------------------------------------------ частота


async def test_rate_limit_is_shared_by_both_addresses(
    app_db: FastAPI, anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    app_db.state.settings = app_db.state.settings.model_copy(
        update={"public_profile_rate_limit": 3, "public_profile_rate_window_s": 60}
    )
    (photo_dir / "1.jpg").write_bytes(JPEG)
    _, token = await make_badge(db, photo_path="1.jpg")

    assert (await anon.get(f"/api/public/profile/{token}")).status_code == 200
    assert (await anon.get(f"/api/public/profile/{token}/photo")).status_code == 200
    assert (await anon.get("/api/public/profile/short")).status_code == 404  # тоже считается
    r = await anon.get(f"/api/public/profile/{token}")

    assert r.status_code == 429
    body = r.json()
    assert body["code"] == "too_many_requests"
    assert body["details"]["retry_after_s"] >= 1
    assert r.headers["retry-after"] == str(body["details"]["retry_after_s"])
    assert_security_headers(r)
    assert (await anon.get(f"/api/public/profile/{token}/photo")).status_code == 429


async def test_default_rate_limit_is_60_per_minute(app_db: FastAPI) -> None:
    settings = app_db.state.settings
    assert (settings.public_profile_rate_limit, settings.public_profile_rate_window_s) == (60, 60)


def test_limiter_forgets_old_requests_and_separates_ips() -> None:
    now = [100.0]
    limiter = PublicRateLimiter(2, 60.0, clock=lambda: now[0])

    assert limiter.hit("1.1.1.1") is None
    assert limiter.hit("1.1.1.1") is None
    assert limiter.hit("1.1.1.1") is not None
    assert limiter.hit("2.2.2.2") is None  # у другого адреса свой счётчик
    now[0] += 61
    assert limiter.hit("1.1.1.1") is None


# ------------------------------------------------------------------ без авторизации


async def test_no_login_or_device_token_is_needed(
    anon: httpx.AsyncClient, db: AsyncSession, photo_dir: Path
) -> None:
    (photo_dir / "1.jpg").write_bytes(JPEG)
    _, token = await make_badge(db, photo_path="1.jpg")
    assert not anon.cookies

    for headers in ({}, {"Authorization": "Terminal not-a-real-token"}):
        r = await anon.get(f"/api/public/profile/{token}", headers=headers)
        assert r.status_code == 200
        assert (
            await anon.get(f"/api/public/profile/{token}/photo", headers=headers)
        ).status_code == 200
