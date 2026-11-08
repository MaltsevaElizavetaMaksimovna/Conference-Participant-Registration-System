"""Автотесты изменения размера шаблона наклейки под новую ленту (PR-05)."""

import io
from typing import Any

import pytest
from PIL import Image

from app.templates.resize import MIN_READABLE_PT, resize_spec
from app.templates.schemas import TemplateElement, TemplateIn
from app.templates.validation import check_geometry
from tests.conftest import LoginAs
from tests.test_templates import (
    SAMPLE_TEMPLATE,
    create_conf,
    error_info,
    manager,
    templates_url,
)


def _base_template() -> TemplateIn:
    """Базовый тестовый шаблон 60x40 мм."""
    return TemplateIn(
        name="Лицевая сторона",
        kind="front",
        width_mm=60.0,
        height_mm=40.0,
        gap_mm=2.0,
        elements=[
            TemplateElement(
                type="field",
                field="last_name",
                x_mm=6.0,
                y_mm=4.0,
                w_mm=50.0,
                h_mm=10.0,
                font_size=14.0,
                min_font_size=8.0,
                max_lines=2,
                align="left",
                bold=True,
            ),
            TemplateElement(
                type="qr",
                x_mm=40.0,
                y_mm=20.0,
                w_mm=14.0,
                h_mm=14.0,
            ),
        ],
    )


# 1. Чистая функция: шаблон 60x40 -> 30x20
def test_resize_spec_half_size() -> None:
    """60x40 -> 30x20: ровно вдвое, кегли не ниже MIN_READABLE_PT, исходный объект неизменен."""
    spec = _base_template()
    copy_spec = spec.model_copy(deep=True)

    res = resize_spec(spec, 30.0, 20.0)

    # Исходный объект не изменился
    assert spec == copy_spec

    # Размеры шаблона изменились, общие поля сохранились
    assert res.width_mm == 30.0
    assert res.height_mm == 20.0
    assert res.name == spec.name
    assert res.kind == spec.kind
    assert res.gap_mm == spec.gap_mm
    assert len(res.elements) == len(spec.elements)

    # Первый элемент: ровно вдвое меньше
    el0 = res.elements[0]
    assert el0.x_mm == 3.0
    assert el0.y_mm == 2.0
    assert el0.w_mm == 25.0
    assert el0.h_mm == 5.0
    assert el0.font_size == 7.0
    assert el0.min_font_size == 6.0  # 8 * 0.5 = 4, но не меньше 6.0 pt
    assert el0.max_lines == 2
    assert el0.field == "last_name"
    assert el0.align == "left"
    assert el0.bold is True

    # Второй элемент: QR
    el1 = res.elements[1]
    assert el1.x_mm == 20.0
    assert el1.y_mm == 10.0
    assert el1.w_mm == 7.0
    assert el1.h_mm == 7.0
    assert el1.type == "qr"


# 2. 60x40 -> 90x60
def test_resize_spec_enlarge_1_5x() -> None:
    """Шаблон 60x40 -> 90x60: всё в 1.5 раза больше, кегль 14 -> 21.0."""
    spec = TemplateIn(
        name="Лицевая",
        kind="front",
        width_mm=60.0,
        height_mm=40.0,
        gap_mm=2.0,
        elements=[
            TemplateElement(
                type="field",
                field="last_name",
                x_mm=4.0,
                y_mm=6.0,
                w_mm=40.0,
                h_mm=12.0,
                font_size=14.0,
                min_font_size=8.0,
            ),
        ],
    )

    res = resize_spec(spec, 90.0, 60.0)

    assert res.width_mm == 90.0
    assert res.height_mm == 60.0
    el = res.elements[0]
    assert el.x_mm == 6.0
    assert el.y_mm == 9.0
    assert el.w_mm == 60.0
    assert el.h_mm == 18.0
    assert el.font_size == 21.0
    assert el.min_font_size == 12.0


# 3. Непропорционально 60x40 -> 58x40
def test_resize_spec_anisotropic_58x40() -> None:
    """Непропорционально 60x40 -> 58x40: x, w * 58/60, y, h без изменений, кегль 14 -> 13.5."""
    spec = TemplateIn(
        name="Лицевая",
        kind="front",
        width_mm=60.0,
        height_mm=40.0,
        gap_mm=2.0,
        elements=[
            TemplateElement(
                type="field",
                field="last_name",
                x_mm=6.0,
                y_mm=10.0,
                w_mm=48.0,
                h_mm=15.0,
                font_size=14.0,
                min_font_size=8.0,
            ),
        ],
    )

    res = resize_spec(spec, 58.0, 40.0)

    el = res.elements[0]
    assert el.x_mm == 5.8
    assert el.y_mm == 10.0
    assert el.w_mm == 46.4
    assert el.h_mm == 15.0
    # k = min(58/60, 40/40) = 58/60; round(14 * 58/60 * 2) / 2 = 13.5
    assert el.font_size == 13.5
    assert el.min_font_size == 7.5


# 4. Каждый элемент внутри наклейки на разных размерах и min_font_size <= font_size
@pytest.mark.parametrize(
    ("target_w", "target_h"),
    [
        (58.0, 40.0),
        (57.0, 30.0),
        (100.0, 70.0),
        (30.0, 20.0),
        (40.0, 60.0),
        (200.0, 200.0),
        (10.0, 10.0),
    ],
)
def test_elements_stay_inside_boundaries(target_w: float, target_h: float) -> None:
    """После масштабирования все элементы строго внутри наклейки, min_font_size <= font_size."""
    spec = TemplateIn(
        name="Граничный тест",
        kind="front",
        width_mm=60.0,
        height_mm=40.0,
        gap_mm=2.0,
        elements=[
            # Элемент в центре
            TemplateElement(
                type="field",
                field="last_name",
                x_mm=5.0,
                y_mm=5.0,
                w_mm=50.0,
                h_mm=10.0,
                font_size=14.0,
                min_font_size=8.0,
            ),
            # Элемент на всю наклейку
            TemplateElement(
                type="field",
                field="organization",
                x_mm=0.0,
                y_mm=0.0,
                w_mm=60.0,
                h_mm=40.0,
                font_size=16.0,
                min_font_size=6.0,
            ),
            # Элемент в правом нижнем углу
            TemplateElement(
                type="qr",
                x_mm=45.0,
                y_mm=25.0,
                w_mm=15.0,
                h_mm=15.0,
            ),
            # Элемент с мелким шрифтом
            TemplateElement(
                type="text",
                text="Постоянная надпись",
                x_mm=2.0,
                y_mm=35.0,
                w_mm=20.0,
                h_mm=4.0,
                font_size=7.0,
                min_font_size=6.0,
            ),
        ],
    )

    res = resize_spec(spec, target_w, target_h)

    # Проверка геометрии встроенным валидатором модуля
    check_geometry(res)

    for el in res.elements:
        assert el.x_mm >= 0.0
        assert el.y_mm >= 0.0
        assert el.w_mm >= 0.1
        assert el.h_mm >= 0.1
        assert round(el.x_mm + el.w_mm, 6) <= target_w + 0.005
        assert round(el.y_mm + el.h_mm, 6) <= target_h + 0.005
        assert el.min_font_size <= el.font_size
        assert el.font_size >= MIN_READABLE_PT
        assert el.min_font_size >= MIN_READABLE_PT


# 5. API: POST .../resize
async def test_api_resize_template(login_as: LoginAs) -> None:
    """POST .../resize меняет размеры и элементы, version растёт; GET отдаёт новый шаблон."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    created = (await c.post(url, json=SAMPLE_TEMPLATE)).json()
    assert created["version"] == 1
    assert created["width_mm"] == 60.0
    assert created["height_mm"] == 40.0

    r = await c.post(f"{url}/{created['id']}/resize", json={"width_mm": 58, "height_mm": 40})
    assert r.status_code == 200, r.text
    resized: dict[str, Any] = r.json()

    assert resized["id"] == created["id"]
    assert resized["width_mm"] == 58.0
    assert resized["height_mm"] == 40.0
    assert resized["version"] == 2
    assert resized["elements"] != created["elements"]
    assert resized["elements"][0]["w_mm"] == round(50 * 58 / 60, 1)

    # GET шаблона возвращает обновлённые данные
    r_get = await c.get(f"{url}/{created['id']}")
    assert r_get.status_code == 200, r_get.text
    fetched: dict[str, Any] = r_get.json()
    assert fetched["width_mm"] == 58.0
    assert fetched["height_mm"] == 40.0
    assert fetched["version"] == 2
    assert fetched["elements"] == resized["elements"]


# 6. Предпросмотр после resize (GET .../preview.png)
async def test_preview_dimensions_after_resize(login_as: LoginAs) -> None:
    """Предпросмотр после resize отдаёт PNG размера 58x40 мм в точках при 203 DPI."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    tpl = (await c.post(url, json=SAMPLE_TEMPLATE)).json()
    r_resize = await c.post(f"{url}/{tpl['id']}/resize", json={"width_mm": 58, "height_mm": 40})
    assert r_resize.status_code == 200

    r_preview = await c.get(f"{url}/{tpl['id']}/preview.png")
    assert r_preview.status_code == 200
    assert r_preview.headers["content-type"] == "image/png"

    img = Image.open(io.BytesIO(r_preview.content))
    expected_width = round(58 * 203 / 25.4)
    expected_height = round(40 * 203 / 25.4)
    assert img.size == (expected_width, expected_height)


# 7. Ошибки: 404, 422, 403
async def test_resize_errors(login_as: LoginAs) -> None:
    """Проверка ошибок 404 template/conf, 422 validation_error, 403 без прав."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])
    tpl = (await c.post(url, json=SAMPLE_TEMPLATE)).json()

    # Шаблона нет -> 404 template_not_found
    r_no_tpl = await c.post(f"{url}/999999/resize", json={"width_mm": 58, "height_mm": 40})
    assert r_no_tpl.status_code == 404
    code, _ = error_info(r_no_tpl)
    assert code == "template_not_found"

    # Конференции нет -> 404 conference_not_found
    r_no_conf = await c.post(
        "/api/admin/conferences/999999/templates/1/resize",
        json={"width_mm": 58, "height_mm": 40},
    )
    assert r_no_conf.status_code == 404
    code, _ = error_info(r_no_conf)
    assert code == "conference_not_found"

    # width_mm: 0 -> 422 validation_error
    r_zero_w = await c.post(f"{url}/{tpl['id']}/resize", json={"width_mm": 0, "height_mm": 40})
    assert r_zero_w.status_code == 422
    code, _ = error_info(r_zero_w)
    assert code == "validation_error"

    # width_mm: 250 -> 422 validation_error
    r_huge_w = await c.post(f"{url}/{tpl['id']}/resize", json={"width_mm": 250, "height_mm": 40})
    assert r_huge_w.status_code == 422
    code, _ = error_info(r_huge_w)
    assert code == "validation_error"

    # height_mm: 0 -> 422 validation_error
    r_zero_h = await c.post(f"{url}/{tpl['id']}/resize", json={"width_mm": 58, "height_mm": 0})
    assert r_zero_h.status_code == 422
    code, _ = error_info(r_zero_h)
    assert code == "validation_error"

    # height_mm: 250 -> 422 validation_error
    r_huge_h = await c.post(f"{url}/{tpl['id']}/resize", json={"width_mm": 58, "height_mm": 250})
    assert r_huge_h.status_code == 422
    code, _ = error_info(r_huge_h)
    assert code == "validation_error"

    # Без разрешения (participants.view) -> 403
    viewer = await login_as("participants.view")
    r_perm = await viewer.post(f"{url}/{tpl['id']}/resize", json={"width_mm": 58, "height_mm": 40})
    assert r_perm.status_code == 403
