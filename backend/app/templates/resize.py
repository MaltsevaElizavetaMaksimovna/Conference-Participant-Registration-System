"""Подгонка шаблона наклейки под другую ленту (PR-05)."""

from app.templates.schemas import TemplateElement, TemplateIn

MIN_READABLE_PT = 6.0  # ниже 6 pt на 203 dpi не читается (прогон на принтере XP-360B)


def resize_spec(spec: TemplateIn, width_mm: float, height_mm: float) -> TemplateIn:
    """Новый шаблон того же содержания под ленту width_mm × height_mm (PR-05)."""
    sx = width_mm / spec.width_mm
    sy = height_mm / spec.height_mm
    k = min(sx, sy)

    new_elements: list[TemplateElement] = []
    for el in spec.elements:
        x = max(0.0, round(el.x_mm * sx, 1))
        if round(x + 0.1, 6) > width_mm:
            x = max(0.0, round(width_mm - 0.1, 1))

        y = max(0.0, round(el.y_mm * sy, 1))
        if round(y + 0.1, 6) > height_mm:
            y = max(0.0, round(height_mm - 0.1, 1))

        w = max(0.1, round(el.w_mm * sx, 1))
        if round(x + w, 6) > width_mm:
            w = max(0.1, round(width_mm - x, 1))
            if round(x + w, 6) > width_mm and w > 0.1:
                w = max(0.1, round(w - 0.1, 1))

        h = max(0.1, round(el.h_mm * sy, 1))
        if round(y + h, 6) > height_mm:
            h = max(0.1, round(height_mm - y, 1))
            if round(y + h, 6) > height_mm and h > 0.1:
                h = max(0.1, round(h - 0.1, 1))

        font_size = max(MIN_READABLE_PT, round(el.font_size * k * 2) / 2)
        min_font_size = min(font_size, max(MIN_READABLE_PT, round(el.min_font_size * k * 2) / 2))

        new_elements.append(
            TemplateElement(
                type=el.type,
                field=el.field,
                text=el.text,
                x_mm=x,
                y_mm=y,
                w_mm=w,
                h_mm=h,
                font_size=font_size,
                min_font_size=min_font_size,
                max_lines=el.max_lines,
                align=el.align,
                bold=el.bold,
            )
        )

    return TemplateIn(
        name=spec.name,
        kind=spec.kind,
        width_mm=width_mm,
        height_mm=height_mm,
        gap_mm=spec.gap_mm,
        elements=new_elements,
    )
