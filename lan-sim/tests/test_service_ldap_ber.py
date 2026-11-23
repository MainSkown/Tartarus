"""The LDAP framing and decoder: hostile bytes in, a message or `LdapProtocolError` out."""

import asyncio
import contextlib
import random
import time

import pytest
from ldap3.protocol.rfc4511 import (
    And,
    BindRequest,
    Filter,
    Not,
    Present,
    SearchRequest,
)

from lan_sim.limits import Limits
from lan_sim.service import Connection, PeerClosed, ReadCapExceeded
from lan_sim.services.ldap_ber import (
    MAX_MESSAGE_BYTES,
    MAX_NESTING_DEPTH,
    LdapProtocolError,
    decode_message,
    encode_message,
    read_frame,
)


def bind_request_bytes(message_id=1, name="", password=""):
    request = BindRequest()
    request["version"] = 3
    request["name"] = name
    request["authentication"]["simple"] = password
    return encode_message(message_id, "bindRequest", request)


def nested_not_filter_search(depth):
    """A search whose filter is `(!(!(...(objectClass=*))))`, `depth` negations deep."""
    inner = Filter()
    inner["present"] = Present("objectClass")
    for _ in range(depth):
        outer = Filter()
        outer["notFilter"] = Not()
        outer["notFilter"]["innerNotFilter"] = inner
        inner = outer
    request = SearchRequest()
    request["baseObject"] = ""
    request["scope"] = 0
    request["derefAliases"] = 0
    request["sizeLimit"] = 0
    request["timeLimit"] = 0
    request["typesOnly"] = False
    request["filter"] = inner
    return encode_message(7, "searchRequest", request)


def deeply_nested_raw(depth):
    """`depth` nested constructed elements, hand-encoded: pyasn1 would not build a tree so deep."""
    body = b""
    for _ in range(depth):
        length = len(body)
        header = b"\xa2" + (
            bytes([length]) if length < 0x80 else b"\x82" + length.to_bytes(2, "big")
        )
        body = header + body
    sequence_length = len(body) + 3
    return b"\x30" + b"\x82" + sequence_length.to_bytes(2, "big") + b"\x02\x01\x01" + body


async def connection_reading(data: bytes, **limits) -> Connection:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return Connection(
        reader=reader,
        writer=None,  # type: ignore[arg-type]
        host=None,  # type: ignore[arg-type]
        service=None,  # type: ignore[arg-type]
        session=None,  # type: ignore[arg-type]
        source=None,  # type: ignore[arg-type]
        destination=None,  # type: ignore[arg-type]
        log=None,  # type: ignore[arg-type]
        clock=None,  # type: ignore[arg-type]
        limits=Limits(idle_timeout_seconds=1.0, **limits),
    )


def read(data: bytes, **limits) -> bytes:
    async def body():
        return await read_frame(await connection_reading(data, **limits))

    return asyncio.run(body())


def test_a_bind_request_round_trips_with_its_message_id():
    message = decode_message(bind_request_bytes(message_id=42, name="CORP\\admin", password="pw"))

    assert int(message["messageID"]) == 42
    assert message["protocolOp"].getName() == "bindRequest"
    bind = message["protocolOp"]["bindRequest"]
    assert str(bind["name"]) == "CORP\\admin"
    assert bytes(bind["authentication"]["simple"]) == b"pw"


def test_a_frame_is_read_whole_and_the_next_message_is_left_in_the_stream():
    first, second = bind_request_bytes(1), bind_request_bytes(2)

    assert read(first + second) == first


def test_a_frame_cut_short_is_a_closed_peer():
    with pytest.raises(PeerClosed):
        read(bind_request_bytes()[:-1])


def test_an_empty_stream_is_a_closed_peer():
    with pytest.raises(PeerClosed):
        read(b"")


@pytest.mark.parametrize(
    "header",
    [
        b"\x04\x01\x00",  # an OCTET STRING, not a SEQUENCE
        b"\x30\x80\x02\x01\x01\x00\x00",  # indefinite length
        b"\x30\xff",  # reserved length octet
        b"\x30\x00",  # empty message
        b"\x3f\x81\x01\x00",  # high tag number form
        b"\x30\x85\x00\x00\x00\x00\x01\x00",  # five length octets
    ],
)
def test_a_header_that_is_not_an_ldap_message_frame_is_refused(header):
    with pytest.raises(LdapProtocolError):
        read(header)


def test_a_declared_length_over_the_cap_is_refused_before_any_body_is_read():
    declared = MAX_MESSAGE_BYTES + 1
    header = b"\x30\x83" + declared.to_bytes(3, "big")

    with pytest.raises(LdapProtocolError):
        read(header)


def test_a_long_form_length_that_fits_the_cap_is_accepted():
    message = bind_request_bytes(name="a" * 300)

    assert read(message) == message


def test_the_connections_read_cap_still_applies_to_a_frame():
    message = bind_request_bytes(name="a" * 300)

    with pytest.raises(ReadCapExceeded):
        read(message, max_bytes_read_per_connection=100)


def test_a_filter_nested_within_the_limit_decodes():
    decode_message(nested_not_filter_search(MAX_NESTING_DEPTH // 2 - 5))


def test_a_filter_nested_past_the_limit_is_refused_without_recursing_into_it():
    started = time.monotonic()
    with pytest.raises(LdapProtocolError):
        decode_message(nested_not_filter_search(MAX_NESTING_DEPTH))
    assert time.monotonic() - started < 1


def test_thousands_of_nested_elements_are_refused_quickly():
    started = time.monotonic()
    with pytest.raises(LdapProtocolError):
        decode_message(deeply_nested_raw(5000))
    assert time.monotonic() - started < 1


def test_an_and_filter_with_many_siblings_is_not_mistaken_for_deep_nesting():
    request = SearchRequest()
    request["baseObject"] = ""
    request["scope"] = 0
    request["derefAliases"] = 0
    request["sizeLimit"] = 0
    request["timeLimit"] = 0
    request["typesOnly"] = False
    conjunction = And()
    for index in range(200):
        term = Filter()
        term["present"] = Present(f"attribute{index}")
        conjunction[index] = term
    request["filter"]["and"] = conjunction

    decode_message(encode_message(1, "searchRequest", request))


def test_a_child_that_overruns_its_parent_is_refused():
    valid = bytearray(bind_request_bytes(name="abc"))
    valid[-1:] = b""  # the outer length now claims a byte the message does not have
    with pytest.raises(LdapProtocolError):
        decode_message(bytes(valid))


def test_bytes_after_the_message_are_refused():
    with pytest.raises(LdapProtocolError):
        decode_message(bind_request_bytes() + b"\x00")


def test_a_message_with_the_wrong_structure_is_refused():
    wrong = b"\x30\x05\x02\x01\x01\x04\x00"  # a message ID and then an OCTET STRING, no operation
    with pytest.raises(LdapProtocolError):
        decode_message(wrong)


def test_a_message_id_of_the_wrong_type_is_refused():
    message = bytearray(bind_request_bytes())
    message[2] = 0x04  # MessageID INTEGER tag becomes OCTET STRING
    with pytest.raises(LdapProtocolError):
        decode_message(bytes(message))


def test_a_bind_version_outside_the_schemas_range_is_refused():
    bind_with_version_zero = bytes.fromhex("300c020101600702010004000480")
    with pytest.raises(LdapProtocolError):
        decode_message(bind_with_version_zero)


def test_random_bytes_end_in_a_message_or_a_protocol_error_in_bounded_time():
    generator = random.Random(20261123)  # noqa: S311 - seeded, for reproducible fuzzing
    started = time.monotonic()
    for _ in range(3000):
        blob = bytes(generator.randrange(256) for _ in range(generator.randrange(1, 120)))
        _decoded_or_refused(blob)
        _decoded_or_refused(b"\x30" + bytes([len(blob)]) + blob[:127])
    assert time.monotonic() - started < 10


def test_mutated_valid_messages_end_in_a_message_or_a_protocol_error():
    generator = random.Random(7)  # noqa: S311 - seeded, for reproducible fuzzing
    seeds = [
        bind_request_bytes(1, "CORP\\admin", "secret"),
        nested_not_filter_search(5),
    ]
    started = time.monotonic()
    for seed in seeds:
        for _ in range(3000):
            mutated = bytearray(seed)
            for _ in range(generator.randrange(1, 5)):
                mutated[generator.randrange(len(mutated))] = generator.randrange(256)
            _decoded_or_refused(bytes(mutated))
            _decoded_or_refused(bytes(mutated[: generator.randrange(1, len(mutated))]))
    assert time.monotonic() - started < 10


def _decoded_or_refused(blob: bytes) -> None:
    with contextlib.suppress(LdapProtocolError):
        decode_message(blob)
