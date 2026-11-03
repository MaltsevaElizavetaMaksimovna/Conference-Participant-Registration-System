"""Автотесты рендера наклейки (PR-01, PR-03, PR-04, QR-01, B2-08, B2-09)."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
import segno
from PIL import Image, ImageChops, ImageOps
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.render.data import LabelData, label_data, profile_url
from app.badges.render.label import DPI, Overflow, dots, render_label
from app.badges.render.select import template_ids, templates_for
from app.badges.render.text_fit import fit_text, tokens
from app.core.enums import BadgeType
from app.core.errors import AppError
from app.models.conference import Conference, LabelTemplate
from app.models.participant import Participant
from app.templates.schemas import TemplateElement, TemplateIn
from tests.render_samples import DATA, LONG_ORG, SAMPLES, SNAPSHOTS, T60X40, T90X50


async def _make_conference(
    db: AsyncSession,
    *,
    badge_type: str = "single",
    title: str = "Тестовая конференция",
) -> Conference:
    """Создать конференцию для проверки привязки шаблонов."""
    conf = Conference(
        title=title,
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 21),
        badge_type=badge_type,
        is_active=False,
    )
    db.add(conf)
    await db.commit()
    return conf


async def _make_template(
    db: AsyncSession,
    conference_id: int,
    kind: str,
    name: str | None = None,
) -> LabelTemplate:
    """Создать шаблон стороны наклейки."""
    tpl = LabelTemplate(
        conference_id=conference_id,
        name=name or f"{kind}-tpl",
        kind=kind,
        width_mm=Decimal("60"),
        height_mm=Decimal("40"),
    )
    db.add(tpl)
    await db.commit()
    return tpl


async def _make_participant(
    db: AsyncSession,
    conference_id: int,
    *,
    manual_fields: list[str] | None = None,
    is_manual_added: bool = False,
) -> Participant:
    """Создать участника в БД."""
    p = Participant(
        conference_id=conference_id,
        external_id=f"P-{uuid.uuid4().hex[:8]}",
        last_name="Иванов",
        first_name="Иван",
        middle_name="Иванович",
        search_norm="иванов иван иванович",
        manual_fields=manual_fields or [],
        is_manual_added=is_manual_added,
    )
    db.add(p)
    await db.commit()
    return p


def test_render_dimensions_and_mode() -> None:
    """1. Размеры наклейки в точках при 203 dpi и 1-битный режим изображения."""
    assert dots(60) == 480
    assert dots(40) == 320
    assert dots(90) == 719
    assert dots(50) == 400

    res_60 = render_label(T60X40, DATA)
    assert res_60.image.size == (480, 320)
    assert res_60.image.mode == "1"

    res_90 = render_label(T90X50, DATA)
    assert res_90.image.size == (719, 400)
    assert res_90.image.mode == "1"


def test_render_snapshots_match() -> None:
    """2. Совпадение рендера с эталонными снимками (доля расхождений <= 1%)."""
    for name, tpl in SAMPLES.items():
        rendered = render_label(tpl, DATA).image
        expected = Image.open(SNAPSHOTS / name)
        assert rendered.size == expected.size

        diff = ImageChops.difference(rendered.convert("L"), expected.convert("L"))
        different_pixels = sum(diff.histogram()[1:])
        total_pixels = expected.width * expected.height
        ratio = different_pixels / total_pixels
        assert ratio <= 0.01, f"Расхождение snapshot {name}: {ratio:.2%}"


def test_long_organization_pr03() -> None:
    """3. Организация в 120 символов в шаблоне 60×40 помещается без overflow в рамку."""
    assert len(LONG_ORG) == 120

    res = render_label(T60X40, DATA)
    assert res.overflow == []

    org_el = next(el for el in T60X40.elements if el.field == "organization")
    single_el_tpl = TemplateIn(
        name="Только организация",
        kind="front",
        width_mm=60,
        height_mm=40,
        elements=[org_el],
    )
    res_org = render_label(single_el_tpl, DATA)
    inv = ImageOps.invert(res_org.image.convert("L"))
    bbox = inv.getbbox()
    assert bbox is not None

    x1 = dots(org_el.x_mm)
    y1 = dots(org_el.y_mm)
    x2 = x1 + dots(org_el.w_mm)
    y2 = y1 + dots(org_el.h_mm)
    assert bbox[0] >= x1 and bbox[1] >= y1
    assert bbox[2] <= x2 and bbox[3] <= y2

    fitted = fit_text(
        LONG_ORG,
        box_w=dots(org_el.w_mm),
        box_h=dots(org_el.h_mm),
        font_size=org_el.font_size,
        min_font_size=org_el.min_font_size,
        max_lines=org_el.max_lines,
        bold=org_el.bold,
        dpi=DPI,
    )
    assert 1 < len(fitted.lines) <= org_el.max_lines
    assert not fitted.overflow


def test_fit_text_narrow_box_reduces_font() -> None:
    """4.1. При узкой рамке кегль уменьшается, количество строк <= max_lines."""
    text = "Научно-исследовательский институт проблем машиностроения"
    # 50×12,5 мм: кеглем 14 в три строки не влезает, меньшим — влезает
    fitted = fit_text(
        text,
        box_w=400,
        box_h=100,
        font_size=14,
        min_font_size=8,
        max_lines=3,
        bold=False,
        dpi=DPI,
    )
    assert fitted.pt < 14
    assert fitted.pt >= 8
    assert len(fitted.lines) <= 3
    assert not fitted.overflow


def test_fit_text_short_text_wide_box() -> None:
    """4.2. Короткий текст в широкой рамке сохраняет исходный кегль и одну строку."""
    fitted = fit_text(
        "Иван",
        box_w=300,
        box_h=100,
        font_size=14,
        min_font_size=8,
        max_lines=2,
        bold=False,
        dpi=DPI,
    )
    assert fitted.pt == 14
    assert len(fitted.lines) == 1
    assert fitted.overflow is False


def test_fit_text_hyphen_tokens() -> None:
    """4.3. Разбивка на токены после дефиса: вторая часть приклеена к первой."""
    toks = tokens("Петров-Водкин")
    assert toks == [("Петров-", False), ("Водкин", True)]


def test_fit_text_single_word_overflow() -> None:
    """4.4. Длинное слово при минимальном кегле разбивается посимвольно не шире рамки."""
    word = "ОченьДлинноеСловоКотороеНеПомещаетсяНиВКакуюРамкуДажеМинимальнымКеглем"
    box_w = 60
    fitted = fit_text(
        word,
        box_w=box_w,
        box_h=200,
        font_size=12,
        min_font_size=8,
        max_lines=10,
        bold=False,
        dpi=DPI,
    )
    assert fitted.overflow is True
    for line in fitted.lines:
        assert fitted.font.getlength(line) <= box_w


def test_fit_text_max_lines_overflow_ellipsis() -> None:
    """4.5. Превышение max_lines дает overflow, допустимое число строк и многоточие."""
    text = "Слишком много текста для ограничения допустимого числа строк наклейки " * 5
    box_w = 100
    max_lines = 2
    fitted = fit_text(
        text,
        box_w=box_w,
        box_h=200,
        font_size=14,
        min_font_size=8,
        max_lines=max_lines,
        bold=False,
        dpi=DPI,
    )
    assert fitted.overflow is True
    assert len(fitted.lines) == max_lines
    assert fitted.lines[-1].endswith("…")
    for line in fitted.lines:
        assert fitted.font.getlength(line) <= box_w


def test_element_overflow_stays_within_box() -> None:
    """5. Элемент с переполнением не выходит за пределы рамки и фиксирует Overflow."""
    el = TemplateElement(
        type="field",
        field="organization",
        x_mm=5,
        y_mm=5,
        w_mm=20,
        h_mm=8,
        font_size=12,
        min_font_size=8,
        max_lines=1,
    )
    tpl = TemplateIn(
        name="Маленькая рамка",
        kind="front",
        width_mm=60,
        height_mm=40,
        elements=[el],
    )
    long_text = "Очень длинное название организации, которое гарантированно не поместится"
    data = LabelData(values={"organization": long_text})
    res = render_label(tpl, data)

    assert Overflow(element=0, field="organization", value=long_text) in res.overflow

    inv = ImageOps.invert(res.image.convert("L"))
    bbox = inv.getbbox()
    assert bbox is not None

    x1 = dots(el.x_mm)
    y1 = dots(el.y_mm)
    x2 = x1 + dots(el.w_mm)
    y2 = y1 + dots(el.h_mm)
    assert bbox[0] >= x1 and bbox[1] >= y1
    assert bbox[2] <= x2 and bbox[3] <= y2


def test_label_data_formatting_and_profile_url() -> None:
    """6. Форматирование label_data, fallback _en -> ru, full_name, extra и profile_url."""
    assert profile_url("https://reg.example.ru/", "abc") == "https://reg.example.ru/p/abc"
    assert profile_url("https://reg.example.ru", "abc") == "https://reg.example.ru/p/abc"

    p = Participant(
        last_name="  Иванов  ",
        first_name="  Иван  ",
        middle_name=None,
        position="  Инженер  ",
        position_en=None,
        organization="  ООО   Ромашка  ",
        organization_en="  Romashka   LLC  ",
        extra={"role": " VIP   гость ", "num": 42},
        manual_fields=[],
        is_manual_added=False,
    )
    data = label_data(p, profile_url="https://reg.example.ru/p/abc")

    assert data.value("last_name") == "Иванов"
    assert data.value("first_name") == "Иван"
    assert data.value("full_name") == "Иванов Иван"
    assert data.value("organization") == "ООО Ромашка"
    assert data.value("position_en") == "Инженер"
    assert data.value("organization_en") == "Romashka LLC"
    assert data.value("extra.role") == "VIP гость"
    assert data.value("extra.num") == "42"
    assert data.profile_url == "https://reg.example.ru/p/abc"

    p2 = Participant(
        last_name="Сидоров",
        first_name="Петр",
        middle_name="Алексеевич",
        manual_fields=[],
        is_manual_added=False,
    )
    assert label_data(p2, None).value("full_name") == "Сидоров Петр Алексеевич"


def test_empty_fields_and_text_elements() -> None:
    """7. Пустые поля и QR без ссылки белые, элемент type='text' печатается."""
    el_org = TemplateElement(
        type="field",
        field="organization",
        x_mm=5,
        y_mm=5,
        w_mm=30,
        h_mm=10,
        font_size=12,
    )
    el_text = TemplateElement(
        type="text",
        text="Статический текст",
        x_mm=5,
        y_mm=20,
        w_mm=30,
        h_mm=10,
        font_size=12,
    )
    el_qr = TemplateElement(type="qr", x_mm=40, y_mm=5, w_mm=15, h_mm=15)
    tpl = TemplateIn(
        name="Тест пустых полей",
        kind="front",
        width_mm=60,
        height_mm=40,
        elements=[el_org, el_text, el_qr],
    )

    data = LabelData(values={"organization": ""}, profile_url=None)
    res = render_label(tpl, data)

    # Пустая организация — полностью белая
    x_org, y_org = dots(el_org.x_mm), dots(el_org.y_mm)
    w_org, h_org = dots(el_org.w_mm), dots(el_org.h_mm)
    box_org = res.image.crop((x_org, y_org, x_org + w_org, y_org + h_org))
    assert ImageOps.invert(box_org.convert("L")).getbbox() is None

    # type='text' — содержит черные пиксели
    x_txt, y_txt = dots(el_text.x_mm), dots(el_text.y_mm)
    w_txt, h_txt = dots(el_text.w_mm), dots(el_text.h_mm)
    box_txt = res.image.crop((x_txt, y_txt, x_txt + w_txt, y_txt + h_txt))
    assert ImageOps.invert(box_txt.convert("L")).getbbox() is not None

    # QR без ссылки — полностью белый
    x_qr, y_qr = dots(el_qr.x_mm), dots(el_qr.y_mm)
    w_qr, h_qr = dots(el_qr.w_mm), dots(el_qr.h_mm)
    box_qr = res.image.crop((x_qr, y_qr, x_qr + w_qr, y_qr + h_qr))
    assert ImageOps.invert(box_qr.convert("L")).getbbox() is None


def test_qr_determinism_and_module_readability() -> None:
    """8. Детерминизм QR-кода и соответствие центров модулей матрице segno."""
    el_qr = TemplateElement(type="qr", x_mm=5, y_mm=5, w_mm=30, h_mm=30)
    tpl = TemplateIn(
        name="Тест QR",
        kind="front",
        width_mm=40,
        height_mm=40,
        elements=[el_qr],
    )
    url1 = "https://reg.example.ru/p/token-123"
    url2 = "https://reg.example.ru/p/token-456"

    res1a = render_label(tpl, LabelData(profile_url=url1))
    res1b = render_label(tpl, LabelData(profile_url=url1))
    res2 = render_label(tpl, LabelData(profile_url=url2))

    # Повторная печать дает идентичное изображение, разные ссылки — разное
    assert res1a.image.tobytes() == res1b.image.tobytes()
    assert res1a.image.tobytes() != res2.image.tobytes()

    # Проверка центров модулей по матрице segno
    matrix = segno.make(url1, error="m", boost_error=False).matrix
    quiet_modules = 2
    n = len(matrix) + 2 * quiet_modules
    box_x = dots(el_qr.x_mm)
    box_y = dots(el_qr.y_mm)
    box_w = dots(el_qr.w_mm)
    box_h = dots(el_qr.h_mm)

    crop_qr = res1a.image.crop((box_x, box_y, box_x + box_w, box_y + box_h)).convert("L")
    module = min(box_w, box_h) // n
    assert module >= 1

    side = n * module
    x0 = (box_w - side) // 2
    y0 = (box_h - side) // 2

    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            center_x = x0 + (c + quiet_modules) * module + module // 2
            center_y = y0 + (r + quiet_modules) * module + module // 2
            expected_color = 0 if dark else 255
            assert crop_qr.getpixel((center_x, center_y)) == expected_color


def test_select_template_ids() -> None:
    """9.1. Выбор идентификаторов сторон для template_ids."""
    conf_none = Conference(
        badge_type=BadgeType.NONE,
        front_template_id=1,
        back_template_id=2,
    )
    assert template_ids(conf_none, data_changed=False) == []
    assert template_ids(conf_none, data_changed=True) == []

    conf_single = Conference(
        badge_type=BadgeType.SINGLE,
        front_template_id=10,
        changed_template_id=20,
    )
    assert template_ids(conf_single, data_changed=False) == [("front", 10)]
    assert template_ids(conf_single, data_changed=True) == [("changed", 20)]

    conf_double = Conference(
        badge_type=BadgeType.DOUBLE,
        front_template_id=10,
        back_template_id=30,
        changed_template_id=20,
        changed_back_template_id=40,
    )
    assert template_ids(conf_double, data_changed=False) == [("front", 10), ("back", 30)]
    assert template_ids(conf_double, data_changed=True) == [("changed", 20), ("changed_back", 40)]

    conf_double_fallback = Conference(
        badge_type=BadgeType.DOUBLE,
        front_template_id=10,
        back_template_id=30,
        changed_template_id=20,
        changed_back_template_id=None,
    )
    assert template_ids(conf_double_fallback, data_changed=True) == [
        ("changed", 20),
        ("changed_back", 30),
    ]


async def test_templates_for_none(db: AsyncSession) -> None:
    """9.2. Для badge_type='none' список шаблонов пуст."""
    conf = await _make_conference(db, badge_type="none")
    p = await _make_participant(db, conf.id)
    assert await templates_for(db, p, conf) == []


async def test_templates_for_single_and_double(db: AsyncSession) -> None:
    """9.3. Выбор шаблонов для single и double при неизмененных данных."""
    conf = await _make_conference(db, badge_type="single")
    front = await _make_template(db, conf.id, "front")
    conf.front_template_id = front.id
    await db.commit()

    p = await _make_participant(db, conf.id)
    assert await templates_for(db, p, conf) == [front]

    back = await _make_template(db, conf.id, "back")
    conf.badge_type = "double"
    conf.back_template_id = back.id
    await db.commit()
    assert await templates_for(db, p, conf) == [front, back]


async def test_templates_for_changed_participant(db: AsyncSession) -> None:
    """9.4. Для участника с ручными правками или добавленного вручную выбирается changed."""
    conf = await _make_conference(db, badge_type="double")
    front = await _make_template(db, conf.id, "front")
    back = await _make_template(db, conf.id, "back")
    changed = await _make_template(db, conf.id, "changed")
    changed_back = await _make_template(db, conf.id, "changed_back")

    conf.front_template_id = front.id
    conf.back_template_id = back.id
    conf.changed_template_id = changed.id
    conf.changed_back_template_id = None
    await db.commit()

    p_manual = await _make_participant(db, conf.id, manual_fields=["last_name"])
    assert await templates_for(db, p_manual, conf) == [changed, back]

    conf.changed_back_template_id = changed_back.id
    await db.commit()

    p_added = await _make_participant(db, conf.id, is_manual_added=True)
    assert await templates_for(db, p_added, conf) == [changed, changed_back]


async def test_templates_for_missing_template_raises_app_error(db: AsyncSession) -> None:
    """9.5. Отсутствие необходимого шаблона вызывает AppError 409 template_not_set."""
    conf = await _make_conference(db, badge_type="single")
    p = await _make_participant(db, conf.id)

    with pytest.raises(AppError) as exc_front:
        await templates_for(db, p, conf)
    assert exc_front.value.code == "template_not_set"
    assert exc_front.value.status_code == 409
    assert exc_front.value.details == {"side": "front"}

    front = await _make_template(db, conf.id, "front")
    conf.badge_type = "double"
    conf.front_template_id = front.id
    conf.back_template_id = None
    await db.commit()

    with pytest.raises(AppError) as exc_back:
        await templates_for(db, p, conf)
    assert exc_back.value.code == "template_not_set"
    assert exc_back.value.status_code == 409
    assert exc_back.value.details == {"side": "back"}

    p_changed = await _make_participant(db, conf.id, manual_fields=["last_name"])
    conf.badge_type = "single"
    conf.changed_template_id = None
    await db.commit()

    with pytest.raises(AppError) as exc_changed:
        await templates_for(db, p_changed, conf)
    assert exc_changed.value.code == "template_not_set"
    assert exc_changed.value.status_code == 409
    assert exc_changed.value.details == {"side": "changed"}

    changed = await _make_template(db, conf.id, "changed")
    conf.badge_type = "double"
    conf.changed_template_id = changed.id
    conf.back_template_id = None
    conf.changed_back_template_id = None
    await db.commit()

    with pytest.raises(AppError) as exc_changed_back:
        await templates_for(db, p_changed, conf)
    assert exc_changed_back.value.code == "template_not_set"
    assert exc_changed_back.value.status_code == 409
    assert exc_changed_back.value.details == {"side": "changed_back"}
