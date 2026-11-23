"""The LDAP service end to end: the daemon serving it on loopback, ldap3 and raw bytes as clients.

Loopback addresses stand in for the guest and the fake host, like in `test_daemon.py`; the ports are
free high ports, never 389.
"""

import asyncio
import json
import re
import sys
from dataclasses import replace

import Cryptodome.Hash.MD4
from impacket import ntlm as impacket_ntlm
from impacket import spnego
from ldap3 import ALL, ANONYMOUS, BASE, NTLM, SIMPLE, SUBTREE, Server
from ldap3 import Connection as LdapClient
from ldap3.operation.search import search_operation
from ldap3.protocol.rfc4511 import (
    AddRequest,
    BindRequest,
    DelRequest,
    SaslCredentials,
    UnbindRequest,
)
from support import FakeClock, free_port

from lan_session import (
    HostSpec,
    Layout,
    ServiceSpec,
    SessionSpec,
    publish_session,
)
from lan_sim.daemon import Daemon
from lan_sim.limits import Limits
from lan_sim.ntlm import challenge_message
from lan_sim.services import ldap as ldap_service
from lan_sim.services.ldap_ber import decode_message, encode_message

# OpenSSL 3 has no MD4, which ldap3's NTLM client needs; pycryptodomex (impacket's own) has it,
# under the name ldap3 looks for.
sys.modules.setdefault("Crypto", Cryptodome)
sys.modules.setdefault("Crypto.Hash", Cryptodome.Hash)
sys.modules.setdefault("Crypto.Hash.MD4", Cryptodome.Hash.MD4)

GUEST = "127.0.0.2"
HOST_ADDRESS = "127.0.0.3"
KEY = "task-1"
BASE_DN = "DC=corp,DC=local"
PASSWORD = "Passw0rd!"
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
NTLMSSP_MECHANISM = spnego.TypesMech["NTLMSSP - Microsoft NTLM Security Support Provider"]
SASL_BIND_IN_PROGRESS = 14
INVALID_CREDENTIALS = 49
PROTOCOL_ERROR = 2
AUTH_METHOD_NOT_SUPPORTED = 7
UNWILLING_TO_PERFORM = 53


class LdapWorld:
    """A daemon serving one host's LDAP service for one session."""

    def __init__(self, tmp_path, fqdn="dc01.corp.local", **limits):
        self.layout = Layout(tmp_path / "root")
        self.layout.make_directories()
        self.port = free_port(HOST_ADDRESS)
        accounts = (("admin", PASSWORD), ("svc_backup", "Backup2020"))
        service = ServiceSpec("ldap", self.port)
        self.host = HostSpec(fqdn, HOST_ADDRESS, "Windows Server 2019", accounts, (service,))
        self.daemon = Daemon(
            self.layout,
            {"ldap": ldap_service.SERVICE},
            limits=replace(Limits(), **limits),
            clock=FakeClock(),
            poll_interval=0.02,
        )

    async def open(self) -> None:
        publish_session(self.layout, SessionSpec(KEY, GUEST, "small-office", (self.host,)))
        await self.daemon.reconcile()

    def client(self, **options) -> LdapClient:
        server = Server(HOST_ADDRESS, port=self.port, get_info=options.pop("get_info", None))
        return LdapClient(server, source_address=GUEST, receive_timeout=10, **options)

    async def raw(self) -> "RawClient":
        reader, writer = await asyncio.open_connection(
            HOST_ADDRESS, self.port, local_addr=(GUEST, 0)
        )
        return RawClient(reader, writer)

    async def settle(self) -> None:
        for _ in range(300):
            if self.daemon.active_connections(KEY) == 0:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("connections did not settle")

    def records(self, event_type: str) -> list[dict]:
        path = self.layout.log_file(KEY)
        lines = path.read_text().splitlines() if path.exists() else []
        return [r for r in map(json.loads, lines) if r["type"] == event_type]

    def raw_log_text(self) -> str:
        return self.layout.log_file(KEY).read_text()


class RawClient:
    """Speaks LDAP as bytes, so a test can send what no client library would."""

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def send(self, data: bytes) -> None:
        self.writer.write(data)
        await self.writer.drain()

    async def request(self, message_id, operation, body):
        await self.send(encode_message(message_id, operation, body))

    async def receive(self):
        """The next LDAPMessage, or None when the server has closed the connection."""
        header = await asyncio.wait_for(self.reader.read(2), 5)
        if len(header) < 2:
            return None
        length = header[1]
        extra = b""
        if length & 0x80:
            extra = await self.reader.readexactly(length & 0x7F)
            length = int.from_bytes(extra, "big")
        body = await asyncio.wait_for(self.reader.readexactly(length), 5)
        return decode_message(header + extra + body)

    async def closed_by_server(self) -> bool:
        try:
            return await asyncio.wait_for(self.reader.read(1), 5) == b""
        except ConnectionError:
            return True

    def close(self) -> None:
        self.writer.close()


def scenario(test):
    def wrapper(tmp_path):
        async def body():
            world = LdapWorld(tmp_path, **getattr(test, "world_options", {}))
            await world.open()
            try:
                await test(world)
            finally:
                await world.daemon.shutdown()

        asyncio.run(body())

    wrapper.__name__ = test.__name__
    return wrapper


def with_world(**options):
    def decorate(test):
        test.world_options = options
        return test

    return decorate


def bind_request(name="", password="", version=3):
    request = BindRequest()
    request["version"] = version
    request["name"] = name
    request["authentication"]["simple"] = password
    return request


def sasl_bind_request(mechanism, credentials):
    request = BindRequest()
    request["version"] = 3
    request["name"] = ""
    sasl = SaslCredentials()
    sasl["mechanism"] = mechanism
    sasl["credentials"] = credentials
    request["authentication"]["sasl"] = sasl
    return request


def sicily_bind_request(kind, payload):
    request = BindRequest()
    request["version"] = 3
    request["name"] = ""
    request["authentication"][kind] = payload
    return request


def search_request(base, scope, text="(objectClass=*)", attributes=()):
    return search_operation(base, text, scope, 0, list(attributes), 0, 0, False, False, False)


def result_code(message) -> int:
    operation = message["protocolOp"]
    return int(operation[operation.getName()]["resultCode"])


def spnego_init(ntlm_message: bytes) -> bytes:
    token = spnego.SPNEGO_NegTokenInit()
    token["MechTypes"] = [NTLMSSP_MECHANISM]
    token["MechToken"] = ntlm_message
    return bytes(token.getData())


def spnego_response(ntlm_message: bytes) -> bytes:
    token = spnego.SPNEGO_NegTokenResp()
    token["ResponseToken"] = ntlm_message
    return bytes(token.getData())


def attribute_values(entry, name) -> list[str]:
    return [bytes(value).decode() for value in _attribute(entry, name)]


def _attribute(entry, name):
    for attribute in entry["attributes"]:
        if str(attribute["type"]).lower() == name.lower():
            return attribute["vals"]
    raise KeyError(name)


async def in_thread(function, *arguments):
    return await asyncio.to_thread(function, *arguments)


def anonymous_rootdse(world):
    client = world.client(get_info=ALL, authentication=ANONYMOUS)
    client.open()
    client.bind()
    return client


# --- the root DSE -----------------------------------------------------------------------------


@scenario
async def test_ldap3_reads_the_root_dse_of_a_domain_controller(world):
    client = await in_thread(anonymous_rootdse, world)
    try:
        info = client.server.info
        other = info.other
    finally:
        client.unbind()

    assert other["defaultNamingContext"] == [BASE_DN]
    assert other["rootDomainNamingContext"] == [BASE_DN]
    assert other["configurationNamingContext"] == [f"CN=Configuration,{BASE_DN}"]
    assert other["schemaNamingContext"] == [f"CN=Schema,CN=Configuration,{BASE_DN}"]
    assert BASE_DN in info.naming_contexts
    assert other["dnsHostName"] == ["dc01.corp.local"]
    assert other["ldapServiceName"] == ["corp.local:dc01$@CORP.LOCAL"]
    assert other["serverName"][0].startswith("CN=DC01,CN=Servers,")
    assert sorted(info.supported_ldap_versions) == ["2", "3"]
    assert {"GSSAPI", "GSS-SPNEGO"} <= set(info.supported_sasl_mechanisms)
    assert other["domainFunctionality"] == ["7"]
    assert other["forestFunctionality"] == ["7"]
    assert other["domainControllerFunctionality"] == ["7"]
    assert other["isSynchronized"] == ["TRUE"]
    assert other["isGlobalCatalogReady"] == ["TRUE"]


@scenario
@with_world(fqdn="ws01.corp.local")
async def test_a_host_that_is_not_a_domain_controller_answers_the_same_way(world):
    client = await in_thread(anonymous_rootdse, world)
    try:
        other = client.server.info.other
    finally:
        client.unbind()

    assert other["dnsHostName"] == ["ws01.corp.local"]
    assert other["defaultNamingContext"] == [BASE_DN]


@scenario
async def test_the_root_dse_honours_the_attributes_asked_for(world):
    raw = await world.raw()
    try:
        await raw.request(1, "searchRequest", search_request("", 0, attributes=["dnsHostName"]))
        entry = await raw.receive()
        done = await raw.receive()
    finally:
        raw.close()

    assert entry["messageID"] == 1
    attributes = entry["protocolOp"]["searchResEntry"]["attributes"]
    assert [str(a["type"]) for a in attributes] == ["dnsHostName"]
    assert done["protocolOp"].getName() == "searchResDone"
    assert result_code(done) == 0


# --- simple binds ------------------------------------------------------------------------------


def bound(client) -> bool:
    return bool(client.bind())


@scenario
async def test_an_anonymous_bind_succeeds_and_is_not_a_login_attempt(world):
    client = world.client(authentication=ANONYMOUS)

    assert await in_thread(bound, client) is True
    client.unbind()
    await world.settle()
    assert world.records("login-attempt") == []


@scenario
async def test_a_simple_bind_with_a_known_accounts_password_succeeds_and_is_logged(world):
    client = world.client(user="CORP\\admin", password=PASSWORD, authentication=SIMPLE)

    assert await in_thread(bound, client) is True
    client.unbind()
    await world.settle()
    [login] = world.records("login-attempt")
    assert (login["user"], login["domain"], login["mechanism"]) == ("admin", "CORP", "ldap-simple")
    assert (login["secret"], login["success"]) == (PASSWORD, True)
    assert (login["host"], login["service"]) == ("dc01.corp.local", "ldap")
    assert login["src"]["ip"] == GUEST


@scenario
async def test_every_way_a_client_writes_a_known_account_binds(world):
    names = ["admin", "CORP\\ADMIN", "admin@corp.local", "CN=admin,CN=Users,DC=corp,DC=local"]
    outcomes = []
    for name in names:
        client = world.client(user=name, password=PASSWORD, authentication=SIMPLE)
        outcomes.append(await in_thread(bound, client))
        client.unbind()

    assert outcomes == [True, True, True, True]


@scenario
async def test_a_simple_bind_with_the_wrong_password_is_refused_and_the_attempt_is_logged(world):
    client = world.client(user="CORP\\admin", password="nope", authentication=SIMPLE)

    assert await in_thread(bound, client) is False
    assert client.result["result"] == INVALID_CREDENTIALS
    client.unbind()
    await world.settle()
    [login] = world.records("login-attempt")
    assert (login["mechanism"], login["secret"], login["success"]) == ("ldap-simple", "nope", False)


@scenario
async def test_a_simple_bind_for_an_unknown_account_is_refused(world):
    client = world.client(user="CORP\\nobody", password=PASSWORD, authentication=SIMPLE)

    assert await in_thread(bound, client) is False
    assert client.result["result"] == INVALID_CREDENTIALS
    client.unbind()
    await world.settle()
    [login] = world.records("login-attempt")
    assert (login["user"], login["success"]) == ("nobody", False)


@scenario
async def test_a_name_with_an_empty_password_is_not_an_unauthenticated_success(world):
    raw = await world.raw()
    try:
        await raw.request(1, "bindRequest", bind_request("CORP\\admin", ""))
        reply = await raw.receive()
    finally:
        raw.close()

    assert result_code(reply) == UNWILLING_TO_PERFORM
    await world.settle()
    [login] = world.records("login-attempt")
    assert (login["secret"], login["success"]) == ("", False)


@scenario
async def test_a_bind_with_an_unsupported_version_is_a_protocol_error(world):
    raw = await world.raw()
    try:
        await raw.request(1, "bindRequest", bind_request("", "", version=1))
        reply = await raw.receive()
    finally:
        raw.close()

    assert result_code(reply) == PROTOCOL_ERROR


@scenario
async def test_control_characters_in_what_a_client_sends_never_reach_the_log(world):
    hostile = "ev\x1b[31mil\x00\x07\r\n"
    raw = await world.raw()
    try:
        await raw.request(1, "bindRequest", bind_request(f"CORP\\{hostile}", f"pw{hostile}"))
        await raw.receive()
        await raw.request(2, "searchRequest", search_request(f"DC={hostile}", 2, f"(cn={hostile})"))
        await raw.receive()
    finally:
        raw.close()
    await world.settle()

    [login] = world.records("login-attempt")
    [search] = world.records("service-request")
    for text in (login["user"], login["secret"], search["detail"]):
        assert not CONTROL_CHARACTERS.search(text)
    assert login["secret"] == "pwev[31mil"
    assert world.raw_log_text().count("\n") == len(world.raw_log_text().splitlines())


# --- NTLM binds --------------------------------------------------------------------------------

HASHCAT_LINE = re.compile(r"^admin::CORP:[0-9a-f]{16}:[0-9a-f]{32}:[0-9a-f]+$")


@scenario
async def test_an_ntlm_bind_from_ldap3_is_captured_and_refused(world):
    client = world.client(user="CORP\\admin", password=PASSWORD, authentication=NTLM)

    assert await in_thread(bound, client) is False
    assert client.result["result"] == INVALID_CREDENTIALS
    client.unbind()
    await world.settle()
    [login] = world.records("login-attempt")
    assert (login["user"], login["domain"], login["mechanism"]) == ("admin", "CORP", "ntlm")
    assert HASHCAT_LINE.match(login["secret"])
    assert login["success"] is True


@scenario
async def test_an_ntlm_bind_with_a_wrong_password_is_logged_as_unverified(world):
    client = world.client(user="CORP\\admin", password="wrong", authentication=NTLM)

    assert await in_thread(bound, client) is False
    client.unbind()
    await world.settle()
    [login] = world.records("login-attempt")
    assert HASHCAT_LINE.match(login["secret"])
    assert login["success"] is False


def type3_for(type1, challenge_message, user="admin", password=PASSWORD):
    type3, _ = impacket_ntlm.getNTLMSSPType3(type1, challenge_message, user, password, "CORP")
    return type3.getData()


@scenario
async def test_a_gss_spnego_bind_gets_the_challenge_in_the_sasl_credentials(world):
    type1 = impacket_ntlm.getNTLMSSPType1("WS01", "CORP")
    raw = await world.raw()
    try:
        await raw.request(
            3, "bindRequest", sasl_bind_request("GSS-SPNEGO", spnego_init(type1.getData()))
        )
        challenge = await raw.receive()
        assert challenge["messageID"] == 3
        assert result_code(challenge) == SASL_BIND_IN_PROGRESS
        reply = challenge["protocolOp"]["bindResponse"]
        token = spnego.SPNEGO_NegTokenResp(bytes(reply["serverSaslCreds"]))
        type2 = bytes(token["ResponseToken"])
        assert type2.startswith(b"NTLMSSP\x00\x02\x00\x00\x00")
        challenge_message = impacket_ntlm.NTLMAuthChallenge(type2)

        type3 = type3_for(type1, type2)
        await raw.request(4, "bindRequest", sasl_bind_request("GSS-SPNEGO", spnego_response(type3)))
        final = await raw.receive()
    finally:
        raw.close()

    assert final["messageID"] == 4
    assert result_code(final) == INVALID_CREDENTIALS
    await world.settle()
    [login] = world.records("login-attempt")
    assert (login["mechanism"], login["success"]) == ("ntlm", True)
    assert HASHCAT_LINE.match(login["secret"])
    assert challenge_message["challenge"].hex() in login["secret"]


@scenario
async def test_a_sasl_ntlm_bind_with_the_bare_ntlm_message_is_served_too(world):
    type1 = impacket_ntlm.getNTLMSSPType1("WS01", "CORP")
    raw = await world.raw()
    try:
        await raw.request(1, "bindRequest", sasl_bind_request("GSS-SPNEGO", type1.getData()))
        challenge = await raw.receive()
    finally:
        raw.close()

    assert result_code(challenge) == SASL_BIND_IN_PROGRESS


@scenario
async def test_the_sicily_forms_are_served_for_clients_that_use_them(world):
    type1 = impacket_ntlm.getNTLMSSPType1("WS01", "CORP")
    raw = await world.raw()
    try:
        await raw.request(1, "bindRequest", sicily_bind_request("sicilyPackageDiscovery", b""))
        discovery = await raw.receive()
        await raw.request(2, "bindRequest", sicily_bind_request("sicilyNegotiate", type1.getData()))
        negotiate = await raw.receive()
        type2 = bytes(negotiate["protocolOp"]["bindResponse"]["matchedDN"])
        type3 = type3_for(type1, type2)
        await raw.request(3, "bindRequest", sicily_bind_request("sicilyResponse", type3))
        final = await raw.receive()
    finally:
        raw.close()

    assert b"NTLM" in bytes(discovery["protocolOp"]["bindResponse"]["matchedDN"])
    assert result_code(negotiate) == 0
    assert result_code(final) == INVALID_CREDENTIALS
    await world.settle()
    assert len(world.records("login-attempt")) == 1


@scenario
async def test_an_ntlm_response_without_a_challenge_is_refused_without_a_log_entry(world):
    type1 = impacket_ntlm.getNTLMSSPType1("WS01", "CORP")
    type2 = challenge_message(world.host, bytes(8), FakeClock())
    raw = await world.raw()
    try:
        type3 = type3_for(type1, type2)
        await raw.request(1, "bindRequest", sicily_bind_request("sicilyResponse", type3))
        final = await raw.receive()
    finally:
        raw.close()

    assert result_code(final) == INVALID_CREDENTIALS
    await world.settle()
    assert world.records("login-attempt") == []


@scenario
async def test_a_malformed_ntlm_message_is_refused_and_the_connection_goes_on(world):
    raw = await world.raw()
    try:
        await raw.request(
            1, "bindRequest", sasl_bind_request("GSS-SPNEGO", b"NTLMSSP\x00\x03\x00\x00\x00junk")
        )
        refused = await raw.receive()
        await raw.request(2, "bindRequest", bind_request())
        anonymous = await raw.receive()
    finally:
        raw.close()

    assert result_code(refused) == INVALID_CREDENTIALS
    assert result_code(anonymous) == 0


@scenario
async def test_a_sasl_mechanism_the_server_cannot_do_is_not_supported(world):
    raw = await world.raw()
    try:
        await raw.request(1, "bindRequest", sasl_bind_request("DIGEST-MD5", b""))
        reply = await raw.receive()
    finally:
        raw.close()

    assert result_code(reply) == AUTH_METHOD_NOT_SUPPORTED


# --- searches ----------------------------------------------------------------------------------


@scenario
async def test_a_base_search_of_the_domain_returns_the_domain_entry(world):
    def search():
        client = world.client(authentication=ANONYMOUS)
        client.bind()
        client.search(BASE_DN.lower(), "(objectClass=*)", search_scope=BASE, attributes=["*"])
        response, result = client.response, client.result
        client.unbind()
        return response, result

    response, result = await in_thread(search)

    [entry] = response
    assert entry["dn"] == BASE_DN
    assert set(entry["attributes"]["objectClass"]) == {"top", "domain", "domainDNS"}
    assert entry["attributes"]["name"] == ["corp"]
    assert entry["attributes"]["distinguishedName"] == [BASE_DN]
    assert result["result"] == 0


@scenario
async def test_every_other_search_is_empty_and_logged_with_its_base_and_filter(world):
    def search():
        client = world.client(authentication=ANONYMOUS)
        client.bind()
        found = [
            client.search(
                BASE_DN, "(&(objectClass=user)(sAMAccountName=admin))", search_scope=SUBTREE
            ),
            client.search(f"CN=Users,{BASE_DN}", "(cn=*)", search_scope=BASE),
        ]
        result = client.result
        client.unbind()
        return found, result

    found, result = await in_thread(search)

    assert found == [False, False]
    assert result["result"] == 0
    await world.settle()
    details = [r["detail"] for r in world.records("service-request")]
    assert any(BASE_DN in d and "(&(objectClass=user)(sAMAccountName=admin))" in d for d in details)
    assert any(f"CN=Users,{BASE_DN}" in d and "(cn=*)" in d for d in details)
    assert {r["name"] for r in world.records("service-request")} == {"ldap search"}


@scenario
async def test_a_paged_search_with_its_control_ends_normally(world):
    def paged():
        client = world.client(authentication=ANONYMOUS)
        client.bind()
        return list(
            client.extend.standard.paged_search(
                BASE_DN, "(objectClass=user)", paged_size=100, generator=True
            )
        )

    assert await in_thread(paged) == []


@scenario
async def test_a_not_filter_is_accepted_even_though_ldap3_cannot_decode_it(world):
    def search():
        client = world.client(authentication=ANONYMOUS)
        client.bind()
        found = client.search(BASE_DN, "(!(userAccountControl=2))", search_scope=SUBTREE)
        client.unbind()
        return found

    assert await in_thread(search) is False
    await world.settle()
    [request] = world.records("service-request")
    assert "(!(userAccountControl=2))" in request["detail"]


@scenario
async def test_a_very_long_filter_is_cut_in_the_log(world):
    raw = await world.raw()
    try:
        await raw.request(1, "searchRequest", search_request(BASE_DN, 2, "(cn=" + "x" * 5000 + ")"))
        await raw.receive()
    finally:
        raw.close()
    await world.settle()

    [request] = world.records("service-request")
    assert len(request["detail"]) <= Limits().max_path_length


# --- the rest of the protocol ------------------------------------------------------------------


@scenario
async def test_message_ids_are_echoed_on_every_response(world):
    raw = await world.raw()
    try:
        await raw.request(5, "bindRequest", bind_request())
        bind = await raw.receive()
        await raw.request(70000, "searchRequest", search_request("", 0))
        entry, done = await raw.receive(), await raw.receive()
    finally:
        raw.close()

    assert (bind["messageID"], entry["messageID"], done["messageID"]) == (5, 70000, 70000)


@scenario
async def test_an_unbind_ends_the_connection_cleanly(world):
    raw = await world.raw()
    try:
        await raw.request(1, "bindRequest", bind_request())
        await raw.receive()
        await raw.request(2, "unbindRequest", UnbindRequest(""))
        assert await raw.closed_by_server()
    finally:
        raw.close()
    await world.settle()

    assert world.records("service-request") == []


@scenario
async def test_an_unoffered_operation_is_a_protocol_error_and_the_connection_goes_on(
    world,
):
    deletion = DelRequest("CN=x," + BASE_DN)
    addition = AddRequest()
    addition["entry"] = "CN=y," + BASE_DN
    raw = await world.raw()
    try:
        await raw.request(1, "delRequest", deletion)
        deleted = await raw.receive()
        await raw.request(2, "bindRequest", bind_request())
        bind = await raw.receive()
    finally:
        raw.close()

    assert deleted["protocolOp"].getName() == "delResponse"
    assert result_code(deleted) == PROTOCOL_ERROR
    assert result_code(bind) == 0


@scenario
async def test_garbage_ends_the_connection_and_leaves_the_service_serving(world):
    raw = await world.raw()
    try:
        await raw.send(b"GET / HTTP/1.1\r\n\r\n")
        assert await raw.closed_by_server()
    finally:
        raw.close()
    await world.settle()

    client = world.client(authentication=ANONYMOUS)
    assert await in_thread(bound, client) is True
    client.unbind()
    [malformed] = world.records("service-request")
    assert malformed["name"] == "ldap malformed"


@scenario
async def test_an_oversized_message_ends_the_connection_before_it_is_read(world):
    raw = await world.raw()
    try:
        await raw.send(b"\x30\x84\x7f\xff\xff\xff")
        assert await raw.closed_by_server()
    finally:
        raw.close()


@scenario
async def test_a_truncated_message_followed_by_silence_does_not_hang_the_daemon(world):
    raw = await world.raw()
    try:
        await raw.send(encode_message(1, "bindRequest", bind_request())[:-2])
    finally:
        raw.close()
    await world.settle()


@scenario
async def test_a_filter_nested_far_too_deep_ends_the_connection(world):
    raw = await world.raw()
    depth = 3000
    filter_bytes = b"\x87\x01a"
    for _ in range(depth):
        filter_bytes = b"\xa2" + _length(len(filter_bytes)) + filter_bytes
    body = (
        b"\x04\x00\x0a\x01\x00\x0a\x01\x00\x02\x01\x00\x02\x01\x00\x01\x01\x00"
        + filter_bytes
        + b"\x30\x00"
    )
    request = b"\x63" + _length(len(body)) + body
    message = b"\x02\x01\x01" + request
    try:
        await raw.send(b"\x30" + _length(len(message)) + message)
        assert await raw.closed_by_server()
    finally:
        raw.close()


def _length(length: int) -> bytes:
    return bytes([length]) if length < 0x80 else b"\x82" + length.to_bytes(2, "big")
