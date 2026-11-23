import ipaddress

import pytest

from guest_engine.lan_block import (
    FIRST_OFFSET,
    LAST_OFFSET,
    address_at,
    block_of,
    offset_in_block,
)


def test_the_block_sits_above_the_guest_range_and_the_dhcp_pool_and_below_the_invented_address():
    assert FIRST_OFFSET > 119
    assert LAST_OFFSET < 250


def test_an_offset_becomes_an_address_in_the_given_subnet():
    assert address_at("192.168.150.0/24", 200) == "192.168.150.200"
    assert address_at("10.77.4.0/24", 247) == "10.77.4.247"


def test_the_block_is_the_first_to_the_last_address_in_the_subnet():
    first, last = block_of("192.168.150.0/24")
    assert (first, last) == ("192.168.150.200", "192.168.150.247")


@pytest.mark.parametrize("offset", [FIRST_OFFSET - 1, LAST_OFFSET + 1, 0, 255, -1])
def test_an_offset_outside_the_block_is_refused(offset):
    assert not offset_in_block(offset)
    with pytest.raises(ValueError, match="block"):
        address_at("192.168.150.0/24", offset)


@pytest.mark.parametrize("offset", [FIRST_OFFSET, 215, LAST_OFFSET])
def test_an_offset_inside_the_block_is_accepted(offset):
    assert offset_in_block(offset)
    assert ipaddress.IPv4Address(address_at("192.168.150.0/24", offset))


def test_a_subnet_that_is_not_a_slash_24_is_refused():
    with pytest.raises(ValueError, match="/24"):
        block_of("192.168.0.0/16")
