"""The MSSQL service behind the real daemon, on loopback, driven by impacket's own TDS client."""

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from dataclasses import replace

from impacket.tds import MSSQL
from mssql_support import (
    TDS_71,
    TDS_73,
    TDS_74,
    batch_packet,
    login7_packet,
    messages,
    prelogin_request,
)
from support import FakeClock, free_port

from lan_session import HostSpec, Layout, ServiceSpec, SessionSpec, publish_session
from lan_sim.daemon import Daemon
from lan_sim.limits import Limits
from lan_sim.registry import build_registry
from lan_sim.services.mssql_sql import sql_banner
from lan_sim.services.mssql_tokens import done, login_success, scalar_result
from lan_sim.services.mssql_wire import TdsVersion, prelogin_response

GUEST = "127.0.0.1"
HOST_ADDRESS = "127.0.0.3"
OS_BANNER = "Windows Server 2019 Standard 10.0.17763"
ACCOUNTS = (("sa", "Passw0rd"), ("Administrator", "Welcome1"))
KEY = "task-1"


class Live:
    def __init__(self, daemon: Daemon, layout: Layout, host: HostSpec) -> None:
        self.daemon = daemon
        self.layout = layout
        self.host = host
        self.port = host.services[0].port

    def log(self, event_type: str) -> list[dict]:
        lines = self.layout.log_file(KEY).read_text().splitlines()
        return [record for record in map(json.loads, lines) if record["type"] == event_type]

    async def settle(self) -> None:
        for _ in range(300):
            if self.daemon.active_connections(KEY) == 0:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the connection never ended")

    async def exchange(self, data: bytes) -> bytes:
        """Sends `data` from the guest address and returns what came back until it went quiet."""
        reader, writer = await asyncio.open_connection(
            HOST_ADDRESS, self.port, local_addr=(GUEST, 0)
        )
        writer.write(data)
        received = b""
        try:
            while chunk := await asyncio.wait_for(reader.read(4096), 0.5):
                received += chunk
        except TimeoutError:
            pass
        finally:
            writer.close()
        return received


@asynccontextmanager
async def live(tmp_path):
    layout = Layout(tmp_path / "root")
    layout.make_directories()
    port = free_port(HOST_ADDRESS)
    host = HostSpec(
        "fs01.corp.local", HOST_ADDRESS, OS_BANNER, ACCOUNTS, (ServiceSpec("mssql", port),)
    )
    daemon = Daemon(
        layout,
        build_registry(["mssql"]),
        limits=replace(Limits(), idle_timeout_seconds=2.0),
        clock=FakeClock(),
        poll_interval=0.02,
    )
    publish_session(layout, SessionSpec(KEY, GUEST, "small-office", (host,)))
    await daemon.reconcile()
    try:
        yield Live(daemon, layout, host)
    finally:
        await daemon.shutdown()


def run(test):
    def wrapper(tmp_path):
        async def body():
            async with live(tmp_path) as world:
                await test(world)

        asyncio.run(body())

    wrapper.__name__ = test.__name__
    return wrapper


def impacket_session(world: Live, body):
    client = MSSQL(HOST_ADDRESS, port=world.port, rowsPrinter=_Silent())
    client.connect()
    try:
        return body(client)
    finally:
        client.disconnect()


class _Silent:
    def logMessage(self, message):  # noqa: N802 - impacket's printer interface
        return None


def sql_login_and_query(world: Live, *queries: str, password="anything"):
    def body(client):
        assert client.login(None, "sa", password, "", None, False)
        return [client.sql_query(query) for query in queries]

    return impacket_session(world, body)


@run
async def test_impacket_logs_in_with_sql_auth_and_any_password(world):
    [version_rows] = await asyncio.to_thread(
        sql_login_and_query, world, "select @@version", password="not-the-password"
    )
    await world.settle()

    assert version_rows[0][""] == sql_banner(world.host)
    [login] = world.log("login-attempt")
    assert (login["user"], login["mechanism"], login["secret"], login["success"]) == (
        "sa",
        "sql",
        "not-the-password",
        True,
    )
    assert login["src"]["ip"] == GUEST
    assert login["dst"] == {"ip": HOST_ADDRESS, "port": world.port}
    [request] = world.log("service-request")
    assert (request["name"], request["detail"]) == ("sql batch", "select @@version")


@run
async def test_impacket_runs_several_queries_and_the_dangerous_one_is_only_logged(world):
    rows = await asyncio.to_thread(
        sql_login_and_query,
        world,
        "SELECT   SERVERPROPERTY('ProductVersion')",
        "exec xp_cmdshell 'whoami'",
        "select db_name()",
    )
    await world.settle()

    assert rows[0][0][""] == "15.0.2000.5"
    assert rows[1] == []
    assert rows[2][0][""] == "master"
    details = [request["detail"] for request in world.log("service-request")]
    assert details == [
        "SELECT   SERVERPROPERTY('ProductVersion')",
        "exec xp_cmdshell 'whoami'",
        "select db_name()",
    ]


@run
async def test_impacket_integrated_login_leaves_a_hashcat_line_and_fails(world):
    def body(client):
        return client.login(None, "Administrator", "wrong", "CORP", None, True)

    result = await asyncio.to_thread(impacket_session, world, body)
    await world.settle()

    assert result is False
    [login] = world.log("login-attempt")
    assert (login["user"], login["domain"], login["mechanism"]) == ("Administrator", "CORP", "ntlm")
    assert login["success"] is False
    user, _, domain, challenge, proof, blob = login["secret"].split(":")
    assert (user, domain) == ("Administrator", "CORP")
    assert len(challenge) == 16
    assert len(proof) == 32
    assert blob.startswith("0101")


@run
async def test_impacket_integrated_login_with_the_right_password_is_verified_but_refused(world):
    def body(client):
        return client.login(None, "Administrator", "Welcome1", "CORP", None, True)

    result = await asyncio.to_thread(impacket_session, world, body)
    await world.settle()

    assert result is False
    [login] = world.log("login-attempt")
    assert login["success"] is True


@run
async def test_a_tds_71_client_gets_the_legacy_token_layout(world):
    legacy = TdsVersion(TDS_71)
    data = prelogin_request() + login7_packet(version=TDS_71, user="sa", password="pw")
    data += batch_packet("select @@version", headers=False)

    received = await world.exchange(data)

    assert messages(received) == [
        prelogin_response(),
        login_success(legacy, "FS01"),
        scalar_result(legacy, "", sql_banner(world.host)),
    ]


@run
async def test_a_tds_73_client_and_a_tds_74_client_each_get_their_own_layout(world):
    for version in (TDS_73, TDS_74):
        layout = TdsVersion(version)
        data = login7_packet(version=version) + batch_packet("select 1")

        received = await world.exchange(data)

        assert messages(received) == [login_success(layout, "FS01"), done(layout)]


@run
async def test_a_stream_of_garbage_ends_the_connection_and_the_daemon_keeps_serving(world):
    reader, writer = await asyncio.open_connection(HOST_ADDRESS, world.port, local_addr=(GUEST, 0))
    writer.write(b"\x12\x01" + bytes(range(256)) * 40_000)
    with suppress(ConnectionError):
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 5) == b""
    writer.close()
    await world.settle()

    assert world.log("service-request")[0]["name"] == "malformed tds"

    received = await world.exchange(prelogin_request())
    assert messages(received) == [prelogin_response()]


@run
async def test_a_silent_client_is_dropped_by_the_idle_timeout(world):
    reader, writer = await asyncio.open_connection(HOST_ADDRESS, world.port, local_addr=(GUEST, 0))
    assert await asyncio.wait_for(reader.read(10), 10) == b""
    writer.close()
    await world.settle()

    [request] = world.log("service-request")
    assert request["name"] == "idle-timeout"


@run
async def test_the_log_never_holds_a_raw_control_character(world):
    hostile = "select '\x00\x01\x1b[2J" + chr(0x202E) + chr(0x2028) + "'" + "x" * 3000
    await world.exchange(login7_payload_user("\x07evil\x1b") + batch_packet(hostile))
    await world.settle()

    text = world.layout.log_file(KEY).read_text()
    assert all(ord(character) >= 0x20 or character == "\n" for character in text)


def login7_payload_user(user: str) -> bytes:
    return login7_packet(user=user, password="p\x00q")
