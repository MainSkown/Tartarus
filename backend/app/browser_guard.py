from collections.abc import Callable, Collection

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from app.errors import error_response

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
WEBSOCKET_POLICY_VIOLATION = 1008

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def hostname_of(authority: str) -> str:
    """Lower-cased host part of `host[:port]`, keeping the brackets of an IPv6 literal."""
    authority = authority.strip().lower()
    if authority.startswith("["):
        return authority[: authority.find("]") + 1]
    return authority.partition(":")[0]


def origin_hostname(origin: str) -> str | None:
    """The host of an Origin header, or None for `null` and anything that is not scheme://authority."""
    _, separator, authority = origin.partition("://")
    if not separator or "@" in authority:
        return None
    return hostname_of(authority.partition("/")[0])


class BrowserOriginGuard:
    """Refuses requests a hostile web page can make to a loopback-bound API.

    Browsers always send Origin on cross-site POSTs and WebSocket handshakes, and always send the
    attacker's own name in Host after DNS rebinding. Clients that are not browsers (curl, the
    compose healthchecks, CAPE's callback) send no Origin and are left alone. Only host names are
    compared: Host loses its port behind nginx, and the dev server proxies from another port.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: Callable[[], Collection[str]]) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        allowed = self.allowed_hosts()
        refusal = self._refusal(scope, headers, allowed)
        await (refusal or self.app)(scope, receive, send)

    def _refusal(self, scope: Scope, headers: Headers, allowed: Collection[str]) -> ASGIApp | None:
        if hostname_of(headers.get("host", "")) not in allowed:
            return _refusal_for(scope, 421, "misdirected_request", "Unknown host.")
        if self._checks_origin(scope) and not self._origin_allowed(headers, allowed):
            return _refusal_for(scope, 403, "foreign_origin", "Foreign origin.")
        return None

    @staticmethod
    def _checks_origin(scope: Scope) -> bool:
        return scope["type"] == "websocket" or scope["method"] not in SAFE_METHODS

    @staticmethod
    def _origin_allowed(headers: Headers, allowed: Collection[str]) -> bool:
        origin = headers.get("origin")
        return origin is None or origin_hostname(origin) in allowed


def _refusal_for(scope: Scope, status_code: int, code: str, message: str) -> ASGIApp:
    if scope["type"] == "websocket":
        return WebSocketClose(WEBSOCKET_POLICY_VIOLATION)
    return error_response(status_code, code, message)


class SecurityHeaders:
    """Adds the same hardening headers to every HTTP response, refusals included."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
