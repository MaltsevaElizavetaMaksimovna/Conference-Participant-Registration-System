"""Тесты рендера заданий печати (B2-11, TR-04, PR-04, ER-02, QR-01)."""

import base64
import io
import itertools
from decimal import Decimal

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.render.data import SAMPLE, label_data, profile_url
from app.badges.render.label import render_label, to_png
from app.core.config import Settings
from app.core.enums import PrintJobKind
from app.core.errors import AppError
from app.models.conference import LabelTemplate
from app.models.device import Printer
from app.models.participant import BadgeToken
from app.models.printing import PrintJob
from app.printing.job_render import render_job
from app.templates.schemas import TemplateElement
from app.templates.service import template_spec
from tests.registration_helpers import make_conference, make_participant

_seq = itertools.count(1)


def _unique_token() -> str:
    return f"tok-test-{next(_seq)}-123456789"


def _unique_name(prefix: str = "Принтер") -> str:
    return f"{prefix} {next(_seq)}"


def _unique_ext_id(prefix: str = "P") -> str:
    return f"{prefix}-{next(_seq)}"


def _default_elements() -> list[dict[str, object]]:
    return [
        TemplateElement(
            type="field",
            field="last_name",
            x_mm=5,
            y_mm=5,
            w_mm=50,
            h_mm=10,
        ).model_dump(mode="json"),
        TemplateElement(
            type="qr",
            x_mm=40,
            y_mm=20,
            w_mm=15,
            h_mm=15,
        ).model_dump(mode="json"),
    ]


async def _create_template(
    db: AsyncSession,
    conference_id: int,
    *,
    name: str = "Лицевая",
    kind: str = "front",
    width_mm: float = 60.0,
    height_mm: float = 40.0,
    gap_mm: float = 2.0,
    elements: list[dict[str, object]] | None = None,
) -> LabelTemplate:
    tpl = LabelTemplate(
        conference_id=conference_id,
        name=name,
        kind=kind,
        width_mm=Decimal(str(width_mm)),
        height_mm=Decimal(str(height_mm)),
        gap_mm=Decimal(str(gap_mm)),
        elements=_default_elements() if elements is None else elements,
    )
    db.add(tpl)
    await db.commit()
    return tpl


async def _create_printer(
    db: AsyncSession,
    name: str | None = None,
    dpi: int = 203,
) -> Printer:
    printer = Printer(name=name or _unique_name(), dpi=dpi)
    db.add(printer)
    await db.commit()
    return printer


@pytest.fixture
def print_settings(database_url: str) -> Settings:
    return Settings(
        env="test",
        database_url=database_url,
        public_base_url="https://reg.example.ru",
    )


async def test_single_sided_first_print(db: AsyncSession, print_settings: Settings) -> None:
    conf = await make_conference(db, badge_type="single")
    tpl = await _create_template(db, conf.id, kind="front", width_mm=60, height_mm=40, gap_mm=2)
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, _unique_ext_id(), last_name="Иванов", first_name="Иван")
    token = BadgeToken(participant_id=p.id, token=_unique_token(), status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db, dpi=203)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=token.id,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    copies = await render_job(db, print_settings, job, printer)
    assert len(copies) == 1
    copy = copies[0]
    assert copy.width_mm == 60.0
    assert copy.height_mm == 40.0
    assert copy.gap_mm == 2.0

    raw = base64.b64decode(copy.png_base64)
    img = Image.open(io.BytesIO(raw))
    assert img.format == "PNG"
    assert img.size == (480, 320)


async def test_double_sided_print_order(db: AsyncSession, print_settings: Settings) -> None:
    conf = await make_conference(db, badge_type="double")
    tpl_front = await _create_template(
        db, conf.id, name=_unique_name("Лицо"), kind="front", width_mm=60, height_mm=40
    )
    tpl_back = await _create_template(
        db, conf.id, name=_unique_name("Оборот"), kind="back", width_mm=58, height_mm=40
    )
    conf.front_template_id = tpl_front.id
    conf.back_template_id = tpl_back.id
    await db.commit()

    p = await make_participant(db, conf, _unique_ext_id())
    token = BadgeToken(participant_id=p.id, token=_unique_token(), status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=2,
        badge_token_id=token.id,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    copies = await render_job(db, print_settings, job, printer)
    assert len(copies) == 2
    assert copies[0].width_mm == 60.0
    assert copies[1].width_mm == 58.0


async def test_changed_template_when_data_modified(
    db: AsyncSession, print_settings: Settings
) -> None:
    conf = await make_conference(db, badge_type="single")
    tpl_front = await _create_template(
        db, conf.id, name=_unique_name("Лицо"), kind="front", width_mm=60, height_mm=40
    )
    tpl_changed = await _create_template(
        db, conf.id, name=_unique_name("Изменено"), kind="changed", width_mm=65, height_mm=40
    )
    conf.front_template_id = tpl_front.id
    conf.changed_template_id = tpl_changed.id
    await db.commit()

    p = await make_participant(db, conf, _unique_ext_id(), last_name="Сидоров")
    p.manual_fields = ["last_name"]
    token = BadgeToken(participant_id=p.id, token=_unique_token(), status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=token.id,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    copies = await render_job(db, print_settings, job, printer)
    assert len(copies) == 1
    assert copies[0].width_mm == 65.0


async def test_changed_template_not_set_raises_error(
    db: AsyncSession, print_settings: Settings
) -> None:
    conf = await make_conference(db, badge_type="single")
    tpl_front = await _create_template(
        db, conf.id, name=_unique_name("Лицо"), kind="front", width_mm=60, height_mm=40
    )
    conf.front_template_id = tpl_front.id
    conf.changed_template_id = None
    await db.commit()

    p = await make_participant(db, conf, _unique_ext_id())
    p.manual_fields = ["last_name"]
    token = BadgeToken(participant_id=p.id, token=_unique_token(), status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=token.id,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    with pytest.raises(AppError) as exc_info:
        await render_job(db, print_settings, job, printer)
    assert exc_info.value.code == "template_not_set"
    assert exc_info.value.status_code == 409
    assert exc_info.value.details == {"side": "changed"}


async def test_qr_byte_exact_match(db: AsyncSession, print_settings: Settings) -> None:
    conf = await make_conference(db, badge_type="single")
    tpl = await _create_template(db, conf.id, kind="front", width_mm=60, height_mm=40)
    conf.front_template_id = tpl.id
    await db.commit()

    token_val = _unique_token()
    p = await make_participant(
        db, conf, _unique_ext_id(), last_name="Кузнецов", first_name="Алексей"
    )
    token = BadgeToken(participant_id=p.id, token=token_val, status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db, dpi=203)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=token.id,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    spec = template_spec(tpl)
    expected_url = f"https://reg.example.ru/p/{token_val}"
    data = label_data(p, expected_url)
    expected_png = to_png(render_label(spec, data, dpi=203).image, 203)

    copies = await render_job(db, print_settings, job, printer)
    actual_png = base64.b64decode(copies[0].png_base64)
    assert actual_png == expected_png


async def test_printer_dpi_300(db: AsyncSession, print_settings: Settings) -> None:
    conf = await make_conference(db, badge_type="single")
    tpl = await _create_template(db, conf.id, kind="front", width_mm=60, height_mm=40)
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, _unique_ext_id())
    token = BadgeToken(participant_id=p.id, token=_unique_token(), status="active")
    db.add(token)
    await db.commit()

    printer_300 = await _create_printer(db, dpi=300)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer_300.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=token.id,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    copies = await render_job(db, print_settings, job, printer_300)
    img = Image.open(io.BytesIO(base64.b64decode(copies[0].png_base64)))
    expected_w = round(60 * 300 / 25.4)
    expected_h = round(40 * 300 / 25.4)
    assert img.size == (expected_w, expected_h)


async def test_error_public_base_url_not_set(db: AsyncSession, database_url: str) -> None:
    settings_no_url = Settings(env="test", database_url=database_url, public_base_url=None)
    conf = await make_conference(db, badge_type="single")
    tpl = await _create_template(db, conf.id, kind="front")
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, _unique_ext_id())
    token = BadgeToken(participant_id=p.id, token=_unique_token(), status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=token.id,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    with pytest.raises(AppError) as exc_info:
        await render_job(db, settings_no_url, job, printer)
    assert exc_info.value.code == "public_base_url_not_set"
    assert exc_info.value.status_code == 409


async def test_error_badge_token_missing(db: AsyncSession, print_settings: Settings) -> None:
    conf = await make_conference(db, badge_type="single")
    tpl = await _create_template(db, conf.id, kind="front")
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, _unique_ext_id())
    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=None,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    with pytest.raises(AppError) as exc_info:
        await render_job(db, print_settings, job, printer)
    assert exc_info.value.code == "badge_token_missing"
    assert exc_info.value.status_code == 409


async def test_error_badge_type_none(db: AsyncSession, print_settings: Settings) -> None:
    conf = await make_conference(db, badge_type="none")
    p = await make_participant(db, conf, _unique_ext_id())
    token = BadgeToken(participant_id=p.id, token=_unique_token(), status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=token.id,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    with pytest.raises(AppError) as exc_info:
        await render_job(db, print_settings, job, printer)
    assert exc_info.value.code == "no_badge"
    assert exc_info.value.status_code == 409


async def test_test_print_without_participant(db: AsyncSession, print_settings: Settings) -> None:
    conf = await make_conference(db)
    tpl = await _create_template(db, conf.id, kind="front", width_mm=60, height_mm=40)
    printer = await _create_printer(db)

    job = PrintJob(
        conference_id=conf.id,
        participant_id=None,
        printer_id=printer.id,
        kind=PrintJobKind.TEST,
        sides=1,
        template_id=tpl.id,
        status="pending",
    )
    db.add(job)
    await db.commit()

    copies = await render_job(db, print_settings, job, printer)
    assert len(copies) == 1
    expected_spec = template_spec(tpl)
    expected_png = to_png(render_label(expected_spec, SAMPLE, dpi=203).image, 203)
    assert base64.b64decode(copies[0].png_base64) == expected_png


async def test_test_print_with_participant_no_token(
    db: AsyncSession, print_settings: Settings
) -> None:
    conf = await make_conference(db)
    tpl = await _create_template(db, conf.id, kind="front", width_mm=60, height_mm=40)
    p = await make_participant(db, conf, _unique_ext_id(), last_name="Николаев")
    printer = await _create_printer(db)

    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.TEST,
        sides=1,
        template_id=tpl.id,
        status="pending",
    )
    db.add(job)
    await db.commit()

    copies = await render_job(db, print_settings, job, printer)
    assert len(copies) == 1
    expected_spec = template_spec(tpl)
    expected_data = label_data(p, SAMPLE.profile_url)
    expected_png = to_png(render_label(expected_spec, expected_data, dpi=203).image, 203)
    assert base64.b64decode(copies[0].png_base64) == expected_png


async def test_test_print_with_participant_and_active_token(
    db: AsyncSession, print_settings: Settings
) -> None:
    conf = await make_conference(db)
    tpl = await _create_template(db, conf.id, kind="front", width_mm=60, height_mm=40)
    p = await make_participant(db, conf, _unique_ext_id(), last_name="Фёдоров")
    token_val = _unique_token()
    token = BadgeToken(participant_id=p.id, token=token_val, status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.TEST,
        sides=1,
        template_id=tpl.id,
        status="pending",
    )
    db.add(job)
    await db.commit()

    copies = await render_job(db, print_settings, job, printer)
    assert len(copies) == 1
    expected_spec = template_spec(tpl)
    expected_url = profile_url(print_settings.public_base_url, token_val)
    expected_data = label_data(p, expected_url)
    expected_png = to_png(render_label(expected_spec, expected_data, dpi=203).image, 203)
    assert base64.b64decode(copies[0].png_base64) == expected_png


async def test_test_print_missing_template_id(db: AsyncSession, print_settings: Settings) -> None:
    conf = await make_conference(db)
    printer = await _create_printer(db)

    job = PrintJob(
        conference_id=conf.id,
        participant_id=None,
        printer_id=printer.id,
        kind=PrintJobKind.TEST,
        sides=1,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    with pytest.raises(AppError) as exc_info:
        await render_job(db, print_settings, job, printer)
    assert exc_info.value.code == "template_not_set"
    assert exc_info.value.status_code == 409
    assert exc_info.value.details == {"side": "test"}


async def test_render_does_not_create_badge_token(
    db: AsyncSession, print_settings: Settings
) -> None:
    conf = await make_conference(db, badge_type="single")
    tpl = await _create_template(db, conf.id, kind="front")
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, _unique_ext_id())
    token = BadgeToken(participant_id=p.id, token=_unique_token(), status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=token.id,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    count_before = await db.scalar(
        select(func.count()).select_from(BadgeToken).where(BadgeToken.participant_id == p.id)
    )
    await render_job(db, print_settings, job, printer)
    count_after = await db.scalar(
        select(func.count()).select_from(BadgeToken).where(BadgeToken.participant_id == p.id)
    )
    assert count_before == count_after == 1

    p_no_tok = await make_participant(db, conf, _unique_ext_id())
    test_job = PrintJob(
        conference_id=conf.id,
        participant_id=p_no_tok.id,
        printer_id=printer.id,
        kind=PrintJobKind.TEST,
        sides=1,
        template_id=tpl.id,
        status="pending",
    )
    db.add(test_job)
    await db.commit()

    await render_job(db, print_settings, test_job, printer)
    count_no_tok = await db.scalar(
        select(func.count()).select_from(BadgeToken).where(BadgeToken.participant_id == p_no_tok.id)
    )
    assert count_no_tok == 0


async def test_active_token_lookup_when_badge_token_id_none(
    db: AsyncSession, print_settings: Settings
) -> None:
    conf = await make_conference(db, badge_type="single")
    tpl = await _create_template(db, conf.id, kind="front")
    conf.front_template_id = tpl.id
    await db.commit()

    p = await make_participant(db, conf, _unique_ext_id())
    token = BadgeToken(participant_id=p.id, token=_unique_token(), status="active")
    db.add(token)
    await db.commit()

    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=p.id,
        printer_id=printer.id,
        kind=PrintJobKind.REPRINT,
        sides=1,
        badge_token_id=None,
        template_id=None,
        status="pending",
    )
    db.add(job)
    await db.commit()

    copies = await render_job(db, print_settings, job, printer)
    assert len(copies) == 1


async def test_participant_not_found(db: AsyncSession, print_settings: Settings) -> None:
    conf = await make_conference(db, badge_type="single")
    printer = await _create_printer(db)
    job = PrintJob(
        conference_id=conf.id,
        participant_id=999999,
        printer_id=printer.id,
        kind=PrintJobKind.FIRST,
        sides=1,
        badge_token_id=None,
        template_id=None,
        status="pending",
    )
    # Задание не сохраняем: внешний ключ не даст сослаться на несуществующего участника
    with pytest.raises(AppError) as exc_info:
        await render_job(db, print_settings, job, printer)
    assert exc_info.value.code == "participant_not_found"
    assert exc_info.value.status_code == 404
