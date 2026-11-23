"""What the SMB tests share: a daemon serving the SMB service on loopback and impacket's client.

The daemon runs on its own thread and event loop so the blocking client can be used as it is.
Ports are free high ports, never 445. impacket's client cannot choose its source address, so the
session's guest is 127.0.0.1 and the fake host is 127.0.0.3.
"""

import asyncio
import itertools
import json
import threading
from dataclasses import replace

from impacket.smbconnection import SMBConnection
from support import free_port

from lan_session import (
    HostSpec,
    Layout,
    ServiceSpec,
    SessionSpec,
    publish_session,
    wait_for_status,
)
from lan_sim.daemon import Daemon
from lan_sim.limits import Limits
from lan_sim.services import smb as smb_service
from lan_sim.services.smb_signing import signature_matches

GUEST = "127.0.0.1"
HOST_ADDRESS = "127.0.0.3"
_worlds = itertools.count(1)
FQDN = "fs01.corp.local"
USER = "Administrator"
PASSWORD = "Passw0rd!"
DOMAIN = "CORP"
MIB = 1024 * 1024


class SmbWorld:
    """One session with one SMB host, served by the real daemon; use as a context manager."""

    def __init__(
        self,
        tmp_path,
        *,
        shares=(),
        accounts=((USER, PASSWORD),),
        smb_implementation=None,
        **limits,
    ):
        self.key = f"task-{next(_worlds)}"
        self.layout = Layout(tmp_path / "root")
        self.layout.make_directories()
        self.port = free_port(HOST_ADDRESS)
        options = {"shares": list(shares)} if shares else {}
        service = ServiceSpec("smb", self.port, options)
        self.host = HostSpec(FQDN, HOST_ADDRESS, "Windows Server 2019", accounts, (service,))
        self.daemon = Daemon(
            self.layout,
            {"smb": smb_implementation or smb_service.SERVICE},
            limits=replace(Limits(), **limits),
            poll_interval=0.02,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> "SmbWorld":
        publish_session(self.layout, SessionSpec(self.key, GUEST, "small-office", (self.host,)))
        self._thread.start()
        status = wait_for_status(self.layout, self.key, {"listening", "failed"}, timeout=10)
        assert status is not None, status
        assert status.state == "listening", status
        return self

    def __exit__(self, *exc) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self.daemon.request_stop)
        self._thread.join(timeout=10)

    def _serve(self) -> None:
        async def main():
            self._loop = asyncio.get_running_loop()
            await self.daemon.run()

        asyncio.run(main())

    def client(self, *, user=USER, password=PASSWORD, domain=DOMAIN, login=True, **options):
        options.setdefault("timeout", 10)
        smb = SMBConnection(FQDN, HOST_ADDRESS, sess_port=self.port, **options)
        if login:
            smb.login(user, password, domain)
        return smb

    def records(self, event_type: str) -> list[dict]:
        path = self.layout.log_file(self.key)
        lines = path.read_text().splitlines() if path.exists() else []
        return [r for r in map(json.loads, lines) if r["type"] == event_type]

    def requests(self, name: str) -> list[dict]:
        return [r for r in self.records("service-request") if r["name"] == name]


class SignatureAudit:
    """Verifies the signature of every response impacket's client receives; it never does."""

    def __init__(self, smb: SMBConnection) -> None:
        self.verified = 0
        self.unsigned = 0
        self.failed: list[int] = []
        self._pending: list = []
        self._server = smb.getSMBServer()
        original = self._server.recvSMB

        def recv(packet_id=None):
            packet = original(packet_id)
            self._pending.append(packet)
            self.settle()
            return packet

        self._server.recvSMB = recv

    def settle(self) -> None:
        session = self._server._Session
        key = session["SigningKey"] or session["SessionKey"]
        if not session["SessionKey"]:
            return
        dialect = self._server._Connection["Dialect"]
        for packet in self._pending:
            self._check(packet, dialect, key)
        self._pending.clear()

    def _check(self, packet, dialect: int, key: bytes) -> None:
        if not packet["Flags"] & 0x8:
            # The interim reply of the session setup is unsigned by definition.
            self.unsigned += packet["Status"] == 0
        elif signature_matches(dialect, key, bytes(packet.rawData)):
            self.verified += 1
        else:
            self.failed.append(packet["MessageID"])
