"""The WinRM listener (TCP 5985) of a fake Windows host: what `Test-WSMan` and NTLM clients see.

It answers the WS-Management Identify request and runs the NTLM handshake far enough to capture the
client's hash. No login ever succeeds, so no shell is created and no command is ever offered. The
HTTP framing is in `winrm_http.py`; the NTLM messages and the verdict are the shared `lan_sim.ntlm`.
"""

import base64
import binascii
import re
from dataclasses import dataclass

from lan_sim import ntlm
from lan_sim.service import Connection
from lan_sim.services.winrm_http import (
    MalformedRequestError,
    Reply,
    Request,
    read_request,
    render,
)

WSMAN_PATH = "/wsman"
IDENTIFY_NAMESPACE = b"http://schemas.dmtf.org/wbem/wsman/identity/1/wsmanidentity.xsd"
IDENTIFY_ELEMENT = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?Identify[\s/>]")
LOGGED_BODY_BYTES = 200
REQUEST_NAME = "winrm request"
BASIC_CHALLENGE = ("WWW-Authenticate", 'Basic realm="WSMAN"')
NEGOTIATE_CHALLENGE = ("WWW-Authenticate", "Negotiate")
SOAP_CONTENT_TYPE = ("Content-Type", "application/soap+xml;charset=UTF-8")
IDENTIFY_RESPONSE = (
    b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
    b'xmlns:wsmid="' + IDENTIFY_NAMESPACE + b'">'
    b"<s:Header/><s:Body><wsmid:IdentifyResponse>"
    b"<wsmid:ProtocolVersion>http://schemas.dmtf.org/wbem/wsman/1/wsman.xsd"
    b"</wsmid:ProtocolVersion>"
    b"<wsmid:ProductVendor>Microsoft Corporation</wsmid:ProductVendor>"
    b"<wsmid:ProductVersion>OS: 0.0.0 SP: 0.0 Stack: 3.0</wsmid:ProductVersion>"
    b"<wsmid:SecurityProfiles>"
    b"<wsmid:SecurityProfile>http://schemas.dmtf.org/wbem/wsman/1/wsman/secprofile/http/"
    b"spnego-kerberos</wsmid:SecurityProfile>"
    b"<wsmid:SecurityProfile>http://schemas.dmtf.org/wbem/wsman/1/wsman/secprofile/http/basic"
    b"</wsmid:SecurityProfile>"
    b"</wsmid:SecurityProfiles>"
    b"</wsmid:IdentifyResponse></s:Body></s:Envelope>"
)
NOT_FOUND = Reply(404)
REFUSED = Reply(401, (NEGOTIATE_CHALLENGE, BASIC_CHALLENGE))


def _identify_reply() -> Reply:
    return Reply(200, (SOAP_CONTENT_TYPE,), IDENTIFY_RESPONSE)


def _unauthorized(*, keeps_open: bool) -> Reply:
    return Reply(401, (NEGOTIATE_CHALLENGE, BASIC_CHALLENGE), keeps_open=keeps_open)


def _negotiate_challenge(token: bytes) -> Reply:
    value = base64.b64encode(token).decode("ascii")
    return Reply(401, (("WWW-Authenticate", f"Negotiate {value}"),), keeps_open=True)


def _decode(token: str) -> bytes | None:
    try:
        return base64.b64decode(token, validate=True)
    except binascii.Error:
        return None


def _is_identify(body: bytes) -> bool:
    return IDENTIFY_NAMESPACE in body and IDENTIFY_ELEMENT.search(body) is not None


def _logged_detail(request: Request) -> str:
    return request.header("soapaction") or request.body[:LOGGED_BODY_BYTES].decode("latin-1")


@dataclass(eq=False)
class _Conversation:
    """One connection's exchange; a challenge is valid only on the connection that was issued it."""

    connection: Connection
    challenge: bytes | None = None

    async def answer(self, request: Request) -> Reply:
        if request.method != "POST" or request.target != WSMAN_PATH:
            return NOT_FOUND
        authorization = request.header("authorization")
        if authorization is None:
            return self._anonymous(request)
        return self._authorized(authorization)

    def _anonymous(self, request: Request) -> Reply:
        if _is_identify(request.body):
            return _identify_reply()
        self.connection.log.service_request(name=REQUEST_NAME, detail=_logged_detail(request))
        return _unauthorized(keeps_open=True)

    def _authorized(self, authorization: str) -> Reply:
        scheme, _, token = authorization.partition(" ")
        token = token.strip()
        match scheme.lower():
            case "negotiate":
                return self._negotiate(token)
            case "basic":
                return self._basic(token)
            case _:
                return REFUSED

    def _negotiate(self, token: str) -> Reply:
        if not token:
            return _unauthorized(keeps_open=True)
        raw = _decode(token)
        blob = None if raw is None else ntlm.unwrap_ntlmssp(raw)
        if blob is None:
            return REFUSED
        try:
            message_type = ntlm.ntlm_message_type(blob)
        except ntlm.NtlmFormatError:
            return REFUSED
        if message_type == ntlm.NEGOTIATE_MESSAGE:
            return self._challenge(wrapped=not raw.startswith(ntlm.NTLMSSP_SIGNATURE))
        if message_type == ntlm.AUTHENTICATE_MESSAGE:
            return self._authenticate(blob)
        return REFUSED

    def _challenge(self, *, wrapped: bool) -> Reply:
        self.challenge = ntlm.new_challenge()
        message = ntlm.challenge_message(
            self.connection.host, self.challenge, self.connection.clock
        )
        return _negotiate_challenge(ntlm.spnego_challenge(message) if wrapped else message)

    def _authenticate(self, blob: bytes) -> Reply:
        challenge, self.challenge = self.challenge, None
        if challenge is None:
            return REFUSED
        try:
            attempt = ntlm.parse_authenticate(blob, challenge)
        except ntlm.NtlmFormatError:
            return REFUSED
        verdict = ntlm.verify(attempt, self.connection.host)
        self.connection.log.login_attempt(
            user=attempt.user,
            domain=attempt.domain,
            mechanism="ntlm",
            secret=attempt.hashcat,
            success=verdict.verified,
        )
        return REFUSED

    def _basic(self, token: str) -> Reply:
        raw = _decode(token)
        if raw is None:
            return REFUSED
        user, _, password = raw.decode("utf-8", errors="replace").partition(":")
        self.connection.log.login_attempt(
            user=user, domain="", mechanism="basic", secret=password, success=False
        )
        return REFUSED


class WinRmService:
    kind = "winrm"

    async def serve(self, connection: Connection) -> None:
        conversation = _Conversation(connection)
        while True:
            try:
                request = await read_request(connection)
            except MalformedRequestError as error:
                await connection.write(render(Reply(error.status), close=True))
                return
            reply = await conversation.answer(request)
            close = not (reply.keeps_open and request.keeps_alive)
            await connection.write(render(reply, close=close))
            if close:
                return


SERVICE = WinRmService()
