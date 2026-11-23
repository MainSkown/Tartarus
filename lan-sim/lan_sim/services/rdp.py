"""RDP on 3389: negotiates NLA, captures the NTLM exchange inside CredSSP, never grants a session.

A client that offers HYBRID gets TLS with the host's self-signed certificate and a CredSSP
exchange; its NTLM AUTHENTICATE is logged and checked against the host's accounts only to fill in
`success`. The reply is always STATUS_LOGON_FAILURE, so no desktop is ever offered. Clients that do
not offer HYBRID are refused the way an NLA-only server refuses them.
"""

import asyncio
import ssl

from lan_sim import ntlm
from lan_sim.service import Connection
from lan_sim.services.rdp_credssp import (
    SERVER_VERSION,
    STATUS_LOGON_FAILURE,
    build_ts_request,
    parse_ts_request,
    read_ts_request,
)
from lan_sim.services.rdp_format import RdpFormatError
from lan_sim.services.rdp_tls import HostCertificates
from lan_sim.services.rdp_x224 import (
    FAILURE_HYBRID_REQUIRED_BY_SERVER,
    FAILURE_SSL_REQUIRED_BY_SERVER,
    PROTOCOL_HYBRID,
    PROTOCOL_RDP,
    ConnectionRequest,
    connection_confirm,
    connection_failure,
    describe_protocols,
    parse_connection_request,
    read_tpkt,
)

MIN_CREDSSP_VERSION = 2


class RdpService:
    kind = "rdp"

    def __init__(self, certificates: HostCertificates | None = None) -> None:
        self._certificates = certificates or HostCertificates()

    async def serve(self, connection: Connection) -> None:
        try:
            await self._negotiate_and_capture(connection)
        except (RdpFormatError, ntlm.NtlmFormatError) as error:
            connection.log.service_request(name="rdp malformed request", detail=str(error))
        except (ssl.SSLError, OSError) as error:
            connection.log.service_request(
                name="rdp tls handshake failed", detail=type(error).__name__
            )

    async def _negotiate_and_capture(self, connection: Connection) -> None:
        request = parse_connection_request(await read_tpkt(connection.read_exactly))
        connection.log.service_request(name="rdp connection request", detail=_describe(request))
        if not request.requests_hybrid:
            await connection.write(connection_failure(_refusal_for(request)))
            return
        context = await self._certificates.context_for(connection.host.fqdn, connection.clock.now())
        await connection.write(connection_confirm(PROTOCOL_HYBRID))
        await _upgrade_to_tls(connection, context)
        await _capture_credentials(connection)


def _describe(request: ConnectionRequest) -> str:
    cookie = request.cookie if request.cookie is not None else "-"
    return f"cookie={cookie} protocols={describe_protocols(request.requested_protocols)}"


def _refusal_for(request: ConnectionRequest) -> int:
    if request.requested_protocols == PROTOCOL_RDP:
        return FAILURE_SSL_REQUIRED_BY_SERVER
    return FAILURE_HYBRID_REQUIRED_BY_SERVER


async def _upgrade_to_tls(connection: Connection, context: ssl.SSLContext) -> None:
    # The reader keeps its buffer across the upgrade; the handshake itself is not read through
    # `connection.read`, so it gets the idle timeout here.
    async with asyncio.timeout(connection.limits.idle_timeout_seconds):
        await connection.writer.start_tls(context)


async def _capture_credentials(connection: Connection) -> None:
    challenge = ntlm.new_challenge()
    negotiate = await _read_ts_request(connection)
    token = negotiate.nego_token
    if token is None or _ntlm_message(token, ntlm.NEGOTIATE_MESSAGE) is None:
        raise RdpFormatError("the first CredSSP message has no NTLM NEGOTIATE")
    version = max(MIN_CREDSSP_VERSION, min(negotiate.version, SERVER_VERSION))
    reply = ntlm.challenge_message(connection.host, challenge, connection.clock)
    wrapped = not token.startswith(ntlm.NTLMSSP_SIGNATURE)
    await connection.write(
        build_ts_request(version, nego_token=ntlm.spnego_challenge(reply) if wrapped else reply)
    )

    authenticate = (await _read_ts_request(connection)).nego_token
    message = (
        None if authenticate is None else _ntlm_message(authenticate, ntlm.AUTHENTICATE_MESSAGE)
    )
    if message is None:
        raise RdpFormatError("the second CredSSP message has no NTLM AUTHENTICATE")
    attempt = ntlm.parse_authenticate(message, challenge)
    verdict = ntlm.verify(attempt, connection.host)
    connection.log.login_attempt(
        user=attempt.user,
        domain=attempt.domain,
        mechanism="ntlm",
        secret=attempt.hashcat,
        success=verdict.verified,
    )
    await connection.write(build_ts_request(version, error_code=STATUS_LOGON_FAILURE))


async def _read_ts_request(connection: Connection):
    return parse_ts_request(await read_ts_request(connection.read_exactly))


def _ntlm_message(token: bytes, expected_type: int) -> bytes | None:
    message = ntlm.unwrap_ntlmssp(token)
    if message is None or ntlm.ntlm_message_type(message) != expected_type:
        return None
    return message


SERVICE = RdpService()
