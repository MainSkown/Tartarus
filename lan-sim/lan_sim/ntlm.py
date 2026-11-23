"""NTLM for every service that authenticates with it (SMB, RDP, WinRM, LDAP, MSSQL), written once.

The server side only: build the CHALLENGE_MESSAGE a Windows Server 2019 host would send, parse the
client's AUTHENTICATE_MESSAGE strictly (it is hostile input), render the hash for hashcat, and
check the response against the host's known accounts. impacket supplies the message structures and
the hashing primitives; the parsing of untrusted bytes is ours, so a malformed message is always an
`NtlmFormatError` and never an exception from inside a library.
"""

import hmac
import secrets
import struct
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from impacket import ntlm, spnego

from lan_session import HostSpec
from lan_sim.clock import Clock
from lan_sim.identity import account_for, dns_domain, netbios_domain, netbios_name

CHALLENGE_BYTES = 8
MAX_NTLM_BYTES = 16 * 1024
MAX_SPNEGO_BYTES = MAX_NTLM_BYTES + 512
MAX_NAME_BYTES = 1024
SESSION_KEY_BYTES = 16
FIRST_PRINTABLE = 0x20
DELETE = 0x7F

NTLMSSP_SIGNATURE = b"NTLMSSP\x00"
NEGOTIATE_MESSAGE = 1
CHALLENGE_MESSAGE = 2
AUTHENTICATE_MESSAGE = 3

# Windows Server 2019: major 10, minor 0, build 17763, NTLM revision 15.
WINDOWS_SERVER_2019_VERSION = bytes.fromhex("0a0063450000000f")

SERVER_FLAGS = (
    ntlm.NTLMSSP_NEGOTIATE_UNICODE
    | ntlm.NTLMSSP_REQUEST_TARGET
    | ntlm.NTLMSSP_NEGOTIATE_SIGN
    | ntlm.NTLMSSP_NEGOTIATE_NTLM
    | ntlm.NTLMSSP_NEGOTIATE_ALWAYS_SIGN
    | ntlm.NTLMSSP_TARGET_TYPE_SERVER
    | ntlm.NTLMSSP_NEGOTIATE_EXTENDED_SESSIONSECURITY
    | ntlm.NTLMSSP_NEGOTIATE_TARGET_INFO
    | ntlm.NTLMSSP_NEGOTIATE_VERSION
    | ntlm.NTLMSSP_NEGOTIATE_128
    | ntlm.NTLMSSP_NEGOTIATE_KEY_EXCH
    | ntlm.NTLMSSP_NEGOTIATE_56
)

CHALLENGE_HEADER_BYTES = 8 + 4 + 8 + 4 + 8 + 8 + 8 + 8
AUTHENTICATE_HEADER = struct.Struct("<8sI" + "HHI" * 6 + "I")
LM_RESPONSE_LENGTHS = (0, 1, 24)
NTLMV1_RESPONSE_BYTES = 24
NTLMV2_MINIMUM_RESPONSE_BYTES = 16 + 28 + 4
WINDOWS_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
FILETIME_TICKS_PER_SECOND = 10_000_000
FILETIME_TICKS_PER_MICROSECOND = 10

SPNEGO_ACCEPT_COMPLETED = b"\x00"
SPNEGO_ACCEPT_INCOMPLETE = b"\x01"
SPNEGO_REJECT = b"\x02"


class NtlmFormatError(ValueError):
    """The bytes are not an NTLM message this server accepts."""


@dataclass(frozen=True)
class NtlmAttempt:
    """What a client's AUTHENTICATE_MESSAGE says, with the pieces `verify` needs.

    `hashcat` is the NetNTLMv2 line (mode 5600), or the NetNTLMv1 line (mode 5500) when the client
    sent v1, or empty when there is no NT response to crack (anonymous, LMv2 only).
    """

    user: str
    domain: str
    workstation: str
    hashcat: str
    is_v2: bool
    anonymous: bool
    challenge: bytes
    lm_response: bytes
    nt_response: bytes
    flags: int
    encrypted_session_key: bytes


@dataclass(frozen=True)
class NtlmVerdict:
    known_account: bool
    verified: bool
    session_base_key: bytes | None


def new_challenge(random_source: Callable[[int], bytes] = secrets.token_bytes) -> bytes:
    challenge = random_source(CHALLENGE_BYTES)
    if len(challenge) != CHALLENGE_BYTES:
        raise ValueError(f"a challenge is {CHALLENGE_BYTES} bytes")
    return challenge


def challenge_message(host: HostSpec, challenge: bytes, clock: Clock) -> bytes:
    """The CHALLENGE_MESSAGE naming `host`, advertising signing and extended session security."""
    if len(challenge) != CHALLENGE_BYTES:
        raise ValueError(f"a challenge is {CHALLENGE_BYTES} bytes")
    computer = netbios_name(host)
    target_name = computer.encode("utf-16le")
    message = ntlm.NTLMAuthChallenge()
    message["flags"] = SERVER_FLAGS
    message["challenge"] = challenge
    message["Version"] = WINDOWS_SERVER_2019_VERSION
    message["domain_name"] = target_name
    message["domain_len"] = message["domain_max_len"] = len(target_name)
    message["domain_offset"] = CHALLENGE_HEADER_BYTES
    target_info = _target_info(host, clock)
    message["TargetInfoFields"] = target_info
    message["TargetInfoFields_len"] = message["TargetInfoFields_max_len"] = len(target_info)
    message["TargetInfoFields_offset"] = CHALLENGE_HEADER_BYTES + len(target_name)
    return bytes(message.getData())


def parse_authenticate(blob: bytes, challenge: bytes) -> NtlmAttempt:
    """The client's AUTHENTICATE_MESSAGE as an attempt; `NtlmFormatError` for anything malformed."""
    if len(challenge) != CHALLENGE_BYTES:
        raise ValueError(f"a challenge is {CHALLENGE_BYTES} bytes")
    if len(blob) > MAX_NTLM_BYTES:
        raise NtlmFormatError(f"an NTLM message is at most {MAX_NTLM_BYTES} bytes")
    if len(blob) < AUTHENTICATE_HEADER.size:
        raise NtlmFormatError("the AUTHENTICATE_MESSAGE header is cut short")
    header = AUTHENTICATE_HEADER.unpack_from(blob)
    if header[0] != NTLMSSP_SIGNATURE or header[1] != AUTHENTICATE_MESSAGE:
        raise NtlmFormatError("not an AUTHENTICATE_MESSAGE")
    flags = header[-1]
    lm_response, nt_response, domain, user, workstation, session_key = _payloads(blob, header)
    _check_responses(lm_response, nt_response, session_key)
    names = [_name(raw, flags) for raw in (user, domain, workstation)]
    anonymous = not user and not nt_response and lm_response in (b"", b"\x00")
    return NtlmAttempt(
        user=names[0],
        domain=names[1],
        workstation=names[2],
        hashcat=_hashcat_line(names[0], names[1], challenge, lm_response, nt_response),
        is_v2=len(nt_response) > NTLMV1_RESPONSE_BYTES,
        anonymous=anonymous,
        challenge=challenge,
        lm_response=lm_response,
        nt_response=nt_response,
        flags=flags,
        encrypted_session_key=session_key,
    )


def verify(attempt: NtlmAttempt, host: HostSpec) -> NtlmVerdict:
    """Whether the response proves knowledge of the password of one of `host`'s accounts.

    Only NTLMv2 is verified. NTLMv1 and LMv2-only responses are never verified in v1 (an account
    may be known, the login is still refused): Windows 10 and 11 clients send NTLMv2 by default.
    `session_base_key` is set only for a verified login: it is the key the SMB signing key derives
    from, so a wrong password must not yield one.
    """
    account = account_for(host, attempt.user)
    if account is None:
        return NtlmVerdict(known_account=False, verified=False, session_base_key=None)
    unverified = NtlmVerdict(known_account=True, verified=False, session_base_key=None)
    if not attempt.is_v2:
        return unverified
    try:
        response_key = ntlm.NTOWFv2(attempt.user, account[1], attempt.domain)
    except UnicodeError:
        return unverified
    proof, client_blob = attempt.nt_response[:16], attempt.nt_response[16:]
    expected = ntlm.hmac_md5(response_key, attempt.challenge + client_blob)
    if not hmac.compare_digest(proof, expected):
        return unverified
    return NtlmVerdict(
        known_account=True, verified=True, session_base_key=ntlm.hmac_md5(response_key, proof)
    )


def exported_session_key(attempt: NtlmAttempt, session_base_key: bytes) -> bytes:
    """The key both sides sign with: the client's random key unwrapped, or the base key itself.

    With key exchange negotiated the client sends a random key RC4-encrypted under the NTLMv2 base
    key. Valid for verified NTLMv2 attempts only.
    """
    if attempt.flags & ntlm.NTLMSSP_NEGOTIATE_KEY_EXCH and (
        len(attempt.encrypted_session_key) == SESSION_KEY_BYTES
    ):
        # RC4 is symmetric: encrypting the encrypted key decrypts it.
        return bytes(
            ntlm.generateEncryptedSessionKey(session_base_key, attempt.encrypted_session_key)
        )
    return session_base_key


def ntlm_message_type(blob: bytes) -> int:
    if len(blob) < len(NTLMSSP_SIGNATURE) + 4 or not blob.startswith(NTLMSSP_SIGNATURE):
        raise NtlmFormatError("not an NTLMSSP message")
    message_type = struct.unpack_from("<I", blob, len(NTLMSSP_SIGNATURE))[0]
    if message_type not in (NEGOTIATE_MESSAGE, CHALLENGE_MESSAGE, AUTHENTICATE_MESSAGE):
        raise NtlmFormatError(f"unknown NTLM message type {message_type}")
    return int(message_type)


def unwrap_ntlmssp(data: bytes) -> bytes | None:
    """The NTLM message inside a SPNEGO token, or `data` itself when it is a raw NTLM message.

    Tolerant on purpose: it finds the NTLMSSP signature instead of walking the ASN.1, because
    clients wrap the message in NegTokenInit, NegTokenResp or nothing at all. Bytes after the
    message (a mechListMIC) are kept; the parsers address fields by offset and ignore them.
    """
    if len(data) > MAX_SPNEGO_BYTES:
        return None
    start = data.find(NTLMSSP_SIGNATURE)
    return data[start:] if start >= 0 else None


def spnego_challenge(ntlm_blob: bytes) -> bytes:
    """NegTokenResp, accept-incomplete, carrying the CHALLENGE_MESSAGE."""
    token = spnego.SPNEGO_NegTokenResp()
    token["NegState"] = SPNEGO_ACCEPT_INCOMPLETE
    token["SupportedMech"] = spnego.TypesMech["NTLMSSP - Microsoft NTLM Security Support Provider"]
    token["ResponseToken"] = ntlm_blob
    return bytes(token.getData())


def spnego_accept() -> bytes:
    """NegTokenResp, accept-completed: the final reply to a verified login."""
    return _spnego_state(SPNEGO_ACCEPT_COMPLETED)


def spnego_reject() -> bytes:
    """NegTokenResp, reject: the final reply to a login that failed."""
    return _spnego_state(SPNEGO_REJECT)


def _spnego_state(state: bytes) -> bytes:
    token = spnego.SPNEGO_NegTokenResp()
    token["NegState"] = state
    return bytes(token.getData())


def _target_info(host: HostSpec, clock: Clock) -> bytes:
    pairs = ntlm.AV_PAIRS()
    pairs[ntlm.NTLMSSP_AV_DOMAINNAME] = netbios_domain(host).encode("utf-16le")
    pairs[ntlm.NTLMSSP_AV_HOSTNAME] = netbios_name(host).encode("utf-16le")
    pairs[ntlm.NTLMSSP_AV_DNS_DOMAINNAME] = dns_domain(host).encode("utf-16le")
    pairs[ntlm.NTLMSSP_AV_DNS_HOSTNAME] = host.fqdn.encode("utf-16le")
    pairs[ntlm.NTLMSSP_AV_DNS_TREENAME] = dns_domain(host).encode("utf-16le")
    pairs[ntlm.NTLMSSP_AV_TIME] = struct.pack("<Q", _filetime(clock.now()))
    return bytes(pairs.getData())


def _filetime(moment: datetime) -> int:
    elapsed = moment - WINDOWS_EPOCH
    return (
        elapsed.days * 86400 + elapsed.seconds
    ) * FILETIME_TICKS_PER_SECOND + elapsed.microseconds * FILETIME_TICKS_PER_MICROSECOND


def _payloads(blob: bytes, header: tuple[Any, ...]) -> list[bytes]:
    """The six fields after the type: each header triple is (length, maximum length, offset)."""
    triples = (header[start : start + 3] for start in range(2, 20, 3))
    return [_payload(blob, length, offset) for length, _, offset in triples]


def _payload(blob: bytes, length: int, offset: int) -> bytes:
    if length == 0:
        return b""
    if offset < AUTHENTICATE_HEADER.size or offset + length > len(blob):
        raise NtlmFormatError("a field points outside the message")
    return blob[offset : offset + length]


def _check_responses(lm_response: bytes, nt_response: bytes, session_key: bytes) -> None:
    if len(lm_response) not in LM_RESPONSE_LENGTHS:
        raise NtlmFormatError("the LM response has an impossible length")
    if len(nt_response) not in (0, NTLMV1_RESPONSE_BYTES) and (
        len(nt_response) < NTLMV2_MINIMUM_RESPONSE_BYTES
    ):
        raise NtlmFormatError("the NT response has an impossible length")
    if len(session_key) not in (0, SESSION_KEY_BYTES):
        raise NtlmFormatError("the encrypted session key has an impossible length")


def _name(raw: bytes, flags: int) -> str:
    if len(raw) > MAX_NAME_BYTES:
        raise NtlmFormatError("a name is too long")
    unicode_names = bool(flags & ntlm.NTLMSSP_NEGOTIATE_UNICODE)
    if unicode_names and len(raw) % 2:
        raise NtlmFormatError("a UTF-16 name has an odd length")
    try:
        text = raw.decode("utf-16le" if unicode_names else "latin-1")
    except UnicodeDecodeError as error:
        raise NtlmFormatError("a name is not valid UTF-16") from error
    if any(_forbidden_in_name(character) for character in text):
        raise NtlmFormatError("a name contains a control character or a colon")
    return text


def _forbidden_in_name(character: str) -> bool:
    """Control characters and the hashcat line's separator."""
    return ord(character) < FIRST_PRINTABLE or ord(character) == DELETE or character == ":"


def _hashcat_line(
    user: str, domain: str, challenge: bytes, lm_response: bytes, nt_response: bytes
) -> str:
    if len(nt_response) > NTLMV1_RESPONSE_BYTES:
        proof, client_blob = nt_response[:16], nt_response[16:]
        return f"{user}::{domain}:{challenge.hex()}:{proof.hex()}:{client_blob.hex()}"
    if len(nt_response) == NTLMV1_RESPONSE_BYTES:
        return f"{user}::{domain}:{lm_response.hex()}:{nt_response.hex()}:{challenge.hex()}"
    return ""
