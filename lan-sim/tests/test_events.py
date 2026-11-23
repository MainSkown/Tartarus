"""The event schema's text handling: nothing a client sends may break the log or a report."""

import json

import pytest

from lan_sim import events
from lan_sim.limits import Limits

LIMITS = Limits()


def line_of(event_type: str, **fields) -> str:
    body = events.build_fields(event_type, LIMITS, fields)
    return json.dumps({"type": event_type, **body}, separators=(",", ":"))


@pytest.mark.parametrize(
    "hostile",
    [
        "line one\nline two",
        "carriage\rreturn",
        "nul\x00byte",
        "tab\there",
        "escape\x1b[31mred",
        "bell\x07",
        "separator\u2028here\u2029",
        "bidi \u202eoverride",
        "zero\u200bwidth",
        "delete\x7f",
        '"quotes" and \\ backslashes',
    ],
)
def test_control_and_format_characters_never_reach_the_log(hostile):
    cleaned = events.sanitize_text(hostile, 256)

    assert all(character.isprintable() for character in cleaned)
    assert "\n" not in cleaned
    assert "\x00" not in cleaned


def test_a_hostile_username_keeps_every_line_of_the_log_one_json_object():
    line = line_of(
        "login-attempt",
        user='admin\n{"type":"session-end"}\x00',
        domain="CORP",
        mechanism="password",
        secret="p\nw",
        success=False,
    )

    assert "\n" not in line
    assert json.loads(line)["user"] == 'admin{"type":"session-end"}'


def test_the_ordinary_text_of_a_name_is_kept_unchanged():
    assert events.sanitize_text("Administrator", 256) == "Administrator"
    assert events.sanitize_text("zażółć", 256) == "zażółć"


def test_invalid_utf8_from_surrogateescape_becomes_replacement_characters():
    raw = b"user\xff\xfe".decode("utf-8", "surrogateescape")

    cleaned = events.sanitize_text(raw, 256)

    assert cleaned == "user��"
    cleaned.encode("utf-8")


def test_bytes_are_decoded_with_replacement():
    assert events.sanitize_text(b"user\xff", 256) == "user�"


def test_a_log_line_is_pure_ascii_whatever_the_text():
    line = line_of("service-request", name="n\u202e\ud800", detail="d\U0001f600�")

    line.encode("ascii")
    json.loads(line)


def test_a_ten_megabyte_string_is_cut_to_the_cap_quickly():
    huge = "A" * 10_000_000

    cleaned = events.sanitize_text(huge, 256)

    assert len(cleaned) == 256
    assert cleaned.endswith("…")


def test_a_ten_megabyte_string_of_control_characters_is_cut_without_scanning_it_all():
    cleaned = events.sanitize_text("\x00" * 10_000_000, 256)

    assert cleaned == "\u2026"


def test_a_string_exactly_at_the_cap_is_not_marked_as_cut():
    assert events.sanitize_text("A" * 256, 256) == "A" * 256


def test_every_text_field_has_its_own_cap():
    fields = {
        "user": "u" * 100_000,
        "domain": "d" * 100_000,
        "mechanism": "password",
        "secret": "s" * 100_000,
        "success": True,
    }

    body = events.build_fields("login-attempt", LIMITS, fields)

    assert len(body["user"]) == LIMITS.max_identity_length
    assert len(body["domain"]) == LIMITS.max_identity_length
    assert len(body["secret"]) == LIMITS.max_secret_length


def test_a_path_and_a_detail_are_capped_at_the_path_length():
    body = events.build_fields(
        "share-access", LIMITS, {"share": "C$", "path": "p" * 100_000, "operation": "read"}
    )

    assert len(body["path"]) == LIMITS.max_path_length


def test_counts_are_clamped_to_non_negative_integers():
    body = events.build_fields(
        "connection", LIMITS, {"bytes_in": -5, "bytes_out": 10**30, "duration_ms": 7.9}
    )

    assert body["bytes_in"] == 0
    assert body["bytes_out"] == events.MAX_COUNT
    assert body["duration_ms"] == 7


def test_a_sha256_must_be_64_lowercase_hex_digits():
    ok = "a" * 64
    fields = {"share": "C$", "path": "x", "size": 1, "sha256": ok, "truncated": False}

    assert events.build_fields("file-write", LIMITS, fields)["sha256"] == ok
    for bad in ("A" * 64, "a" * 63, "zz" * 32, "a" * 64 + "\n"):
        with pytest.raises(ValueError, match="sha256"):
            events.build_fields("file-write", LIMITS, {**fields, "sha256": bad})


def test_a_mechanism_outside_the_schema_is_refused():
    fields = {"user": "u", "domain": "d", "mechanism": "kerberos", "secret": "s", "success": True}

    with pytest.raises(ValueError, match="mechanism"):
        events.build_fields("login-attempt", LIMITS, fields)


def test_flags_are_booleans():
    fields = {"user": "u", "domain": "d", "mechanism": "ntlm", "secret": "s", "success": 1}

    with pytest.raises(ValueError, match="success"):
        events.build_fields("login-attempt", LIMITS, fields)


def test_missing_and_extra_fields_are_refused():
    with pytest.raises(ValueError, match="missing"):
        events.build_fields("share-access", LIMITS, {"share": "C$", "path": "x"})
    with pytest.raises(ValueError, match="unexpected"):
        events.build_fields(
            "share-access", LIMITS, {"share": "C$", "path": "x", "operation": "read", "pid": 4}
        )


def test_an_unknown_event_type_is_refused():
    with pytest.raises(ValueError, match="event type"):
        events.build_fields("exploit", LIMITS, {})


def test_the_schema_lists_the_seven_event_types():
    assert events.EVENT_TYPES == (
        "connection",
        "login-attempt",
        "share-access",
        "file-write",
        "service-request",
        "aggregate",
        "session-end",
    )
    assert events.MECHANISMS == ("ntlm", "basic", "password", "publickey", "sql", "ldap-simple")
