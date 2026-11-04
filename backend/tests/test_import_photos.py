"""Тесты фоновой загрузки фото после импорта участников (B1-06, IM-01, QR-02)."""

import asyncio
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.imports.photo_apply import save_participant_photo
from app.imports.photo_fetch import PhotoFetchError
from app.imports.photo_worker import PhotoWorker
from app.models.conference import Conference
from app.models.participant import Participant
from tests.conftest import LoginAs, StaffClient
from tests.import_files import HEADERS, make_conference, person, upload, upload_report, xlsx_bytes


@pytest.fixture
def worker(app_db: FastAPI, db: AsyncSession, tmp_path: Path) -> PhotoWorker:
    @asynccontextmanager
    async def sessions() -> AsyncIterator[AsyncSession]:
        yield db

    app_db.state.settings = app_db.state.settings.model_copy(
        update={"photo_dir": tmp_path / "photos", "photo_workers": 1}
    )
    w = PhotoWorker(sessions, lambda: app_db.state.settings)
    app_db.state.photo_worker = w
    return w


def make_jpeg(width: int = 100, height: int = 100, color: str = "red") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_png(width: int = 100, height: int = 100, color: str = "red") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def active_conference(db: AsyncSession, title: str = "Конференция") -> int:
    conf_id = await make_conference(db, title)
    conf = await db.get(Conference, conf_id)
    assert conf is not None
    conf.is_active = True
    await db.commit()
    return conf_id


# 1. Две строки с фото: A -> корректный JPEG, B -> PhotoFetchError
async def test_two_rows_one_success_one_fail(
    login_as: LoginAs,
    db: AsyncSession,
    worker: PhotoWorker,
    app_db: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c: StaffClient = await login_as("imports.run", "participants.view")
    conf = await active_conference(db)

    img_a = make_jpeg(120, 120, color="blue")
    url_a = "https://example.com/photo_a.jpg"
    url_b = "https://example.com/photo_b.jpg"

    async def fake(url: str, **kwargs: Any) -> bytes:
        if url == url_a:
            return img_a
        if url == url_b:
            raise PhotoFetchError("http_status")
        raise PhotoFetchError("network")

    monkeypatch.setattr("app.imports.photo_worker.fetch_photo", fake)

    row_a = [*person(1), url_a]
    row_b = [*person(2), url_b]
    headers = [*HEADERS, "Фото (ссылка)"]

    r = await upload(c, conf, "p.xlsx", xlsx_bytes([row_a, row_b], headers=headers))
    assert r.status_code == 202
    batch_id = r.json()["batch_id"]

    await worker.wait_idle()

    report = (await c.get(f"/api/admin/conferences/{conf}/imports/{batch_id}")).json()
    assert report["photos"] == {"total": 2, "loaded": 1, "failed": 1, "pending": 0}
    assert "Строка 3: фото не загружено" in report["warnings"]

    db.expunge_all()
    rows = list(
        await db.scalars(
            select(Participant).where(Participant.conference_id == conf).order_by(Participant.id)
        )
    )
    p_a = next(p for p in rows if p.external_id == "P-1")
    p_b = next(p for p in rows if p.external_id == "P-2")

    assert p_a.photo_path is not None
    assert p_a.photo_sha256 is not None
    photo_file = app_db.state.settings.photo_dir / p_a.photo_path
    assert photo_file.is_file()

    photo_resp = await c.get(f"/api/participants/{p_a.id}/photo")
    assert photo_resp.status_code == 200
    assert photo_resp.headers["content-type"] == "image/jpeg"

    assert p_b.photo_path is None
    assert p_b.photo_sha256 is None


# 2. Готово-критерий «ссылка на 127.0.0.1»: НАСТОЯЩИЙ fetch_photo
async def test_ssrf_blocked_address_loopback(
    login_as: LoginAs,
    db: AsyncSession,
    worker: PhotoWorker,
) -> None:
    c: StaffClient = await login_as("imports.run", "participants.view")
    conf = await active_conference(db)

    headers = [*HEADERS, "Фото (ссылка)"]
    rows = [[*person(1), "http://127.0.0.1:9/p.jpg"]]

    r = await upload(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers))
    assert r.status_code == 202
    batch_id = r.json()["batch_id"]

    await worker.wait_idle()

    report = (await c.get(f"/api/admin/conferences/{conf}/imports/{batch_id}")).json()
    assert report["photos"] == {"total": 1, "loaded": 0, "failed": 1, "pending": 0}
    assert "Строка 2: фото не загружено" in report["warnings"]

    db.expunge_all()
    p = await db.scalar(
        select(Participant).where(
            Participant.conference_id == conf, Participant.external_id == "P-1"
        )
    )
    assert p is not None
    assert p.photo_path is None


# 3. Готово-критерий «картинка-бомба»: fake отдаёт PNG 8000x8000 при photo_max_pixels=1_000_000
async def test_decompression_bomb_rejected(
    login_as: LoginAs,
    db: AsyncSession,
    worker: PhotoWorker,
    app_db: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c: StaffClient = await login_as("imports.run", "participants.view")
    conf = await active_conference(db)

    app_db.state.settings = app_db.state.settings.model_copy(update={"photo_max_pixels": 1_000_000})

    bomb_bytes = make_png(8000, 8000, color="white")

    async def fake(url: str, **kwargs: Any) -> bytes:
        return bomb_bytes

    monkeypatch.setattr("app.imports.photo_worker.fetch_photo", fake)

    headers = [*HEADERS, "Фото (ссылка)"]
    rows = [[*person(1), "https://example.com/bomb.png"]]

    r = await upload(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers))
    assert r.status_code == 202
    batch_id = r.json()["batch_id"]

    await worker.wait_idle()

    report = (await c.get(f"/api/admin/conferences/{conf}/imports/{batch_id}")).json()
    assert report["photos"] == {"total": 1, "loaded": 0, "failed": 1, "pending": 0}
    assert "Строка 2: фото не загружено" in report["warnings"]

    db.expunge_all()
    p = await db.scalar(
        select(Participant).where(
            Participant.conference_id == conf, Participant.external_id == "P-1"
        )
    )
    assert p is not None
    assert p.photo_path is None


# 4. Битая ссылка и «не картинка»
async def test_broken_link_and_not_an_image(
    login_as: LoginAs,
    db: AsyncSession,
    worker: PhotoWorker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c: StaffClient = await login_as("imports.run", "participants.view")
    conf = await active_conference(db)

    async def fake(url: str, **kwargs: Any) -> bytes:
        if "broken" in url:
            raise PhotoFetchError("network")
        return b"<html><body>Not an image</body></html>"

    monkeypatch.setattr("app.imports.photo_worker.fetch_photo", fake)

    headers = [*HEADERS, "Фото (ссылка)"]
    rows = [
        [*person(1), "https://example.com/broken.jpg"],
        [*person(2), "https://example.com/html.jpg"],
    ]

    r = await upload(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers))
    assert r.status_code == 202
    batch_id = r.json()["batch_id"]

    await worker.wait_idle()

    report = (await c.get(f"/api/admin/conferences/{conf}/imports/{batch_id}")).json()
    assert report["photos"] == {"total": 2, "loaded": 0, "failed": 2, "pending": 0}
    assert "Строка 2: фото не загружено" in report["warnings"]
    assert "Строка 3: фото не загружено" in report["warnings"]

    db.expunge_all()
    rows_db = list(
        await db.scalars(
            select(Participant).where(Participant.conference_id == conf).order_by(Participant.id)
        )
    )
    assert len(rows_db) == 2
    assert rows_db[0].photo_path is None
    assert rows_db[1].photo_path is None


# 5. Строка без ссылки
async def test_row_without_photo_link(
    login_as: LoginAs,
    db: AsyncSession,
    worker: PhotoWorker,
) -> None:
    c: StaffClient = await login_as("imports.run", "participants.view")
    conf = await active_conference(db)

    headers = [*HEADERS, "Фото (ссылка)"]
    rows = [[*person(1), ""]]

    r = await upload(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers))
    assert r.status_code == 202
    batch_id = r.json()["batch_id"]

    report = (await c.get(f"/api/admin/conferences/{conf}/imports/{batch_id}")).json()
    assert report["photos"] == {"total": 0, "loaded": 0, "failed": 0, "pending": 0}
    assert len(worker._tasks) == 0


# 6. Импорт не ждёт фото
async def test_import_does_not_wait_for_photos(
    login_as: LoginAs,
    db: AsyncSession,
    worker: PhotoWorker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c: StaffClient = await login_as("imports.run", "participants.view")
    conf = await active_conference(db)

    img = make_jpeg(100, 100)

    async def fake_slow(url: str, **kwargs: Any) -> bytes:
        await asyncio.sleep(0.5)
        return img

    monkeypatch.setattr("app.imports.photo_worker.fetch_photo", fake_slow)

    headers = [*HEADERS, "Фото (ссылка)"]
    rows = [[*person(1), "https://example.com/slow.jpg"]]

    r = await upload(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers))
    assert r.status_code == 202
    batch_id = r.json()["batch_id"]

    # Сразу после upload (до wait_idle)
    report_pending = (await c.get(f"/api/admin/conferences/{conf}/imports/{batch_id}")).json()
    assert report_pending["photos"]["pending"] == 1
    assert report_pending["photos"]["total"] == 1
    assert report_pending["photos"]["loaded"] == 0

    await worker.wait_idle()

    # После wait_idle
    report_done = (await c.get(f"/api/admin/conferences/{conf}/imports/{batch_id}")).json()
    assert report_done["photos"]["pending"] == 0
    assert report_done["photos"]["loaded"] == 1
    assert report_done["photos"]["total"] == 1


# 7. Повторная загрузка: та же ссылка, изменённая ссылка, пустая ссылка
async def test_reupload_scenarios(
    login_as: LoginAs,
    db: AsyncSession,
    worker: PhotoWorker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c: StaffClient = await login_as("imports.run", "participants.view")
    conf = await active_conference(db)

    img_1 = make_jpeg(100, 100, color="red")
    img_2 = make_jpeg(100, 100, color="blue")

    async def fake(url: str, **kwargs: Any) -> bytes:
        if "photo1" in url:
            return img_1
        if "photo2" in url:
            return img_2
        raise PhotoFetchError("network")

    monkeypatch.setattr("app.imports.photo_worker.fetch_photo", fake)
    headers = [*HEADERS, "Фото (ссылка)"]

    # Первичная загрузка
    r1 = await upload(
        c,
        conf,
        "p.xlsx",
        xlsx_bytes([[*person(1), "https://example.com/photo1.jpg"]], headers=headers),
    )
    assert r1.status_code == 202
    await worker.wait_idle()

    db.expunge_all()
    p1 = await db.scalar(
        select(Participant).where(
            Participant.conference_id == conf, Participant.external_id == "P-1"
        )
    )
    assert p1 is not None
    assert p1.photo_path is not None
    assert p1.photo_sha256 is not None
    original_sha = p1.photo_sha256
    original_path = p1.photo_path

    # (а) Та же ссылка -> нового задания нет (photos.total == 0), фото сохраняется
    r_a = await upload_report(
        c,
        conf,
        "p.xlsx",
        xlsx_bytes([[*person(1), "https://example.com/photo1.jpg"]], headers=headers),
    )
    assert r_a["photos"]["total"] == 0
    assert r_a["photos"]["pending"] == 0
    await worker.wait_idle()

    db.expunge_all()
    p_a = await db.scalar(
        select(Participant).where(
            Participant.conference_id == conf, Participant.external_id == "P-1"
        )
    )
    assert p_a is not None
    assert p_a.photo_path == original_path
    assert p_a.photo_sha256 == original_sha

    # (б) Ссылка изменилась -> новое фото (другой photo_sha256)
    r_b = await upload(
        c,
        conf,
        "p.xlsx",
        xlsx_bytes([[*person(1), "https://example.com/photo2.jpg"]], headers=headers),
    )
    assert r_b.status_code == 202
    await worker.wait_idle()

    report_b = (
        await c.get(f"/api/admin/conferences/{conf}/imports/{r_b.json()['batch_id']}")
    ).json()
    assert report_b["photos"]["total"] == 1
    assert report_b["photos"]["loaded"] == 1

    db.expunge_all()
    p_b = await db.scalar(
        select(Participant).where(
            Participant.conference_id == conf, Participant.external_id == "P-1"
        )
    )
    assert p_b is not None
    assert p_b.photo_sha256 != original_sha
    assert p_b.photo_path is not None

    # (в) Ссылка стала пустой -> photo_path is None, photo_sha256 is None
    r_c = await upload_report(c, conf, "p.xlsx", xlsx_bytes([[*person(1), ""]], headers=headers))
    assert r_c["photos"]["total"] == 0
    assert r_c["photos"]["pending"] == 0
    await worker.wait_idle()

    db.expunge_all()
    p_c = await db.scalar(
        select(Participant).where(
            Participant.conference_id == conf, Participant.external_id == "P-1"
        )
    )
    assert p_c is not None
    assert p_c.photo_path is None
    assert p_c.photo_sha256 is None


# 8. Устаревший результат
async def test_stale_result_not_applied(
    db: AsyncSession,
) -> None:
    conf = await active_conference(db)
    p = Participant(
        conference_id=conf,
        external_id="P-1",
        last_name="Иванов",
        first_name="Иван",
        search_norm="иванов иван",
        source_data={"photo_url": "https://new.test/y.jpg"},
    )
    db.add(p)
    await db.commit()

    applied = await save_participant_photo(db, p.id, "https://old.test/x.jpg", "x.jpg", "0" * 64)
    assert applied is False

    await db.refresh(p)
    assert p.photo_path is None
    assert p.photo_sha256 is None


# 9. Сохранённый файл — JPEG без EXIF и не больше photo_max_side_px
async def test_saved_photo_normalized_jpeg_no_exif_max_side(
    login_as: LoginAs,
    db: AsyncSession,
    worker: PhotoWorker,
    app_db: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c: StaffClient = await login_as("imports.run", "participants.view")
    conf = await active_conference(db)

    app_db.state.settings = app_db.state.settings.model_copy(update={"photo_max_side_px": 300})

    img = Image.new("RGB", (800, 400), color="yellow")
    exif_data = img.getexif()
    exif_data[0x0112] = 1  # Orientation
    exif_data[0x010E] = "Test Image Description"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif_data)
    raw_img = buf.getvalue()

    async def fake(url: str, **kwargs: Any) -> bytes:
        return raw_img

    monkeypatch.setattr("app.imports.photo_worker.fetch_photo", fake)

    headers = [*HEADERS, "Фото (ссылка)"]
    rows = [[*person(1), "https://example.com/large_exif.jpg"]]

    r = await upload(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers))
    assert r.status_code == 202
    await worker.wait_idle()

    db.expunge_all()
    p = await db.scalar(
        select(Participant).where(
            Participant.conference_id == conf, Participant.external_id == "P-1"
        )
    )
    assert p is not None
    assert p.photo_path is not None

    file_path = app_db.state.settings.photo_dir / p.photo_path
    assert file_path.is_file()

    with Image.open(file_path) as saved_img:
        assert saved_img.format == "JPEG"
        w, h = saved_img.size
        assert max(w, h) <= 300
        exif = saved_img.getexif()
        assert len(exif) == 0
        assert saved_img.info.get("exif") is None
