"""What a SQL batch or RPC request gets back: canned scalars, and the text capped for the log."""

import struct
from dataclasses import replace

import pytest
from mssql_support import HOST, all_headers

from lan_sim.services.mssql_sql import (
    ScalarAnswer,
    answer_for,
    batch_text,
    rpc_procedure,
    sql_banner,
)

USER = "sa"


def answer(text, user=USER):
    return answer_for(text, HOST, user)


def test_the_banner_is_sql_server_2019_standard_on_the_hosts_os():
    banner = sql_banner(HOST)

    assert banner.startswith("Microsoft SQL Server 2019 (RTM) - 15.0.2000.5 (X64)")
    assert "Standard Edition (64-bit) on Windows Server 2019 Standard 10.0 <X64>" in banner
    assert "(Build 17763: )" in banner


def test_an_os_banner_without_a_build_number_is_used_as_it_is():
    banner = sql_banner(replace(HOST, os_banner="Windows"))

    assert "Standard Edition (64-bit) on Windows <X64>" in banner
    assert "(Build" not in banner


@pytest.mark.parametrize(
    "text",
    [
        "select @@version",
        "SELECT @@VERSION",
        "  select\t@@version  ",
        "select\r\n@@version;",
        "SELECT @@version;  ",
    ],
)
def test_select_at_at_version_answers_the_banner_with_no_column_name(text):
    assert answer(text) == ScalarAnswer("", sql_banner(HOST))


@pytest.mark.parametrize(
    ("text", "column"),
    [
        ("select @@version as v", "v"),
        ("select @@version v", "v"),
        ("SELECT @@VERSION AS [My Col]", "My Col"),
        ("select @@version as ver;", "ver"),
    ],
)
def test_a_trailing_alias_names_the_column(text, column):
    assert answer(text) == ScalarAnswer(column, sql_banner(HOST))


def test_other_scalar_functions_answer_one_row_each():
    assert answer("select db_name()") == ScalarAnswer("", "master")
    assert answer("SELECT DB_NAME ( )") == ScalarAnswer("", "master")
    assert answer("select suser_name()", "alice") == ScalarAnswer("", "alice")
    assert answer("select @@servername") == ScalarAnswer("", "FS01")


def test_server_properties_are_answered_or_null():
    assert answer("select serverproperty('ProductVersion')") == ScalarAnswer("", "15.0.2000.5")
    assert answer("select SERVERPROPERTY(N'MachineName')") == ScalarAnswer("", "FS01")
    assert answer("select serverproperty('Edition')") == ScalarAnswer(
        "", "Standard Edition (64-bit)"
    )
    assert answer("select serverproperty('InstanceName')") == ScalarAnswer("", None)
    assert answer("select serverproperty('NoSuchThing')") == ScalarAnswer("", None)


@pytest.mark.parametrize(
    "text",
    [
        "select 1",
        "exec xp_cmdshell 'whoami'",
        "select @@version; drop table x",
        "select @@version as 1bad",
        "select @@version as [a]]b",
        "",
        "select * from sys.databases",
        "select @@version" + " " * 5000 + "x",
    ],
)
def test_everything_else_has_no_rows(text):
    assert answer(text) is None


def test_a_batch_text_skips_the_all_headers_block():
    payload = all_headers() + "select 1".encode("utf-16le")

    assert batch_text(payload) == "select 1"


def test_a_batch_text_without_a_headers_block_is_decoded_whole():
    assert batch_text("select 1".encode("utf-16le")) == "select 1"


def test_a_batch_text_is_capped_and_survives_odd_bytes_and_bad_surrogates():
    assert len(batch_text(b"a\x00" * 100_000)) == 4000
    assert batch_text(b"a\x00b") == "a"
    assert "�" in batch_text(b"\x00\xd8a\x00")


def test_an_rpc_with_a_name_yields_the_name():
    name = "sp_executesql".encode("utf-16le")
    payload = all_headers() + struct.pack("<H", 13) + name + b"\x00\x00"

    assert rpc_procedure(payload) == "sp_executesql"


def test_an_rpc_with_a_well_known_id_yields_its_name():
    payload = all_headers() + struct.pack("<HH", 0xFFFF, 10) + b"\x00\x00"

    assert rpc_procedure(payload) == "sp_executesql"
    assert rpc_procedure(struct.pack("<HH", 0xFFFF, 13)) == "sp_prepexec"


def test_an_rpc_with_an_unknown_id_is_named_by_number():
    assert rpc_procedure(struct.pack("<HH", 0xFFFF, 99)) == "procedure id 99"


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\x01",
        struct.pack("<H", 500) + b"ab",
        struct.pack("<H", 0xFFFF) + b"\x01",
        b"\xff" * 3,
    ],
)
def test_a_truncated_rpc_has_no_name(payload):
    assert rpc_procedure(payload) is None


def test_an_rpc_name_is_capped():
    payload = struct.pack("<H", 0x7FFF) + ("a" * 0x7FFF).encode("utf-16le")

    assert rpc_procedure(payload) is None
