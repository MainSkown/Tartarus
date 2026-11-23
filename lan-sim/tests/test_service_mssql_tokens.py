"""The reply tokens: byte-exact, and different below TDS 7.2 where the protocol changed."""

import struct

from mssql_support import TDS_71, TDS_74

from lan_sim.services.mssql_tokens import (
    done,
    env_change,
    error_message,
    login_failure,
    login_success,
    scalar_result,
    sspi_token,
)
from lan_sim.services.mssql_wire import TdsVersion

LEGACY = TdsVersion(TDS_71)
MODERN = TdsVersion(TDS_74)


def utf16(text):
    return text.encode("utf-16le")


def test_a_plain_done_has_an_eight_byte_row_count_from_tds_72():
    assert done(MODERN) == b"\xfd" + struct.pack("<HHQ", 0, 0, 0)


def test_a_plain_done_has_a_four_byte_row_count_below_tds_72():
    assert done(LEGACY) == b"\xfd" + struct.pack("<HHI", 0, 0, 0)


def test_a_done_with_rows_sets_the_count_flag_and_the_select_command():
    assert done(MODERN, rows=1) == b"\xfd" + struct.pack("<HHQ", 0x10, 0xC1, 1)
    assert done(LEGACY, rows=1) == b"\xfd" + struct.pack("<HHI", 0x10, 0xC1, 1)


def test_a_done_after_an_error_carries_the_error_bit():
    assert done(MODERN, error=True) == b"\xfd" + struct.pack("<HHQ", 0x02, 0, 0)


def test_the_done_that_answers_an_attention_carries_the_attention_bit():
    assert done(MODERN, attention=True) == b"\xfd" + struct.pack("<HHQ", 0x20, 0, 0)


def test_an_env_change_names_the_new_and_the_old_value():
    token = env_change(4, "4096", "4096")

    assert token == (
        b"\xe3"
        + struct.pack("<H", 1 + 1 + 8 + 1 + 8)
        + b"\x04"
        + b"\x04"
        + utf16("4096")
        + b"\x04"
        + utf16("4096")
    )


def test_an_error_token_has_a_four_byte_line_number_from_tds_72():
    token = error_message(MODERN, 18456, "no", "FS01")

    body = struct.pack("<IBBH", 18456, 1, 14, 2) + utf16("no") + b"\x04" + utf16("FS01") + b"\x00"
    assert token == b"\xaa" + struct.pack("<H", len(body) + 4) + body + struct.pack("<I", 1)


def test_an_error_token_has_a_two_byte_line_number_below_tds_72():
    token = error_message(LEGACY, 18456, "no", "FS01")

    body = struct.pack("<IBBH", 18456, 1, 14, 2) + utf16("no") + b"\x04" + utf16("FS01") + b"\x00"
    assert token == b"\xaa" + struct.pack("<H", len(body) + 2) + body + struct.pack("<H", 1)


def test_a_login_failure_is_the_18456_error_then_an_error_done():
    stream = login_failure(MODERN, "FS01", "sa")

    assert stream == error_message(MODERN, 18456, "Login failed for user 'sa'.", "FS01") + done(
        MODERN, error=True
    )


def test_a_successful_login_acknowledges_the_clients_tds_version_and_ends_with_done():
    for version, wire in ((LEGACY, 0x71000001), (MODERN, 0x74000004)):
        stream = login_success(version, "FS01")

        assert stream.startswith(b"\xad")
        assert struct.pack(">I", wire) in stream[:12]
        assert stream.endswith(done(version))


def test_a_successful_login_reports_the_server_version_15_0_2000():
    stream = login_success(MODERN, "FS01")

    assert b"\x0f\x00\x07\xd0" in stream
    assert utf16("Microsoft SQL Server") in stream


def test_a_successful_login_sets_the_database_and_the_packet_size():
    stream = login_success(MODERN, "FS01")

    assert env_change(1, "master", "master") in stream
    assert env_change(4, "4096", "4096") in stream
    assert utf16("Changed database context to 'master'.") in stream


def test_a_scalar_result_is_one_nvarchar_column_and_one_row():
    stream = scalar_result(MODERN, "v", "hello")

    metadata = (
        b"\x81"
        + struct.pack("<H", 1)
        + struct.pack("<IH", 0, 0x21)
        + b"\xe7"
        + struct.pack("<H", 8000)
        + b"\x09\x04\xd0\x00\x34"
        + b"\x01"
        + utf16("v")
    )
    assert stream == metadata + b"\xd1" + struct.pack("<H", 10) + utf16("hello") + done(
        MODERN, rows=1
    )


def test_a_scalar_result_has_a_two_byte_user_type_below_tds_72():
    stream = scalar_result(LEGACY, "", "x")

    assert stream[:5] == b"\x81\x01\x00\x00\x00"
    assert struct.pack("<HH", 0, 0x21) + b"\xe7" in stream
    assert stream.endswith(done(LEGACY, rows=1))


def test_a_null_value_is_the_nvarchar_null_length():
    stream = scalar_result(MODERN, "", None)

    assert b"\xd1\xff\xff" in stream


def test_a_value_longer_than_nvarchar_4000_is_cut():
    stream = scalar_result(MODERN, "", "x" * 5000)

    assert b"\xd1" + struct.pack("<H", 8000) in stream


def test_an_sspi_token_carries_its_length():
    assert sspi_token(b"abc") == b"\xed\x03\x00abc"
