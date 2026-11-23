"""Rendering a raw LDAP search filter as RFC 4515 text for the log."""

import contextlib
import random

import pytest
from ldap3.operation.search import search_operation
from ldap3.utils.conv import escape_filter_chars
from pyasn1.codec.ber import encoder

from lan_sim.services.ldap_ber import LdapProtocolError
from lan_sim.services.ldap_filter import render_filter


def raw(text: str) -> bytes:
    """The filter as ldap3's own client encodes it."""
    request = search_operation("", text, 0, 0, [], 0, 0, False, False, False)
    return bytes(encoder.encode(request["filter"]))


@pytest.mark.parametrize(
    "text",
    [
        "(objectClass=*)",
        "(sAMAccountName=admin)",
        "(&(objectCategory=person)(objectClass=user))",
        "(|(cn=a)(cn=b)(cn=c))",
        "(!(userAccountControl=2))",
        "(cn=ad*min*x)",
        "(cn=*min)",
        "(cn=ad*)",
        "(uSNChanged>=100)",
        "(uSNChanged<=100)",
        "(cn~=admin)",
        "(&(objectClass=user)(!(cn=a))(|(x=1)(y=2)))",
    ],
)
def test_a_filter_the_clients_encode_is_rendered_as_it_was_written(text):
    assert render_filter(raw(text), 1024) == text


def test_the_extensible_match_shows_rule_attribute_and_value():
    text = "(userAccountControl:1.2.840.113556.1.4.803:=2)"

    assert render_filter(raw(text), 1024) == text


def test_special_characters_in_a_value_are_escaped():
    rendered = render_filter(raw("(cn=" + escape_filter_chars("a(b)*c\\d") + ")"), 1024)

    assert rendered == r"(cn=a\28b\29\2ac\5cd)"


def test_a_control_character_in_a_value_is_escaped_not_passed_through():
    rendered = render_filter(raw("(cn=a\\0ab)"), 1024)

    assert "\n" not in rendered
    assert rendered == r"(cn=a\0ab)"


def test_the_rendering_is_cut_at_the_cap():
    rendered = render_filter(raw("(cn=" + "x" * 500 + ")"), 100)

    assert len(rendered) <= 100
    assert rendered.endswith("…")


def test_an_unknown_filter_tag_is_a_protocol_error():
    with pytest.raises(LdapProtocolError):
        render_filter(b"\xaf\x00", 1024)


def test_a_value_assertion_missing_its_value_is_a_protocol_error():
    with pytest.raises(LdapProtocolError):
        render_filter(b"\xa3\x03\x04\x01a", 1024)


def test_a_filter_with_trailing_bytes_is_a_protocol_error():
    with pytest.raises(LdapProtocolError):
        render_filter(raw("(cn=a)") + b"\x00", 1024)


def test_a_not_filter_without_exactly_one_inner_filter_is_a_protocol_error():
    with pytest.raises(LdapProtocolError):
        render_filter(b"\xa2\x00", 1024)


def test_mutated_filters_are_rendered_or_refused_never_crash():
    generator = random.Random(11)  # noqa: S311 - seeded, for reproducible fuzzing
    seed = raw("(&(objectClass=user)(!(cn=a*b))(|(x>=1)(y:dn:1.2.3:=2)))")
    for _ in range(3000):
        mutated = bytearray(seed)
        for _ in range(generator.randrange(1, 4)):
            mutated[generator.randrange(len(mutated))] = generator.randrange(256)
        with contextlib.suppress(LdapProtocolError):
            render_filter(bytes(mutated), 1024)
