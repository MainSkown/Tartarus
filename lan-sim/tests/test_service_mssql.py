"""The MSSQL service on a fed connection: what it answers and what it logs, byte for byte."""

import struct
from contextlib import suppress

import pytest
from impacket import ntlm as impacket_ntlm
from impacket import spnego as impacket_spnego
from mssql_support import (
    ATTENTION,
    HOST,
    RPC,
    SSPI,
    TDS_71,
    TDS_72,
    TDS_73,
    TDS_74,
    FakeClock,
    all_headers,
    batch_packet,
    login7_packet,
    messages,
    packet,
    prelogin_request,
    run_rig,
)

from lan_sim.ntlm import challenge_message, spnego_challenge
from lan_sim.service import PeerClosed
from lan_sim.services.mssql import SERVICE, MssqlService
from lan_sim.services.mssql_sql import sql_banner
from lan_sim.services.mssql_tokens import (
    done,
    login_failure,
    login_success,
    scalar_result,
    sspi_token,
)
from lan_sim.services.mssql_wire import TdsVersion, prelogin_response

CHALLENGE = bytes(range(1, 9))
V74 = TdsVersion(TDS_74)


def converse(data, service=SERVICE, **limits):
    async def body(rig):
        with suppress(PeerClosed):
            await service.serve(rig.connection)

    _, rig = run_rig(data, body, **limits)
    return rig


def fixed_challenge_service():
    return MssqlService(random_source=lambda size: CHALLENGE[:size])


def test_the_module_exports_the_mssql_service():
    assert SERVICE.kind == "mssql"


def test_a_prelogin_is_answered_with_the_prelogin_reply():
    rig = converse(prelogin_request())

    assert messages(rig.writer.written) == [prelogin_response()]
    assert rig.events("login-attempt") == []


@pytest.mark.parametrize("version", [TDS_71, TDS_72, TDS_73, TDS_74])
def test_a_sql_login_with_any_password_is_accepted_and_queries_are_answered(version):
    layout = TdsVersion(version)
    data = prelogin_request()
    data += login7_packet(version=version, user="sa", password="hunter2")
    data += batch_packet("select @@version")

    rig = converse(data)

    assert messages(rig.writer.written) == [
        prelogin_response(),
        login_success(layout, "FS01"),
        scalar_result(layout, "", sql_banner(HOST)),
    ]
    [login] = rig.events("login-attempt")
    assert (login["user"], login["domain"], login["mechanism"]) == ("sa", "", "sql")
    assert (login["secret"], login["success"]) == ("hunter2", True)
    [request] = rig.events("service-request")
    assert (request["name"], request["detail"]) == ("sql batch", "select @@version")


def test_a_login_without_a_prelogin_is_served():
    rig = converse(login7_packet(user="sa", password="x") + batch_packet("select 1"))

    assert messages(rig.writer.written) == [login_success(V74, "FS01"), done(V74)]


def test_a_batch_without_all_headers_is_read_too():
    data = login7_packet(version=TDS_71) + batch_packet("select @@version", headers=False)

    rig = converse(data)

    legacy = TdsVersion(TDS_71)
    assert messages(rig.writer.written)[-1] == scalar_result(legacy, "", sql_banner(HOST))


def test_an_empty_user_is_refused_with_error_18456_and_the_connection_ends():
    data = login7_packet(user="", password="x") + batch_packet("select @@version")

    rig = converse(data)

    assert messages(rig.writer.written) == [login_failure(V74, "FS01", "")]
    [login] = rig.events("login-attempt")
    assert (login["user"], login["mechanism"], login["success"]) == ("", "sql", False)
    assert rig.events("service-request") == []


def test_a_dangerous_statement_is_logged_and_answered_with_a_bare_done():
    text = "EXEC xp_cmdshell 'whoami /all'"
    rig = converse(login7_packet() + batch_packet(text))

    assert messages(rig.writer.written)[-1] == done(V74)
    [request] = rig.events("service-request")
    assert (request["name"], request["detail"]) == ("sql batch", text)


def test_the_logged_statement_is_cut_to_500_characters_and_has_no_control_characters():
    text = "select '\x01\x1b[31m" + chr(0x202E) + "a" * 2000
    rig = converse(login7_packet() + batch_packet(text))

    [request] = rig.events("service-request")
    assert 0 < len(request["detail"]) <= 500
    assert all(ord(character) >= 0x20 for character in request["detail"])
    assert all(ord(character) >= 0x20 for line in rig.sink.lines for character in line)


def test_a_statement_with_an_alias_names_the_column():
    rig = converse(login7_packet() + batch_packet("select @@version as v"))

    assert messages(rig.writer.written)[-1] == scalar_result(V74, "v", sql_banner(HOST))


def test_suser_name_echoes_the_login():
    rig = converse(login7_packet(user="alice") + batch_packet("select suser_name()"))

    assert messages(rig.writer.written)[-1] == scalar_result(V74, "", "alice")


def test_an_rpc_request_is_named_in_the_log_and_answered_with_done():
    name = "sp_executesql".encode("utf-16le")
    body = all_headers() + struct.pack("<H", 13) + name + b"\x00\x00"

    rig = converse(login7_packet() + packet(RPC, body))

    assert messages(rig.writer.written)[-1] == done(V74)
    [request] = rig.events("service-request")
    assert (request["name"], request["detail"]) == ("sql rpc", "sp_executesql")


def test_an_rpc_with_an_unreadable_name_is_still_answered():
    rig = converse(login7_packet() + packet(RPC, b"\x01"))

    assert messages(rig.writer.written)[-1] == done(V74)
    assert rig.events("service-request")[0]["detail"] == ""


def test_an_attention_is_acknowledged_with_a_done_carrying_the_attention_bit():
    rig = converse(login7_packet() + packet(ATTENTION))

    assert messages(rig.writer.written)[-1] == done(V74, attention=True)


def test_many_requests_on_one_connection_are_all_answered():
    data = login7_packet() + b"".join(batch_packet("select 1") for _ in range(50))

    rig = converse(data)

    assert len(messages(rig.writer.written)) == 51


@pytest.mark.parametrize(
    "data",
    [
        packet(0x03 + 0x10, b"x"),
        login7_packet() + login7_packet(),
        login7_packet() + prelogin_request(),
        prelogin_request() + prelogin_request(),
        prelogin_request() + batch_packet("select 1"),
        packet(0x10, b"\x00" * 40),
        login7_packet(version=0x75000000),
        packet(0x12, b"\x00"),
        batch_packet("select 1"),
    ],
)
def test_a_malformed_or_out_of_order_message_is_logged_and_ends_the_connection(data):
    rig = converse(data)

    [request] = rig.events("service-request")
    assert request["name"] == "malformed tds"


# --- integrated security ----------------------------------------------------------------------


def negotiate_blob():
    return impacket_ntlm.getNTLMSSPType1("WS01", "CORP").getData()


def spnego_negotiate_blob():
    init = impacket_spnego.SPNEGO_NegTokenInit()
    init["MechTypes"] = [
        impacket_spnego.TypesMech["NTLMSSP - Microsoft NTLM Security Support Provider"]
    ]
    init["MechToken"] = negotiate_blob()
    return init.getData()


def authenticate_blob(user, password, domain="CORP"):
    type1 = impacket_ntlm.getNTLMSSPType1("WS01", domain)
    challenge = challenge_message(HOST, CHALLENGE, FakeClock())
    type3, _ = impacket_ntlm.getNTLMSSPType3(type1, challenge, user, password, domain)
    return type3.getData()


def integrated_login(sspi=None):
    return login7_packet(integrated=True, user="", password="", sspi=sspi or negotiate_blob())


def test_an_integrated_login_is_answered_with_the_ntlm_challenge_in_an_sspi_token():
    rig = converse(integrated_login(), service=fixed_challenge_service())

    expected = challenge_message(HOST, CHALLENGE, FakeClock())
    assert messages(rig.writer.written) == [sspi_token(expected)]


def test_a_spnego_wrapped_negotiate_gets_a_spnego_wrapped_challenge():
    rig = converse(integrated_login(spnego_negotiate_blob()), service=fixed_challenge_service())

    expected = spnego_challenge(challenge_message(HOST, CHALLENGE, FakeClock()))
    assert messages(rig.writer.written) == [sspi_token(expected)]


def test_the_authenticate_is_logged_as_a_hashcat_line_and_the_login_is_refused():
    data = integrated_login() + packet(SSPI, authenticate_blob("Administrator", "wrong"))
    data += batch_packet("select @@version")

    rig = converse(data, service=fixed_challenge_service())

    _, refusal = messages(rig.writer.written)
    assert refusal == login_failure(V74, "FS01", "CORP\\Administrator")
    [login] = rig.events("login-attempt")
    assert (login["user"], login["domain"], login["mechanism"]) == ("Administrator", "CORP", "ntlm")
    assert login["success"] is False
    assert login["secret"].startswith("Administrator::CORP:0102030405060708:")
    assert rig.events("service-request") == []


def test_a_correct_ntlm_response_is_logged_as_verified_but_still_refused():
    data = integrated_login() + packet(SSPI, authenticate_blob("Administrator", "Welcome1"))

    rig = converse(data, service=fixed_challenge_service())

    assert messages(rig.writer.written)[-1] == login_failure(V74, "FS01", "CORP\\Administrator")
    [login] = rig.events("login-attempt")
    assert login["success"] is True


def test_an_integrated_login_that_is_not_ntlm_is_refused_and_logged_without_material():
    rig = converse(integrated_login(b"\x60\x82\x01\x00not ntlm"))

    assert messages(rig.writer.written) == [login_failure(V74, "FS01", "")]
    [login] = rig.events("login-attempt")
    assert (login["mechanism"], login["secret"], login["success"]) == ("ntlm", "", False)


@pytest.mark.parametrize("second", [b"junk", b"NTLMSSP\x00\x03\x00\x00\x00", b""])
def test_a_garbage_authenticate_ends_the_connection_without_a_login_record(second):
    data = integrated_login() + packet(SSPI, second)

    rig = converse(data, service=fixed_challenge_service())

    assert rig.events("service-request")[0]["name"] == "malformed tds"
    assert rig.events("login-attempt") == []


def test_a_batch_where_the_authenticate_was_due_ends_the_connection():
    rig = converse(integrated_login() + batch_packet("select 1"))

    assert rig.events("service-request")[0]["name"] == "malformed tds"
