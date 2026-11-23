"""WinRM over real sockets: Identify, the 401 challenges, the NTLM capture and hostile input.

The daemon serves a session on loopback addresses (the guest is 127.0.0.2, the fake host 127.0.0.3);
the client side is asyncio too, so the event loop that serves the daemon never blocks.
"""

import asyncio
import base64
import contextlib
import functools
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from impacket import ntlm as impacket_ntlm
from support import FakeClock, free_port

from lan_session import HostSpec, Layout, ServiceSpec, SessionSpec, publish_session
from lan_sim.daemon import Daemon
from lan_sim.limits import Limits
from lan_sim.ntlm import CHALLENGE_MESSAGE, ntlm_message_type
from lan_sim.services.winrm import SERVICE

GUEST = "127.0.0.2"
HOST_ADDRESS = "127.0.0.3"
KEY = "task-1"
ACCOUNTS = (("Administrator", "Passw0rd!"),)
WSMID = "http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd"
IDENTIFY = (
    f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:wsmid="{WSMID}">'
    "<s:Header/><s:Body><wsmid:Identify/></s:Body></s:Envelope>"
).encode("ascii")
CREATE_SHELL = (
    b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
    b'xmlns:rsp="http://schemas.microsoft.com/wbem/wsman/1/windows/shell"><s:Header/>'
    b"<s:Body><rsp:Shell/></s:Body></s:Envelope>"
)
TIMEOUT_S = 5
CHALLENGE_OFFSET = 24


def runs_async(test):
    """Runs an async test body on a fresh event loop, as test_daemon.py does."""

    @functools.wraps(test)
    def wrapper(**fixtures):
        asyncio.run(test(**fixtures))

    return wrapper


def encode64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def post(body: bytes = b"", *, path="/wsman", version="HTTP/1.1", headers=()) -> bytes:
    lines = [
        f"POST {path} {version}",
        "Host: fs01.corp.local:5985",
        f"Content-Length: {len(body)}",
        *(f"{name}: {value}" for name, value in headers),
    ]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


@dataclass(frozen=True)
class Answer:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def values(self, name: str) -> list[str]:
        return [value for key, value in self.headers if key.lower() == name.lower()]


class Wire:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    async def send(self, data: bytes) -> None:
        self.writer.write(data)
        await self.writer.drain()

    async def answer(self) -> Answer:
        head = await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), TIMEOUT_S)
        status_line, *lines = head[:-4].decode("latin-1").split("\r\n")
        headers = tuple(tuple(part.strip() for part in line.split(":", 1)) for line in lines)
        length = int(next((v for k, v in headers if k.lower() == "content-length"), "0"))
        body = await asyncio.wait_for(self.reader.readexactly(length), TIMEOUT_S)
        return Answer(int(status_line.split(" ")[1]), headers, body)

    async def ended(self) -> bool:
        """True when the server closed the connection, with nothing more to say."""
        rest = await asyncio.wait_for(self.reader.read(), TIMEOUT_S)
        return rest == b""

    def close(self) -> None:
        self.writer.close()


@dataclass
class Served:
    port: int
    daemon: Daemon
    layout: Layout

    async def connect(self) -> Wire:
        reader, writer = await asyncio.open_connection(
            HOST_ADDRESS, self.port, local_addr=(GUEST, 0)
        )
        return Wire(reader, writer)

    async def settle(self) -> None:
        for _ in range(500):
            if self.daemon.active_connections(KEY) == 0:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the connection was not closed by the daemon")

    def records(self, event_type: str) -> list[dict]:
        return [record for record in self._all() if record["type"] == event_type]

    def _all(self) -> list[dict]:
        path: Path = self.layout.log_file(KEY)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]

    def raw_log(self) -> bytes:
        return self.layout.log_file(KEY).read_bytes()


@contextlib.asynccontextmanager
async def served(tmp_path, limits: Limits | None = None) -> AsyncIterator[Served]:
    layout = Layout(tmp_path / "root")
    layout.make_directories()
    port = free_port(HOST_ADDRESS)
    host = HostSpec(
        "fs01.corp.local",
        HOST_ADDRESS,
        "Windows Server 2019",
        ACCOUNTS,
        (ServiceSpec("winrm", port),),
    )
    publish_session(layout, SessionSpec(KEY, GUEST, "small-office", (host,)))
    daemon = Daemon(
        layout,
        {"winrm": SERVICE},
        limits=limits or Limits(),
        clock=FakeClock(),
        poll_interval=0.02,
    )
    await daemon.reconcile()
    try:
        yield Served(port, daemon, layout)
    finally:
        await daemon.shutdown()


async def ntlm_handshake(wire: Wire, user: str, password: str, domain="CORP") -> Answer:
    """Runs impacket's client through type 1, the challenge and type 3 on `wire`."""
    type1 = impacket_ntlm.getNTLMSSPType1("WS01", domain)
    await wire.send(post(headers=[("Authorization", f"Negotiate {encode64(type1.getData())}")]))
    challenge = await wire.answer()
    type2 = base64.b64decode(challenge.values("WWW-Authenticate")[0].split(" ", 1)[1])
    type3, _ = impacket_ntlm.getNTLMSSPType3(type1, type2, user, password, domain)
    await wire.send(post(headers=[("Authorization", f"Negotiate {encode64(type3.getData())}")]))
    return await wire.answer()


async def challenge_of(wire: Wire) -> tuple[bytes, impacket_ntlm.NTLMAuthNegotiate]:
    type1 = impacket_ntlm.getNTLMSSPType1("WS01", "CORP")
    await wire.send(post(headers=[("Authorization", f"Negotiate {encode64(type1.getData())}")]))
    answer = await wire.answer()
    return base64.b64decode(answer.values("WWW-Authenticate")[0].split(" ", 1)[1]), type1


def authenticate_for(type1, type2: bytes, user: str, password: str) -> bytes:
    type3, _ = impacket_ntlm.getNTLMSSPType3(type1, type2, user, password, "CORP")
    return type3.getData()


def assert_refused_with_both_schemes(answer: Answer) -> None:
    assert answer.status == 401
    assert answer.values("WWW-Authenticate") == ["Negotiate", 'Basic realm="WSMAN"']
    assert answer.body == b""


# --- Identify ----------------------------------------------------------------------------------


@runs_async
async def test_an_identify_request_is_answered_with_the_identify_response(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        await wire.send(post(IDENTIFY))

        answer = await wire.answer()

        assert answer.status == 200
        response = ET.fromstring(answer.body)  # noqa: S314 - our own constant, parsed in a test
        fields = {
            element.tag.rpartition("}")[2]: element.text
            for element in response.iter()
            if element.text and element.tag.startswith(f"{{{WSMID}}}")
        }
        assert fields["ProductVendor"] == "Microsoft Corporation"
        assert fields["ProductVersion"] == "OS: 0.0.0 SP: 0.0 Stack: 3.0"
        assert fields["ProtocolVersion"] == "http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
        profiles = [element.text or "" for element in response.iter()]
        assert any(profile.endswith("/spnego-kerberos") for profile in profiles)
        assert any(profile.endswith("/basic") for profile in profiles)
        assert await wire.ended()


@runs_async
async def test_identify_leaves_no_login_or_request_record(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        await wire.send(post(IDENTIFY))
        await wire.answer()
        await wire.ended()
        await host.settle()

        assert host.records("login-attempt") == []
        assert host.records("service-request") == []


# --- the unauthenticated refusal ---------------------------------------------------------------


@runs_async
async def test_a_shell_request_without_credentials_gets_both_schemes_and_no_body(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        await wire.send(post(CREATE_SHELL))

        assert_refused_with_both_schemes(await wire.answer())


@runs_async
async def test_the_refusal_keeps_the_connection_open_for_the_handshake(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        await wire.send(post(CREATE_SHELL))
        await wire.answer()

        await wire.send(post(CREATE_SHELL))

        assert_refused_with_both_schemes(await wire.answer())


@runs_async
async def test_the_refusal_is_logged_with_the_soap_action_when_there_is_one(tmp_path):
    action = "http://schemas.xmlsoap.org/ws/2004/09/transfer/Create"
    async with served(tmp_path) as host:
        wire = await host.connect()
        await wire.send(post(CREATE_SHELL, headers=[("SOAPAction", action)]))
        await wire.answer()
        wire.close()
        await host.settle()

        [request] = host.records("service-request")
        assert request["name"] == "winrm request"
        assert request["detail"] == action


@runs_async
async def test_the_refusal_without_a_soap_action_logs_the_start_of_the_body(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        await wire.send(post(CREATE_SHELL + b"x" * 500))
        await wire.answer()
        wire.close()
        await host.settle()

        [request] = host.records("service-request")
        assert request["detail"] == (CREATE_SHELL + b"x" * 500)[:200].decode("latin-1")


# --- NTLM ----------------------------------------------------------------------------------------


@runs_async
async def test_the_negotiate_answer_carries_the_challenge_on_the_same_connection(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        type1 = impacket_ntlm.getNTLMSSPType1("WS01", "CORP")
        await wire.send(post(headers=[("Authorization", f"Negotiate {encode64(type1.getData())}")]))

        answer = await wire.answer()

        assert answer.status == 401
        [token] = answer.values("WWW-Authenticate")
        scheme, _, value = token.partition(" ")
        assert scheme == "Negotiate"
        assert ntlm_message_type(base64.b64decode(value)) == CHALLENGE_MESSAGE


@runs_async
async def test_a_spnego_wrapped_negotiate_gets_an_spnego_wrapped_challenge(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        type1 = impacket_ntlm.getNTLMSSPType1("WS01", "CORP").getData()
        wrapped = b"\x60\x20\x06\x06" + b"\x2b\x06\x01\x05\x05\x02" + b"\xa0\x10" + type1
        await wire.send(post(headers=[("Authorization", f"Negotiate {encode64(wrapped)}")]))

        answer = await wire.answer()

        token = base64.b64decode(answer.values("WWW-Authenticate")[0].split(" ", 1)[1])
        assert not token.startswith(b"NTLMSSP\x00")
        assert b"NTLMSSP\x00" in token


@runs_async
async def test_a_wrong_password_is_logged_with_its_hash_and_refused(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()

        answer = await ntlm_handshake(wire, "Administrator", "wrong-password")

        assert_refused_with_both_schemes(answer)
        [login] = host.records("login-attempt")
        assert login["mechanism"] == "ntlm"
        assert login["user"] == "Administrator"
        assert login["domain"] == "CORP"
        assert login["success"] is False
        assert login["secret"].startswith("Administrator::CORP:")
        assert login["dst"] == {"ip": HOST_ADDRESS, "port": host.port}
        assert await wire.ended()


@runs_async
async def test_the_right_password_verifies_but_still_gets_no_session(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()

        answer = await ntlm_handshake(wire, "Administrator", ACCOUNTS[0][1])

        assert_refused_with_both_schemes(answer)
        [login] = host.records("login-attempt")
        assert login["success"] is True
        assert await wire.ended()


@runs_async
async def test_the_logged_hash_carries_this_connections_challenge(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        type2, type1 = await challenge_of(wire)
        message = authenticate_for(type1, type2, "Administrator", "x")
        await wire.send(post(headers=[("Authorization", f"Negotiate {encode64(message)}")]))
        await wire.answer()
        await host.settle()

        [login] = host.records("login-attempt")
        challenge_hex = re.search(r"CORP:([0-9a-f]{16}):", login["secret"])
        assert challenge_hex is not None
        sent_challenge = type2[CHALLENGE_OFFSET : CHALLENGE_OFFSET + 8]
        assert bytes.fromhex(challenge_hex.group(1)) == sent_challenge


@runs_async
async def test_a_type3_on_a_connection_that_issued_no_challenge_logs_nothing(tmp_path):
    async with served(tmp_path) as host:
        other = await host.connect()
        challenge_token, type1 = await challenge_of(other)
        wire = await host.connect()
        message = authenticate_for(type1, challenge_token, "Administrator", "Passw0rd!")
        await wire.send(post(headers=[("Authorization", f"Negotiate {encode64(message)}")]))

        assert_refused_with_both_schemes(await wire.answer())
        assert await wire.ended()
        other.close()
        await host.settle()
        assert host.records("login-attempt") == []


@runs_async
async def test_a_truncated_authenticate_is_refused_and_logs_nothing(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        challenge_token, type1 = await challenge_of(wire)
        message = authenticate_for(type1, challenge_token, "Administrator", "Passw0rd!")
        await wire.send(post(headers=[("Authorization", f"Negotiate {encode64(message[:40])}")]))

        answer = await wire.answer()

        assert answer.status == 401
        assert await wire.ended()
        await host.settle()
        assert host.records("login-attempt") == []


@runs_async
async def test_a_negotiate_token_that_is_not_ntlm_is_refused_and_closed(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        junk = encode64(b"\x30\x03\x02\x01\x05")
        await wire.send(post(headers=[("Authorization", f"Negotiate {junk}")]))

        answer = await wire.answer()

        assert_refused_with_both_schemes(answer)
        assert await wire.ended()


# --- Basic --------------------------------------------------------------------------------------


@runs_async
async def test_basic_credentials_are_logged_in_clear_and_refused(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        token = encode64(b"CORP\\Administrator:hunter2")
        await wire.send(post(headers=[("Authorization", f"Basic {token}")]))

        assert_refused_with_both_schemes(await wire.answer())
        [login] = host.records("login-attempt")
        assert login["mechanism"] == "basic"
        assert login["user"] == "CORP\\Administrator"
        assert login["secret"] == "hunter2"
        assert login["success"] is False
        assert await wire.ended()


@runs_async
async def test_basic_with_malformed_base64_is_refused_without_a_log_record(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        await wire.send(post(headers=[("Authorization", "Basic not*base64!")]))

        assert (await wire.answer()).status == 401
        assert await wire.ended()
        await host.settle()
        assert host.records("login-attempt") == []


@runs_async
async def test_control_characters_in_a_password_never_reach_the_log_raw(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        password = "\x1b[2J\x07\u202eabc\r\n".encode("utf-8")
        token = encode64(b"Administrator:" + password)
        await wire.send(post(headers=[("Authorization", f"Basic {token}")]))
        await wire.answer()
        await wire.ended()
        await host.settle()

        assert host.records("login-attempt")[0]["secret"].endswith("abc")
        assert re.search(rb"[\x00-\x09\x0b-\x1f\x7f]", host.raw_log()) is None


# --- routing and framing -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/wsman"), ("GET", "/"), ("HEAD", "/wsman"), ("POST", "/elsewhere")],
)
@runs_async
async def test_anything_but_post_to_wsman_is_not_found(tmp_path, method, path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        request = f"{method} {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode()
        await wire.send(request)

        assert (await wire.answer()).status == 404


@runs_async
async def test_an_http_10_request_gets_connection_close_and_ends(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        await wire.send(post(IDENTIFY, version="HTTP/1.0"))

        answer = await wire.answer()

        assert answer.status == 200
        assert answer.values("Connection") == ["close"]
        assert await wire.ended()


HOSTILE = {
    "oversize-header": b"POST /wsman HTTP/1.1\r\nX-Pad: " + b"a" * 9000 + b"\r\n\r\n",
    "one-hundred-headers": b"POST /wsman HTTP/1.1\r\n"
    + b"".join(b"X-%d: v\r\n" % number for number in range(100))
    + b"\r\n",
    "garbage": b"\x00\xff\xfe garbage \x1b[31m\r\n\r\n",
    "bad-content-length": b"POST /wsman HTTP/1.1\r\nContent-Length: -4\r\n\r\n",
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
@runs_async
async def test_hostile_head_is_answered_400_and_closed_and_the_daemon_stays_up(tmp_path, name):
    async with served(tmp_path) as host:
        wire = await host.connect()
        await wire.send(HOSTILE[name])

        assert (await wire.answer()).status == 400
        assert await wire.ended()

        healthy = await host.connect()
        await healthy.send(post(IDENTIFY))
        assert (await healthy.answer()).status == 200


@runs_async
async def test_a_ten_megabyte_body_is_refused_with_413_and_the_daemon_stays_up(tmp_path):
    async with served(tmp_path) as host:
        wire = await host.connect()
        size = 10 * 1024 * 1024
        head = f"POST /wsman HTTP/1.1\r\nContent-Length: {size}\r\n\r\n".encode()

        async def flood() -> None:
            with contextlib.suppress(ConnectionError):
                await wire.send(head + b"x" * size)

        flooding = asyncio.create_task(flood())
        answer = await wire.answer()
        flooding.cancel()

        assert answer.status == 413
        healthy = await host.connect()
        await healthy.send(post(IDENTIFY))
        assert (await healthy.answer()).status == 200


@runs_async
async def test_a_slow_drip_header_is_cut_off_by_the_connection_lifetime(tmp_path):
    limits = replace(Limits(), max_connection_seconds=1.0, idle_timeout_seconds=0.5)
    async with served(tmp_path, limits) as host:
        wire = await host.connect()
        await wire.send(b"POST /wsman HTTP/1.1\r\nX-Slow: ")

        async def drip() -> None:
            with contextlib.suppress(ConnectionError):
                while True:
                    await wire.send(b"a")
                    await asyncio.sleep(0.05)

        dripping = asyncio.create_task(drip())
        ended = await asyncio.wait_for(wire.ended(), TIMEOUT_S)
        dripping.cancel()

        assert ended is True
