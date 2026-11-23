"""LDAP binds: anonymous, simple and the NTLM forms (SASL GSS-SPNEGO and Microsoft's sicily).

A simple bind succeeds only for an account the host lists, with that exact password. An NTLM bind
is captured and refused: LDAP NTLM binds ask for a signed and sealed channel the fake host cannot
give, and a real DC rejects an account whose password it does not know the same way.
"""

import hmac
import re
from dataclasses import dataclass
from typing import Any

from ldap3.protocol.rfc4511 import BindResponse, ServerSaslCreds

from lan_sim.identity import account_for
from lan_sim.ntlm import (
    AUTHENTICATE_MESSAGE,
    NEGOTIATE_MESSAGE,
    NtlmFormatError,
    challenge_message,
    new_challenge,
    ntlm_message_type,
    parse_authenticate,
    spnego_challenge,
    unwrap_ntlmssp,
    verify,
)
from lan_sim.service import Connection
from lan_sim.services.ldap_ber import build_result

SUCCESS = 0
PROTOCOL_ERROR = 2
SASL_BIND_IN_PROGRESS = 14
AUTH_METHOD_NOT_SUPPORTED = 7
INVALID_CREDENTIALS = 49
UNWILLING_TO_PERFORM = 53
SUPPORTED_VERSIONS = (2, 3)
NTLM_SASL_MECHANISMS = ("GSS-SPNEGO", "NTLM")
SICILY_PACKAGES = b"NTLM"
MAX_NAME_CHARACTERS = 1024
# What a Windows DC says for a bad password; the same text for every refusal.
WINDOWS_REFUSAL = (
    "80090308: LdapErr: DSID-0C090569, comment: AcceptSecurityContext error, data 52e, v4563"
)
DN_LOGIN = re.compile(r"(?:cn|uid)=([^,]+)", re.IGNORECASE)


@dataclass
class BindState:
    """What an NTLM exchange remembers between its two binds: the challenge it issued."""

    challenge: bytes | None = None


@dataclass(frozen=True)
class Identity:
    user: str
    domain: str


def handle_bind(connection: Connection, request: Any, state: BindState) -> Any:
    """The `BindResponse` to a `BindRequest`."""
    if int(request["version"]) not in SUPPORTED_VERSIONS:
        return build_result(BindResponse, PROTOCOL_ERROR, "unsupported LDAP version")
    name = bytes(request["name"])
    authentication = request["authentication"]
    kind = authentication.getName()
    if kind == "simple":
        return _simple_bind(connection, name, bytes(authentication["simple"]))
    if kind == "sasl":
        return _sasl_bind(connection, authentication["sasl"], state)
    if kind == "sicilyPackageDiscovery":
        return build_result(BindResponse, SUCCESS, matched_dn=SICILY_PACKAGES)
    return _sicily_bind(connection, bytes(authentication[kind]), state)


def identity_of(name: str) -> Identity:
    """The account a client names: `DOMAIN\\user`, `user@domain`, a DN, or the bare user."""
    name = name[:MAX_NAME_CHARACTERS]
    if "\\" in name:
        domain, _, user = name.partition("\\")
        return Identity(user, domain)
    if "@" in name:
        user, _, domain = name.partition("@")
        return Identity(user, domain)
    first_rdn = DN_LOGIN.match(name)
    return Identity(first_rdn.group(1).strip() if first_rdn else name, "")


def _simple_bind(connection: Connection, name: bytes, password: bytes) -> Any:
    if not name and not password:
        return build_result(BindResponse, SUCCESS)
    identity = identity_of(name.decode("utf-8", errors="replace"))
    account = account_for(connection.host, identity.user)
    # RFC 4513 5.1.2: a name with no password is an unauthenticated bind, never a success.
    known_password = bool(password) and account is not None
    verified = known_password and hmac.compare_digest(password, account[1].encode())  # type: ignore[index]
    connection.log.login_attempt(
        user=identity.user,
        domain=identity.domain,
        mechanism="ldap-simple",
        secret=password.decode("utf-8", errors="replace"),
        success=verified,
    )
    if verified:
        return build_result(BindResponse, SUCCESS)
    if not password:
        return build_result(BindResponse, UNWILLING_TO_PERFORM, "unauthenticated bind refused")
    return _refused()


def _sasl_bind(connection: Connection, sasl: Any, state: BindState) -> Any:
    mechanism = bytes(sasl["mechanism"]).decode("utf-8", errors="replace")
    if mechanism.upper() not in NTLM_SASL_MECHANISMS:
        return build_result(BindResponse, AUTH_METHOD_NOT_SUPPORTED, "SASL mechanism not supported")
    credentials = bytes(sasl["credentials"]) if sasl["credentials"].hasValue() else b""
    ntlm_message = unwrap_ntlmssp(credentials)
    if ntlm_message is None:
        return build_result(BindResponse, AUTH_METHOD_NOT_SUPPORTED, "no NTLM mechanism offered")
    wrapped = ntlm_message != credentials
    return _ntlm_step(connection, ntlm_message, state, _sasl_challenge(wrapped))


def _sasl_challenge(wrapped: bool) -> Any:
    def reply(challenge: bytes) -> Any:
        body = build_result(BindResponse, SASL_BIND_IN_PROGRESS)
        body["serverSaslCreds"] = ServerSaslCreds(
            spnego_challenge(challenge) if wrapped else challenge
        )
        return body

    return reply


def _sicily_bind(connection: Connection, ntlm_message: bytes, state: BindState) -> Any:
    def reply(challenge: bytes) -> Any:
        return build_result(BindResponse, SUCCESS, matched_dn=challenge)

    return _ntlm_step(connection, ntlm_message, state, reply)


def _ntlm_step(
    connection: Connection, message: bytes, state: BindState, challenge_reply: Any
) -> Any:
    try:
        message_type = ntlm_message_type(message)
    except NtlmFormatError:
        return _refused()
    if message_type == NEGOTIATE_MESSAGE:
        state.challenge = new_challenge()
        return challenge_reply(
            challenge_message(connection.host, state.challenge, connection.clock)
        )
    if message_type == AUTHENTICATE_MESSAGE and state.challenge is not None:
        challenge, state.challenge = state.challenge, None
        _log_ntlm_attempt(connection, message, challenge)
    return _refused()


def _log_ntlm_attempt(connection: Connection, message: bytes, challenge: bytes) -> None:
    try:
        attempt = parse_authenticate(message, challenge)
    except NtlmFormatError:
        return
    verdict = verify(attempt, connection.host)
    connection.log.login_attempt(
        user=attempt.user,
        domain=attempt.domain,
        mechanism="ntlm",
        secret=attempt.hashcat,
        success=verdict.verified,
    )


def _refused() -> Any:
    return build_result(BindResponse, INVALID_CREDENTIALS, WINDOWS_REFUSAL)
