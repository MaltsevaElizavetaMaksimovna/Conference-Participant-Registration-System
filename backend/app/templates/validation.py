"""Проверка геометрии шаблона (PR-01): элементы внутри наклейки, предупреждения у края.

Свойства одного элемента (поле, текст, кегли) проверяет сама схема `TemplateElement`; здесь —
то, для чего нужен размер наклейки.
"""

from app.core.errors import AppError
from app.templates.schemas import TemplateElement, TemplateIn, TemplateWarning

# Допуск на округление дробных миллиметров с фронта
_EPS = 0.005


def _outside(el: TemplateElement, width: float, height: float) -> bool:
    return (
        el.x_mm < -_EPS
        or el.y_mm < -_EPS
        or el.x_mm + el.w_mm > width + _EPS
        or el.y_mm + el.h_mm > height + _EPS
    )


def check_geometry(body: TemplateIn) -> None:
    """422 `validation_error`, если элемент выходит за край; ключ ошибки — `elements.<i>`."""
    fields = {
        f"elements.{i}": f"Элемент {i + 1} выходит за край наклейки {body.width_mm:g}×"
        f"{body.height_mm:g} мм"
        for i, el in enumerate(body.elements)
        if _outside(el, body.width_mm, body.height_mm)
    }
    if fields:
        raise AppError("validation_error", "Некорректные данные запроса", 422, {"fields": fields})


def edge_warnings(
    width: float, height: float, elements: list[TemplateElement], margin_mm: float
) -> list[TemplateWarning]:
    """Элементы ближе `margin_mm` к любому краю: принтер может их обрезать."""
    warnings = []
    for i, el in enumerate(elements):
        gap = min(el.x_mm, el.y_mm, width - el.x_mm - el.w_mm, height - el.y_mm - el.h_mm)
        if gap < margin_mm - _EPS:
            warnings.append(
                TemplateWarning(
                    element=i,
                    code="near_edge",
                    message=f"Элемент {i + 1} ближе {margin_mm:g} мм к краю наклейки: "
                    "принтер может его обрезать",
                )
            )
    return warnings
