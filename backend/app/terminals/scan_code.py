"""Нормализация строки от USB-сканера QR (B2-02, TR-01, TR-07).

Сканер работает как клавиатура. Если на терминале включена русская раскладка, вместо
`https://reg.example/p?id=A1b2` в браузер приходит `реезыЖ..купюучфьзду.з,шв=Ф1и2`.
Фронт читает `event.code` и обычно присылает правильную строку, но бэкенд всё равно
исправляет раскладку: это вторая линия защиты (например, при вводе через IME).

Три шага, каждый можно вызывать отдельно:

1. `normalize_scan(raw)` — убрать мусор и перевести ЙЦУКЕН -> US QWERTY.
2. `is_badge_link(...)` — это QR с нашей наклейки (`/p/<token>`)? Такой код не регистрирует.
3. `extract_invite_id(...)` — достать идентификатор участника из ссылки приглашения.

Регистр функции не меняют. Если на сканере включён CapsLock, регистр букв инвертирован
(`A1b2` придёт как `a1B2`), и мы это не «чиним»: идентификатор может быть регистрозависимым.
TODO B2-03: искать `external_id` сначала точно, затем без учёта регистра, если совпадение
единственное.
"""

import logging
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit

log = logging.getLogger("app.scan_code")

# --- Раскладка ЙЦУКЕН (Windows) -> US QWERTY, по рядам физических клавиш -------------------
# Ряды: цифры, верхний буквенный, средний, нижний. Совпадает с таблицей из
# tools/scanner-spike (RU и CODE_TO_US в test.js); без Shift и с Shift.
_US = "`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./"
_US_SHIFT = '~!@#$%^&*()_+QWERTYUIOP{}|ASDFGHJKL:"ZXCVBNM<>?'
_RU = "ё1234567890-=йцукенгшщзхъ\\фывапролджэячсмитьбю."
_RU_SHIFT = 'Ё!"№;%:?*()_+ЙЦУКЕНГШЩЗХЪ/ФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,'

assert len(_US) == len(_RU) == 47
assert len(_US_SHIFT) == len(_RU_SHIFT) == 47

RU_TO_US: dict[int, str] = {
    ord(ru): us
    for ru, us in zip(_RU + _RU_SHIFT, _US + _US_SHIFT, strict=True)
    if ru != us  # цифры, `- = ! % * ( ) _ +` совпадают в обеих раскладках
}

# Признак русской раскладки: любая кириллица (U+0400..U+04FF) или «№» (есть только в ЙЦУКЕН)
_CYRILLIC = re.compile("[Ѐ-ӿ№]")


def normalize_scan(raw: str) -> str:
    """Строка от сканера -> строка в US-раскладке без управляющих символов.

    - Удаляет управляющие и невидимые символы (`\\r`, `\\n`, Tab, BOM, нулевой пробел),
      пробелы по краям.
    - Если в строке есть кириллица, сканер «печатал» в русской раскладке: ВСЯ строка
      переводится в US QWERTY (`Ж -> :`, `. -> /`, `, -> ?`, `ю -> .`, `" -> @`, `№ -> #`).
      Строка без кириллицы не меняется: `.` и `,` там настоящие.
    """
    cleaned = "".join(ch for ch in raw if unicodedata.category(ch) not in ("Cc", "Cf")).strip()
    if _CYRILLIC.search(cleaned):
        return cleaned.translate(RU_TO_US)
    return cleaned


# --- Ссылка с наклейки ----------------------------------------------------------------------

_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin(url: str) -> tuple[str, int | None, str] | None:
    """(host без регистра, порт, путь без хвостового `/`) или None, если это не http(s)-ссылка."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in _DEFAULT_PORTS or not host:
        return None
    if port == _DEFAULT_PORTS[parts.scheme.lower()]:
        port = None
    return host, port, parts.path.rstrip("/")


def is_badge_link(normalized: str, public_base_url: str | None) -> bool:
    """Это ссылка на профиль с нашей наклейки: `<public_base_url>/p/<token>`?

    Такой код приглашением не является (TR-07): терминал отвечает «Участник не найден».
    Сравниваются адрес и порт, схема (http/https) значения не имеет. Если
    `public_base_url` не задан, узнать ссылку нельзя и возвращается False.
    """
    if not public_base_url or not _URL.match(normalized):
        return False
    base = _origin(public_base_url.strip())
    link = _origin(normalized)
    if base is None or link is None:
        return False
    if link[:2] != base[:2]:
        return False
    prefix = f"{base[2]}/p/"
    return link[2].startswith(prefix) and len(link[2]) > len(prefix)


# --- Идентификатор участника ----------------------------------------------------------------

# Параметры, в которых ссылка приглашения может нести ID (по убыванию приоритета)
ID_QUERY_PARAMS = ("id", "participant_id", "participant", "pid", "code", "uid")
_BARE_ID = re.compile(r"[A-Za-z0-9_-]{2,64}")
_MAX_ID_LEN = 255


def _clean_id(value: str | None) -> str | None:
    value = (value or "").strip()
    if not value or len(value) > _MAX_ID_LEN:
        return None
    return value


def _id_by_pattern(normalized: str, pattern: str) -> str | None:
    try:
        match = re.search(pattern, normalized)
    except re.error:
        log.warning(
            "Некорректная регулярка ID приглашения %r, используем разбор по умолчанию", pattern
        )
        return _id_by_default(normalized)
    if match is None:
        return None
    # Первая группа = ID; регулярка без групп — весь фрагмент
    return _clean_id(match.group(1) if match.re.groups else match.group(0))


def _id_by_default(normalized: str) -> str | None:
    if not _URL.match(normalized):
        return normalized if _BARE_ID.fullmatch(normalized) else None
    try:
        parts = urlsplit(normalized)
    except ValueError:
        return None
    if parts.scheme.lower() not in _DEFAULT_PORTS:
        return None
    params: dict[str, str] = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        params.setdefault(key.lower(), value)
    for name in ID_QUERY_PARAMS:
        if name in params:
            return _clean_id(params[name])
    segments = [s for s in parts.path.split("/") if s]
    return _clean_id(unquote(segments[-1])) if segments else None


def extract_invite_id(normalized: str, pattern: str | None) -> str | None:
    """Идентификатор участника из нормализованной строки; None, если достать не удалось.

    - Задана регулярка (`RS_INVITE_ID_REGEX` или `conference.invite_id_regex`): ID — её первая
      группа (`re.search` по всей строке).
    - Иначе, для ссылки http(s): значение параметра из `ID_QUERY_PARAMS` (имя без учёта
      регистра), а если его нет — последний непустой сегмент пути.
    - Иначе (не ссылка): вся строка, если это `[A-Za-z0-9_-]{2,64}`.

    Формат реальных приглашений пока неизвестен (вопрос В-04), поэтому всё настраивается.
    """
    if not normalized:
        return None
    if pattern:
        return _id_by_pattern(normalized, pattern)
    return _id_by_default(normalized)
