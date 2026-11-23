"""The LDAP service: a read-only directory that is empty beyond its root DSE and its domain entry.

The protocol is BER over TCP, hand-framed in `ldap_ber`. A message that is not LDAP ends the
connection; an operation this server does not offer is answered with protocolError and the
connection goes on; an unbind or the end of the stream closes it.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from ldap3.protocol.rfc4511 import (
    AddResponse,
    CompareResponse,
    DelResponse,
    ExtendedResponse,
    ModifyDNResponse,
    ModifyResponse,
    SearchResultDone,
    SearchResultEntry,
)

from lan_sim.service import Connection
from lan_sim.services.ldap_ber import (
    LdapProtocolError,
    build_result,
    decode_message,
    encode_message,
    read_frame,
)
from lan_sim.services.ldap_bind import PROTOCOL_ERROR, SUCCESS, BindState, handle_bind
from lan_sim.services.ldap_directory import (
    Entry,
    domain_entry,
    is_domain_dn,
    root_dse,
    select_attributes,
)
from lan_sim.services.ldap_filter import render_filter

MAX_LOGGED_BASE_CHARACTERS = 256
SCOPE_NAMES = ("base", "one", "sub")
UNSUPPORTED_REQUESTS = {
    "modifyRequest": ("modifyResponse", ModifyResponse),
    "addRequest": ("addResponse", AddResponse),
    "delRequest": ("delResponse", DelResponse),
    "modDNRequest": ("modDNResponse", ModifyDNResponse),
    "compareRequest": ("compareResponse", CompareResponse),
    "extendedReq": ("extendedResp", ExtendedResponse),
}
BASE_OBJECT = 0

Replies = list[bytes]
Handler = Callable[[Connection, int, Any, BindState], Awaitable[Replies]]


class LdapService:
    """Speaks LDAP v2/v3 to anyone: it bears the same face on a domain controller or not."""

    kind = "ldap"

    async def serve(self, connection: Connection) -> None:
        state = BindState()
        try:
            while await self._serve_one_message(connection, state):
                pass
        except LdapProtocolError as error:
            connection.log.service_request(name="ldap malformed", detail=str(error))

    async def _serve_one_message(self, connection: Connection, state: BindState) -> bool:
        """Whether the connection goes on after this message."""
        message = decode_message(await read_frame(connection))
        message_id = int(message["messageID"])
        operation = message["protocolOp"].getName()
        if operation == "unbindRequest":
            return False
        if operation == "abandonRequest":
            return True
        replies = self._replies_to(
            connection, message_id, operation, message["protocolOp"][operation], state
        )
        await connection.write(b"".join(replies))
        return True

    def _replies_to(
        self, connection: Connection, message_id: int, operation: str, body: Any, state: BindState
    ) -> Replies:
        if operation == "bindRequest":
            response = handle_bind(connection, body, state)
            return [encode_message(message_id, "bindResponse", response)]
        if operation == "searchRequest":
            return _search(connection, message_id, body)
        if operation in UNSUPPORTED_REQUESTS:
            connection.log.service_request(name="ldap request", detail=operation)
            response_name, response_class = UNSUPPORTED_REQUESTS[operation]
            response = build_result(response_class, PROTOCOL_ERROR, "operation not supported")
            return [encode_message(message_id, response_name, response)]
        raise LdapProtocolError(f"a client does not send {operation}")


def _search(connection: Connection, message_id: int, request: Any) -> Replies:
    base = bytes(request["baseObject"]).decode("utf-8", errors="replace")
    scope = int(request["scope"])
    filter_text = render_filter(bytes(request["filter"]), connection.limits.max_path_length)
    logged_base = base[:MAX_LOGGED_BASE_CHARACTERS]
    connection.log.service_request(
        name="ldap search",
        detail=f"base={logged_base} scope={_scope_name(scope)} filter={filter_text}",
    )
    replies = [
        encode_message(message_id, "searchResEntry", _entry_message(dn, attributes))
        for dn, attributes in _entries_for(connection, base, scope, request)
    ]
    done = build_result(SearchResultDone, SUCCESS)
    return [*replies, encode_message(message_id, "searchResDone", done)]


def _entries_for(
    connection: Connection, base: str, scope: int, request: Any
) -> list[tuple[str, Entry]]:
    if scope != BASE_OBJECT:
        return []
    if base == "":
        entry = root_dse(connection.host, connection.clock.now())
    elif is_domain_dn(connection.host, base):
        entry = domain_entry(connection.host)
    else:
        return []
    requested = [bytes(name).decode("utf-8", errors="replace") for name in request["attributes"]]
    selected = select_attributes(entry, requested)
    types_only = bool(request["typesOnly"])
    dn = "" if base == "" else entry["distinguishedName"][0]
    return [(dn, {name: [] if types_only else values for name, values in selected.items()})]


def _entry_message(dn: str, attributes: Entry) -> Any:
    message = SearchResultEntry()
    message["object"] = dn
    for index, (name, values) in enumerate(attributes.items()):
        message["attributes"][index]["type"] = name
        for value_index, value in enumerate(values):
            message["attributes"][index]["vals"][value_index] = value
    return message


def _scope_name(scope: int) -> str:
    return SCOPE_NAMES[scope] if 0 <= scope < len(SCOPE_NAMES) else str(scope)


SERVICE = LdapService()
