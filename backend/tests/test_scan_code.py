"""Нормализация отсканированного кода (B2-02, TR-01, TR-07)."""

import httpx
import pytest
from fastapi import FastAPI

from app.terminals.scan_code import (
    RU_TO_US,
    extract_invite_id,
    is_badge_link,
    normalize_scan,
)
from tests.conftest import Devices

# Эталоны получены из tools/scanner-spike/test.js (restoreFromKeys при раскладке RU):
# что «увидел» браузер, если сканер печатал в русской раскладке.
RU_URL = "реезыЖ..купюучфьзду.з,шв=Ф1и2"  # https://reg.example/p?id=A1b2
ROUNDTRIP = [
    ("https://reg.example/p?id=A1b2", RU_URL),
    (
        "https://reg.example/invite/Zq9-x_T.k?id=A1b2&t=%7B1%7D#frag",
        "реезыЖ..купюучфьзду.штмшеу.Яй9-ч_Еюл,шв=Ф1и2?е=%7И1%7В№акфп",
    ),
    (
        "http://localhost:8080/p/AbCdEf0123456789?x=1+2&y=[a]|b~c`d\\e\"f'g<h>i,j;k@l!m$n^o*p(q)r{s}",
        'реезЖ..дщсфдрщыеЖ8080.з.ФиСвУа0123456789,ч=1+2?н=хфъ/иЁсёв\\уЭаэпБрЮшбожл"д!ь;т:щ*з(й)кХыЪ',
    ),
    ("B24-1001", "И24-1001"),
    ("AbCdEf0123456789", "ФиСвУа0123456789"),
    (  # все 94 печатных символа ASCII
        "!\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`"
        "abcdefghijklmnopqrstuvwxyz{|}~",
        '!Э№;%?э()*+б-ю.0123456789ЖжБ=Ю,"ФИСВУАПРШОЛДЬТЩЗЙКЫЕГМЦЧНЯх\\ъ:_'
        "ёфисвуапршолдьтщзйкыегмцчняХ/ЪЁ",
    ),
]


# ------------------------------------------------------------------ normalize_scan


@pytest.mark.parametrize(("expected", "typed"), ROUNDTRIP)
def test_russian_layout_is_restored(expected: str, typed: str) -> None:
    assert normalize_scan(typed) == expected


def test_example_from_task() -> None:
    assert normalize_scan(RU_URL) == "https://reg.example/p?id=A1b2"


@pytest.mark.parametrize(
    ("ru", "us"),
    [
        ("Ж", ":"),
        ("ж", ";"),
        (".", "/"),
        (",", "?"),
        ("ю", "."),
        ("б", ","),
        ("Ю", ">"),
        ("Б", "<"),
        ('"', "@"),
        ("№", "#"),
        (";", "$"),
        (":", "^"),
        ("?", "&"),
        ("э", "'"),
        ("Э", '"'),
        ("х", "["),
        ("ъ", "]"),
        ("Х", "{"),
        ("Ъ", "}"),
        ("ё", "`"),
        ("Ё", "~"),
        ("/", "|"),
        ("\\", "\\"),
        ("Й", "Q"),
        ("я", "z"),
    ],
)
def test_punctuation_keys(ru: str, us: str) -> None:
    # Перед знаком — русская буква «ф» (клавиша A), иначе раскладку не распознать
    assert normalize_scan("ф" + ru) == "a" + us


def test_table_has_no_collisions() -> None:
    # Разные русские символы не должны давать одну и ту же клавишу
    targets = [ch for ru, ch in RU_TO_US.items() if chr(ru) != ch]
    assert len(targets) == len(set(targets))


def test_english_layout_is_unchanged() -> None:
    url = "https://reg.example/p?id=A1b2&x=1,2;3"
    assert normalize_scan(url) == url


def test_no_cyrillic_means_no_translation() -> None:
    # Без единой русской буквы точки и запятые настоящие (запятая не станет «?»)
    assert normalize_scan("123.45,67") == "123.45,67"
    assert normalize_scan("B24-1001") == "B24-1001"


def test_capslock_english_is_not_fixed() -> None:
    # CapsLock меняет регистр букв: функция его не «чинит», идентификатор может быть
    # регистрозависимым. TODO B2-03: искать external_id точно, затем без учёта регистра,
    # если совпадение единственное.
    caps = "HTTPS://REG.EXAMPLE/P?ID=a1B2"
    assert normalize_scan(caps) == caps
    assert extract_invite_id(caps, None) == "a1B2"  # не A1b2


def test_capslock_russian_keeps_letters_case_and_loses_letter_punctuation() -> None:
    # При CapsLock + русской раскладке клавиши ж/э/х/ъ/б/ю приходят в обратном регистре,
    # а это уже другие знаки (Ж = «:», ж = «;»): ссылка не восстановится. Это известное
    # ограничение, надёжно здесь помогает только `event.code` на фронте.
    typed = "РЕЕЗЫж..КУПЮУЧФЬЗДУ.З,ШВ=ф1И2"
    assert normalize_scan(typed) == "HTTPS;//REG>EXAMPLE/P?ID=a1B2"
    assert extract_invite_id(normalize_scan(typed), None) is None


def test_whitespace_and_control_characters_are_removed() -> None:
    assert normalize_scan("  https://reg.example/p?id=A1b2\r\n") == "https://reg.example/p?id=A1b2"
    assert normalize_scan("\thttps://reg.example/p?id=A1b2\t\r\n\r\n") == (
        "https://reg.example/p?id=A1b2"
    )
    assert normalize_scan("﻿\x00B24-\t1001\x1b​") == "B24-1001"
    assert normalize_scan("\n" + RU_URL + "\r\n") == "https://reg.example/p?id=A1b2"


def test_empty_input() -> None:
    assert normalize_scan("") == ""
    assert normalize_scan("   \r\n\t ") == ""
    assert extract_invite_id("", None) is None
    assert extract_invite_id("", r"id=(\d+)") is None
    assert not is_badge_link("", "https://reg.example.ru")


# ------------------------------------------------------------------- is_badge_link

BASE = "https://reg.example.ru"


@pytest.mark.parametrize(
    "link",
    [
        "https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4",
        "http://reg.example.ru/p/Zk3x9QnS7Vb2LmT4",
        "HTTPS://REG.EXAMPLE.RU/p/Zk3x9QnS7Vb2LmT4",
        "https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4/",
        "https://reg.example.ru:443/p/Zk3x9QnS7Vb2LmT4",
        "https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4?utm=1",
    ],
)
def test_badge_link_detected(link: str) -> None:
    assert is_badge_link(link, BASE)
    assert is_badge_link(link, BASE + "/")


@pytest.mark.parametrize(
    "link",
    [
        "https://reg.example.ru/p/",
        "https://reg.example.ru/p",
        "https://reg.example.ru/invite/Zk3x9QnS7Vb2LmT4",
        "https://other.example.ru/p/Zk3x9QnS7Vb2LmT4",
        "https://reg.example.ru:8443/p/Zk3x9QnS7Vb2LmT4",
        "ftp://reg.example.ru/p/Zk3x9QnS7Vb2LmT4",
        "Zk3x9QnS7Vb2LmT4",
        "/p/Zk3x9QnS7Vb2LmT4",
    ],
)
def test_other_links_are_not_badge_links(link: str) -> None:
    assert not is_badge_link(link, BASE)


def test_badge_link_from_russian_layout() -> None:
    # https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4, набранная в русской раскладке
    typed = "реезыЖ..купюучфьздуюкг.з.Ял3ч9ЙтЫ7Ми2ДьЕ4"
    link = normalize_scan(typed)
    assert link == "https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4"
    assert is_badge_link(link, BASE)


def test_badge_link_needs_public_base_url() -> None:
    link = "https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4"
    assert not is_badge_link(link, None)
    assert not is_badge_link(link, "")


def test_badge_link_with_path_in_base_url() -> None:
    base = "https://example.ru/reg"
    assert is_badge_link("https://example.ru/reg/p/Zk3x", base)
    assert not is_badge_link("https://example.ru/p/Zk3x", base)


# ------------------------------------------------------------------ extract_invite_id


@pytest.mark.parametrize(
    ("normalized", "expected"),
    [
        ("https://reg.example/p?id=A1b2", "A1b2"),
        ("https://reg.example/p?ID=A1b2", "A1b2"),
        ("https://reg.example/p?Participant_ID=42", "42"),
        ("https://reg.example/p?participant=42", "42"),
        ("https://reg.example/p?pid=42&x=1", "42"),
        ("https://reg.example/p?x=1&code=C-77", "C-77"),
        ("https://reg.example/p?uid=u_9", "u_9"),
        ("https://reg.example/p?code=zzz&id=123", "123"),  # приоритет по списку
        ("https://reg.example/p?id=&pid=5", "5"),  # пустое значение пропускается
        ("https://reg.example/invite/B24-1001", "B24-1001"),
        ("https://reg.example/invite/B24-1001/", "B24-1001"),
        ("https://reg.example/invite/B24-1001?utm=1#top", "B24-1001"),
        ("https://reg.example/p/Zk3x9QnS7Vb2LmT4", "Zk3x9QnS7Vb2LmT4"),
        ("https://reg.example/p?id=%D0%98-1", "И-1"),
        ("http://localhost:8080/api/p/17", "17"),
    ],
)
def test_default_extraction_from_url(normalized: str, expected: str) -> None:
    assert extract_invite_id(normalized, None) == expected


@pytest.mark.parametrize(
    "normalized",
    [
        "https://other.example",
        "https://other.example/",
        "https://other.example/?id=",
        "https://other.example/?x=1&y=2",
        "ftp://other.example/file",
        "javascript:alert(1)",
        "mailto:a@b.c",
        "https://",
        "http://[bad",
    ],
)
def test_link_without_id_gives_none(normalized: str) -> None:
    assert extract_invite_id(normalized, None) is None


@pytest.mark.parametrize(
    ("normalized", "expected"),
    [
        ("B24-1001", "B24-1001"),
        ("A1b2", "A1b2"),
        ("ab", "ab"),
        ("a_b-9", "a_b-9"),
        ("a" * 64, "a" * 64),
        ("a", None),
        ("a" * 65, None),
        ("abc def", None),
        ("a/b", None),
        ("www.example.com/x", None),
        ("123.0", None),
    ],
)
def test_default_extraction_from_bare_string(normalized: str, expected: str | None) -> None:
    assert extract_invite_id(normalized, None) == expected


def test_very_long_id_is_rejected() -> None:
    assert extract_invite_id("https://reg.example/p?id=" + "9" * 300, None) is None


def test_custom_pattern_first_group_is_id() -> None:
    pattern = r"/invite/([A-Z0-9-]+)"
    assert extract_invite_id("https://b24.example/invite/B24-1001?x=1", pattern) == "B24-1001"
    assert extract_invite_id("https://b24.example/other/B24-1001", pattern) is None
    # пользовательская регулярка важнее разбора по умолчанию
    assert extract_invite_id("https://b24.example/invite/abc?id=1", pattern) is None
    assert extract_invite_id("https://b24.example/x?uid=55&id=1", r"[?&]uid=(\d+)") == "55"


def test_custom_pattern_without_group_uses_whole_match() -> None:
    assert extract_invite_id("https://b24.example/i/B24-1001", r"B24-\d+") == "B24-1001"


def test_custom_pattern_empty_group_is_none() -> None:
    assert extract_invite_id("https://b24.example/?id=", r"id=(\d*)") is None


def test_invalid_pattern_falls_back_to_default() -> None:
    assert extract_invite_id("B24-1001", "(") == "B24-1001"
    assert extract_invite_id("https://reg.example/p?id=7", "(") == "7"


def test_empty_pattern_means_default() -> None:
    assert extract_invite_id("B24-1001", "") == "B24-1001"
    assert extract_invite_id("B24-1001", None) == "B24-1001"


def test_full_chain_from_russian_layout() -> None:
    assert extract_invite_id(normalize_scan(RU_URL), None) == "A1b2"
    assert extract_invite_id(normalize_scan("И24-1001\r\n"), None) == "B24-1001"


# ------------------------------------------------------- POST /api/terminal/scan (заглушка)


async def _scan(client: httpx.AsyncClient, token: str, raw: str) -> httpx.Response:
    return await client.post(
        "/api/terminal/scan", headers={"Authorization": f"Terminal {token}"}, json={"raw": raw}
    )


async def test_scan_endpoint_understands_russian_layout(
    db_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, token = await devices.terminal()
    r = await _scan(db_client, token, RU_URL + "\r\n")
    assert r.status_code == 200
    assert r.json()["result"] == "found"


async def test_scan_endpoint_unparsable_code_is_not_found(
    db_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, token = await devices.terminal()
    for raw in ("https://other.example", "!!!", "https://other.example/?id="):
        r = await _scan(db_client, token, raw)
        assert r.status_code == 200, raw
        assert r.json()["result"] == "not_found", raw
        assert r.json()["message"] == "Участник не найден. Обратитесь к стойке регистрации"


async def test_scan_endpoint_badge_link_is_not_found(
    app: FastAPI, db_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, token = await devices.terminal()
    link = "https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4"
    # адрес системы не задан: ссылку не узнать, дальше работает заглушка
    assert (await _scan(db_client, token, link)).json()["result"] == "found"

    app.state.settings = app.state.settings.model_copy(
        update={"public_base_url": "https://reg.example.ru"}
    )
    assert (await _scan(db_client, token, link)).json()["result"] == "not_found"
    # то же самое, набранное в русской раскладке
    typed = "реезыЖ..купюучфьздуюкг.з.Ял3ч9ЙтЫ7Ми2ДьЕ4"
    assert (await _scan(db_client, token, typed)).json()["result"] == "not_found"
    # приглашение на том же домене, но не на /p/ — не наклейка
    r = await _scan(db_client, token, "https://reg.example.ru/invite/777")
    assert r.json()["result"] == "found"


async def test_scan_endpoint_uses_configured_regex(
    app: FastAPI, db_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, token = await devices.terminal()
    app.state.settings = app.state.settings.model_copy(update={"invite_id_regex": r"/invite/(\d+)"})
    assert (await _scan(db_client, token, "https://b24.example/invite/777")).json()[
        "result"
    ] == "found"
    assert (await _scan(db_client, token, "https://b24.example/x?id=777")).json()[
        "result"
    ] == "not_found"
