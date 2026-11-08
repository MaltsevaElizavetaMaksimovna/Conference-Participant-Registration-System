"""Образцы для snapshot-тестов рендера наклейки (B2-08): шаблоны 60×40 и 90×50 мм.

Пересоздать эталоны после осознанного изменения рендера:
    python -m tests.render_samples
и посмотреть PNG глазами перед коммитом.
"""

from pathlib import Path

from app.badges.render.data import SAMPLE, LabelData
from app.badges.render.label import render_label, to_png
from app.templates.schemas import TemplateElement as E
from app.templates.schemas import TemplateIn

SNAPSHOTS = Path(__file__).resolve().parent / "snapshots"

# Организация ровно в 120 символов (PR-03)
LONG_ORG = (
    "Федеральное государственное бюджетное образовательное учреждение высшего образования "
    "«Научно-исследовательский университет»"
)[:120]

DATA = LabelData(values={**SAMPLE.values, "organization": LONG_ORG}, profile_url=SAMPLE.profile_url)

T60X40 = TemplateIn(
    name="Лицевая 60×40",
    kind="front",
    width_mm=60,
    height_mm=40,
    elements=[
        E(
            type="field",
            field="full_name",
            x_mm=3,
            y_mm=3,
            w_mm=54,
            h_mm=11,
            font_size=14,
            min_font_size=8,
            max_lines=2,
            bold=True,
        ),
        E(
            type="field",
            field="organization",
            x_mm=3,
            y_mm=15,
            w_mm=36,
            h_mm=21,
            font_size=11,
            min_font_size=6,
            max_lines=5,
        ),
        E(type="qr", x_mm=40, y_mm=17, w_mm=17, h_mm=17),
    ],
)

T90X50 = TemplateIn(
    name="Оборот 90×50",
    kind="back",
    width_mm=90,
    height_mm=50,
    elements=[
        E(
            type="text",
            text="Инновации-2026",
            x_mm=3,
            y_mm=3,
            w_mm=84,
            h_mm=6,
            font_size=10,
            align="center",
        ),
        E(
            type="field",
            field="last_name_en",
            x_mm=3,
            y_mm=10,
            w_mm=60,
            h_mm=9,
            font_size=20,
            min_font_size=10,
            bold=True,
        ),
        E(type="field", field="first_name_en", x_mm=3, y_mm=19, w_mm=60, h_mm=7, font_size=14),
        E(
            type="field",
            field="organization",
            x_mm=3,
            y_mm=27,
            w_mm=60,
            h_mm=20,
            font_size=12,
            min_font_size=7,
            max_lines=4,
        ),
        E(type="qr", x_mm=65, y_mm=25, w_mm=22, h_mm=22),
    ],
)

SAMPLES = {"label_60x40.png": T60X40, "label_90x50.png": T90X50}


if __name__ == "__main__":
    SNAPSHOTS.mkdir(exist_ok=True)
    for name, tpl in SAMPLES.items():
        (SNAPSHOTS / name).write_bytes(to_png(render_label(tpl, DATA).image))
        print(SNAPSHOTS / name)
