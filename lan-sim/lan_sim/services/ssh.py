"""SSH 22: asyncssh's server, which accepts any password and runs nothing.

Every login attempt, public-key attempt and exec request is logged, and the client is told the
command succeeded. Shells, subsystems and forwarding are refused or closed at once. The host key is
made in memory per host name and never written to disk.
"""

import asyncio
import socket
from collections.abc import Callable

import asyncssh

from lan_session import HostSpec, ServiceSpec
from lan_sim.service import Connection
from lan_sim.services.ssh_bridge import relay_through_socket
from lan_sim.session_log import ConnectionLog

DEFAULT_BANNER = "OpenSSH_8.9p1 Ubuntu-3ubuntu0.10"
MAX_BANNER_LENGTH = 128
MAX_EXEC_DETAIL_LENGTH = 500
LOGIN_TIMEOUT_SECONDS = 30.0
LOGIN_LIFETIME_SECONDS = 30.0
PUBLIC_KEY_FAILURES_ALLOWED = 3

_host_keys: dict[str, asyncssh.SSHKey] = {}


def host_key_of(host: HostSpec) -> asyncssh.SSHKey:
    if host.fqdn not in _host_keys:
        _host_keys[host.fqdn] = asyncssh.generate_private_key("ssh-ed25519")
    return _host_keys[host.fqdn]


def banner_of(service: ServiceSpec) -> str:
    banner = service.options.get("banner", DEFAULT_BANNER)
    if not _is_printable_banner(banner):
        raise ValueError("banner must be 1 to 128 printable ASCII characters")
    return banner


def _is_printable_banner(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_BANNER_LENGTH
        and value.isascii()
        and value.isprintable()
    )


class _SshServer(asyncssh.SSHServer):
    def __init__(self, log: ConnectionLog, closed: asyncio.Future[None]) -> None:
        self._log = log
        self._closed = closed
        self._connection: asyncssh.SSHServerConnection | None = None
        self._failed_public_keys = 0

    def connection_made(self, connection: asyncssh.SSHServerConnection) -> None:
        self._connection = connection

    def connection_lost(self, _exc: Exception | None) -> None:
        if not self._closed.done():
            self._closed.set_result(None)

    def begin_auth(self, _username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        self._log.login_attempt(
            user=username, domain="", mechanism="password", secret=password, success=True
        )
        return True

    def public_key_auth_supported(self) -> bool:
        return True

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        self._log.login_attempt(
            user=username,
            domain="",
            mechanism="publickey",
            secret=key.get_fingerprint(),
            success=False,
        )
        self._failed_public_keys += 1
        if self._failed_public_keys >= PUBLIC_KEY_FAILURES_ALLOWED and self._connection:
            self._connection.close()
        return False

    def auth_completed(self) -> None:
        if self._connection:
            asyncio.get_running_loop().call_later(LOGIN_LIFETIME_SECONDS, self._connection.close)


def _exec_only(log: ConnectionLog) -> Callable[[asyncssh.SSHServerProcess], None]:
    def start(process: asyncssh.SSHServerProcess) -> None:
        if process.command is not None:
            log.service_request(name="ssh exec", detail=process.command[:MAX_EXEC_DETAIL_LENGTH])
        process.exit(0)

    return start


async def _serve_library(
    log: ConnectionLog, library_socket: socket.socket, banner: str, host_key: asyncssh.SSHKey
) -> None:
    closed: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    try:
        await asyncssh.run_server(
            library_socket,
            server_factory=lambda: _SshServer(log, closed),
            server_host_keys=[host_key],
            server_version=banner,
            process_factory=_exec_only(log),
            login_timeout=LOGIN_TIMEOUT_SECONDS,
            authorized_client_keys=None,
        )
        await closed
    except asyncssh.Error:
        return


class SshService:
    kind = "ssh"

    async def serve(self, connection: Connection) -> None:
        banner = banner_of(connection.service)
        host_key = host_key_of(connection.host)
        await relay_through_socket(
            connection,
            lambda library_socket: _serve_library(connection.log, library_socket, banner, host_key),
        )


SERVICE = SshService()
