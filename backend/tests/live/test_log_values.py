from datetime import datetime

import pytest

from app.live.log_values import (
    clock_text,
    filetime_to_datetime,
    hex_word,
    render_argument,
    render_return,
    render_text,
)


@pytest.mark.parametrize(
    ("raw", "tag", "expected"),
    [
        (5, None, "5"),
        (0, None, "0"),
        (-1, None, "18446744073709551615"),
        (-2, None, "18446744073709551614"),
        (2**40, None, str(2**40)),
        (0x22C, "p", "0x0000022c"),
        (0, "h", "0x00000000"),
        (2**40 + 5, "p", "0x10000000005"),
        (0x7FFD9FE38838, "p", "0x7ffd9fe38838"),
        (-1, "p", "0xffffffff"),
        (-1, "h", "0xffffffff"),
        (7, "unknown-tag", "7"),
        (b"abc", None, "abc"),
        (b"", None, ""),
        (b"C:\\Windows\\cmd.exe", None, "C:\\Windows\\cmd.exe"),
        (b"a\x00b", None, "a\\x00b"),
        (b"\xff\x01", None, "\\xff\\x01"),
        ("caf\u00e9".encode(), None, "caf\\xe9"),
        (b"line\r\nnext\ttab", None, "line\r\nnext\ttab"),
        ("a\x01", None, "a\\x01"),
        (None, None, ""),
        (1.5, None, "1.5"),
        (True, None, "1"),
        ([b"a", b"b"], None, "a b"),
        ([1, 2], None, "1 2"),
    ],
)
def test_renders_an_argument_the_way_the_report_does(raw: object, tag: str | None, expected: str):
    assert render_argument(raw, tag) == expected


def test_pointer_tag_on_a_text_value_falls_back_to_text() -> None:
    assert render_argument(b"name", "p") == "name"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, "0x00000000"),
        (1, "0x00000001"),
        (0xC0000034, "0xc0000034"),
        (-1, "0xffffffffffffffff"),
        (-1073741772, "0xffffffffc0000034"),
        (2**33, "0x200000000"),
        (b"text\x00", "text\\x00"),
    ],
)
def test_renders_a_return_value(raw: object, expected: str) -> None:
    assert render_return(raw) == expected


def test_hex_word_pads_to_eight_digits_and_wraps_negatives_to_64_bits() -> None:
    assert hex_word(0x1F) == "0x0000001f"
    assert hex_word(-1) == "0x" + "f" * 16


def test_render_text_decodes_utf8_then_falls_back_to_one_char_per_byte() -> None:
    assert render_text(b"ok") == "ok"
    assert render_text(b"\xc3\xa9") == "\\xe9"
    assert render_text(b"\xe9") == "\\xe9"


def test_clock_text_has_milliseconds_after_a_comma() -> None:
    assert clock_text(datetime(2026, 10, 13, 15, 39, 50, 393999)) == "2026-10-13 15:39:50,393"
    assert clock_text(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02 03:04:05,000"


def test_filetime_counts_hundred_nanosecond_ticks_from_1601() -> None:
    assert filetime_to_datetime(0xD53E8000, 0x019DB1DE) == datetime(1970, 1, 1)


def test_filetime_of_a_real_process_start_truncates_below_the_microsecond() -> None:
    # pid 9708 of analysis 45, whose report says first_seen 2026-10-13 13:39:50,393
    assert filetime_to_datetime(1375613491, 31283992) == datetime(2026, 10, 13, 13, 39, 50, 393912)


def test_filetime_wraps_negative_halves_like_unsigned_words() -> None:
    assert filetime_to_datetime(-0x2AC18000, 0x019DB1DE) == datetime(1970, 1, 1)
