import pytest

from app.core.text import full_name, normalize_search


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Иванов Иван Иванович", "иванов иван иванович"),
        ("  Королёв   Артём\tПетрович\n", "королев артем петрович"),
        ("ЁЖИКОВ ёлка", "ежиков елка"),
        ("Ivanov  Ivan", "ivanov ivan"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_search(raw: str, expected: str) -> None:
    assert normalize_search(raw) == expected


def test_normalize_is_idempotent() -> None:
    once = normalize_search("  Фёдоров   Пётр ")
    assert normalize_search(once) == once


def test_full_name() -> None:
    assert full_name("Иванов", "Иван", "Иванович") == "Иванов Иван Иванович"
    assert full_name("Иванов", "Иван", None) == "Иванов Иван"
    assert full_name(" Иванов ", "Иван", "  ") == "Иванов Иван"
    assert normalize_search(full_name("Королёв", "Артём", None)) == "королев артем"
