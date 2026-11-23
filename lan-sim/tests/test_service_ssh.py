"""The SSH service with asyncssh's client, over real sockets through the daemon."""

import asyncio

import asyncssh
import pytest
from support import free_port
from test_daemon import GUEST_A, HOST_1, HOST_2, World

from lan_session import HostSpec, ServiceSpec, SessionSpec, SessionStatus
from lan_sim.services import ssh
from lan_sim.services.ssh import SERVICE

KEY = "ssh-1"
BANNER_DEFAULT = b"SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.10\r\n"


def run(tmp_path, body, **limits):
    async def main():
        world = World(tmp_path, services={SERVICE.kind: SERVICE}, **limits)
        try:
            await body(world)
        finally:
            await world.daemon.shutdown()

    asyncio.run(main())


def ssh_host(address=HOST_1, options=None, fqdn="fs01.corp.local"):
    service = ServiceSpec("ssh", free_port(address), options or {})
    return HostSpec(fqdn, address, "Windows", (("admin", "pw"),), (service,))


def ssh_session(*hosts):
    return SessionSpec(KEY, GUEST_A, "small-office", tuple(hosts))


async def open_session(world, *hosts):
    assert await world.open(ssh_session(*hosts)) == SessionStatus("listening")
    return [(host.address, host.services[0].port) for host in hosts]


async def login(address, port, *, user="Administrator", password="anything", **options):
    return await asyncssh.connect(
        address,
        port,
        username=user,
        password=password,
        preferred_auth="password",
        client_keys=None,
        agent_path=None,
        known_hosts=None,
        local_addr=(GUEST_A, 0),
        **options,
    )


async def close(connection):
    connection.close()
    await connection.wait_closed()


async def logged(world, event_type):
    await world.settle(KEY)
    return world.log_of_type(KEY, event_type)


def test_password_login_succeeds_with_any_password_and_is_logged(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        connection = await login(address, port, password="whatever-it-is")
        await close(connection)

        [attempt] = await logged(world, "login-attempt")
        assert attempt["user"] == "Administrator"
        assert attempt["domain"] == ""
        assert attempt["mechanism"] == "password"
        assert attempt["secret"] == "whatever-it-is"
        assert attempt["success"] is True
        assert attempt["host"] == "fs01.corp.local"
        assert attempt["service"] == "ssh"
        assert attempt["src"]["ip"] == GUEST_A

    run(tmp_path, body)


def test_exec_command_exits_zero_with_no_output_and_is_logged(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        connection = await login(address, port)
        result = await connection.run("whoami", check=False)
        await close(connection)

        assert result.exit_status == 0
        assert result.stdout == ""
        assert result.stderr == ""
        [request] = await logged(world, "service-request")
        assert request["name"] == "ssh exec"
        assert request["detail"] == "whoami"

    run(tmp_path, body)


def test_shell_and_pty_requests_close_the_channel_at_once(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        connection = await login(address, port)
        for request in ({}, {"term_type": "xterm"}):
            process = await connection.create_process(**request)
            result = await asyncio.wait_for(process.wait(), 5)
            assert result.exit_status == 0
        await close(connection)

    run(tmp_path, body)


def test_sftp_subsystem_is_refused(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        connection = await login(address, port)
        with pytest.raises(asyncssh.Error, match="Session request failed"):
            await connection.start_sftp_client()
        await close(connection)

    run(tmp_path, body)


def test_port_forwarding_is_refused(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        connection = await login(address, port)
        with pytest.raises(asyncssh.ChannelOpenError):
            await connection.open_connection("127.0.0.1", 9)
        with pytest.raises(asyncssh.ChannelListenError):
            await connection.forward_remote_port("", 0, "127.0.0.1", 9)
        await close(connection)

    run(tmp_path, body)


def test_publickey_attempt_is_logged_with_its_fingerprint_and_refused(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        key = asyncssh.generate_private_key("ssh-ed25519")
        with pytest.raises(asyncssh.PermissionDenied):
            await asyncssh.connect(
                address,
                port,
                username="Administrator",
                client_keys=[key],
                preferred_auth="publickey",
                agent_path=None,
                known_hosts=None,
                local_addr=(GUEST_A, 0),
            )

        [attempt] = await logged(world, "login-attempt")
        assert attempt["mechanism"] == "publickey"
        assert attempt["secret"] == key.get_fingerprint()
        assert attempt["success"] is False

    run(tmp_path, body)


def test_three_failed_publickey_attempts_end_the_connection(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        keys = [asyncssh.generate_private_key("ssh-ed25519") for _ in range(4)]
        with pytest.raises(asyncssh.Error):
            await asyncssh.connect(
                address,
                port,
                username="Administrator",
                client_keys=keys,
                preferred_auth="publickey",
                agent_path=None,
                known_hosts=None,
                local_addr=(GUEST_A, 0),
            )

        attempts = await logged(world, "login-attempt")
        assert [attempt["secret"] for attempt in attempts] == [
            key.get_fingerprint() for key in keys[:3]
        ]
        assert not any(attempt["success"] for attempt in attempts)

    run(tmp_path, body)


def test_banner_option_sets_the_version_string_and_the_default_applies_without_it(tmp_path):
    async def body(world):
        default_host = ssh_host(HOST_1)
        custom_host = ssh_host(
            HOST_2, options={"banner": "dropbear_2022.83"}, fqdn="fs02.corp.local"
        )
        default_at, custom_at = await open_session(world, default_host, custom_host)
        assert await first_line(default_at) == BANNER_DEFAULT
        assert await first_line(custom_at) == b"SSH-2.0-dropbear_2022.83\r\n"

    run(tmp_path, body)


def test_a_banner_that_is_not_printable_ascii_ends_the_connection_with_a_service_error(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(
            world, ssh_host(options={"banner": "bad\u00e9banner"})
        )
        assert await first_line((address, port)) == b""
        [error] = await logged(world, "service-request")
        assert error["name"] == "service-error"
        assert error["detail"] == "ValueError"

    run(tmp_path, body)


def test_host_key_is_stable_within_a_host_and_differs_between_hosts(tmp_path):
    async def body(world):
        first, second = await open_session(
            world, ssh_host(HOST_1), ssh_host(HOST_2, fqdn="fs02.corp.local")
        )
        fingerprints = []
        for address, port in (first, first, second):
            connection = await login(address, port)
            fingerprints.append(connection.get_server_host_key().get_fingerprint())
            await close(connection)

        assert fingerprints[0] == fingerprints[1]
        assert fingerprints[0] != fingerprints[2]

    run(tmp_path, body)


def test_a_logged_in_connection_ends_after_the_login_lifetime(tmp_path, monkeypatch):
    monkeypatch.setattr(ssh, "LOGIN_LIFETIME_SECONDS", 0.5)

    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        connection = await login(address, port)
        await asyncio.wait_for(connection.wait_closed(), 5)

    run(tmp_path, body)


def test_an_exec_command_is_cut_to_500_characters_in_the_log(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        connection = await login(address, port)
        await connection.run("A" * 2000, check=False)
        await close(connection)

        [request] = await logged(world, "service-request")
        assert request["detail"] == "A" * 500

    run(tmp_path, body)


def test_control_characters_from_the_client_never_reach_the_log(tmp_path):
    async def body(world):
        [(address, port)] = await open_session(world, ssh_host())
        connection = await login(address, port)
        await connection.run("echo\x1b[31m\x07", check=False)
        await close(connection)

        [request] = await logged(world, "service-request")
        assert request["detail"] == "echo[31m"
        text = world.layout.log_file(KEY).read_text(encoding="ascii")
        assert all(ord(character) >= 0x20 for character in text if character != "\n")

    run(tmp_path, body)


async def first_line(address_and_port) -> bytes:
    reader, writer = await asyncio.open_connection(*address_and_port, local_addr=(GUEST_A, 0))
    try:
        return await asyncio.wait_for(reader.readline(), 5)
    finally:
        writer.close()
