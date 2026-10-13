import asyncio

import pytest

from app.desktop.guacamole import Instruction, encode
from app.desktop.tunnel import GuacdTunnel, TunnelError
from tests.desktop.fake_guacd import GUEST_OFF, OBSERVED_ARGS, FakeGuacd

HANDSHAKE_TIMEOUT_S = 0.3
# hostname, port, read-only | five empty | color-depth, cursor, autoretry | twelve empty |
# disable-copy, disable-paste | nine empty: the order guacd listed its args in.
EXPECTED_CONNECT_VALUES = (
    ("VERSION_1_5_0", "127.0.0.1", "5900", "false")
    + ("",) * 5
    + ("24", "remote", "0")
    + ("",) * 12
    + ("true", "true")
    + ("",) * 9
)


async def open_tunnel(guacd: FakeGuacd, *, vnc_port: int = 5900) -> GuacdTunnel:
    return await GuacdTunnel.open(
        "127.0.0.1", guacd.port, vnc_port=vnc_port, handshake_timeout_s=HANDSHAKE_TIMEOUT_S
    )


async def send_until_refused(tunnel: GuacdTunnel) -> None:
    # A write to a socket the peer closed only fails on the second try or later.
    for _ in range(50):
        await tunnel.send(Instruction("nop", ()))
        await asyncio.sleep(0.01)


async def test_the_handshake_is_the_one_observed_against_the_real_guacd() -> None:
    async with FakeGuacd() as guacd:
        tunnel = await open_tunnel(guacd)
        await tunnel.close()

    assert guacd.received == [
        Instruction("select", ("vnc",)),
        Instruction("size", ("1280", "800", "96")),
        Instruction("audio", ()),
        Instruction("video", ()),
        Instruction("image", ("image/png", "image/jpeg", "image/webp")),
        Instruction("timezone", ("UTC",)),
        Instruction("connect", EXPECTED_CONNECT_VALUES),
    ]


async def test_the_connect_names_the_vnc_port_it_was_given() -> None:
    async with FakeGuacd() as guacd:
        tunnel = await open_tunnel(guacd, vnc_port=5903)
        await tunnel.close()

    (connect,) = [i for i in guacd.received if i.opcode == "connect"]
    assert connect.args[OBSERVED_ARGS.index("hostname")] == "127.0.0.1"
    assert connect.args[OBSERVED_ARGS.index("port")] == "5903"


async def test_the_connect_follows_the_args_this_guacd_listed() -> None:
    names = ("VERSION_9_9_9", "new-thing", "port", "hostname", "disable-copy")
    async with FakeGuacd(args=names) as guacd:
        tunnel = await open_tunnel(guacd)
        await tunnel.close()

    (connect,) = [i for i in guacd.received if i.opcode == "connect"]
    assert connect.args == ("VERSION_9_9_9", "", "5900", "127.0.0.1", "true")


async def test_after_ready_the_instructions_of_guacd_come_through_in_order() -> None:
    async with FakeGuacd() as guacd:
        tunnel = await open_tunnel(guacd)
        await guacd.push(
            encode("sync", "100"), encode("img", "3", "14", "0", "image/png", "0", "0")
        )

        received = [await tunnel.receive() for _ in range(4)]
        await tunnel.close()

    assert [i.opcode for i in received if i] == ["size", "size", "sync", "img"]


async def test_the_ready_instruction_is_part_of_the_handshake_not_of_the_stream() -> None:
    async with FakeGuacd() as guacd:
        tunnel = await open_tunnel(guacd)
        first = await tunnel.receive()
        await tunnel.close()

    assert first == Instruction("size", ("-2", "5", "5"))


async def test_the_desktop_counts_as_connected_at_the_first_picture_not_at_ready() -> None:
    async with FakeGuacd(after_ready=()) as guacd:
        tunnel = await open_tunnel(guacd)
        assert not tunnel.connected
        await guacd.push(encode("size", "0", "1280", "800"))
        await tunnel.receive()
        connected = tunnel.connected
        await tunnel.close()

    assert connected


async def test_a_guest_that_is_off_never_counts_as_connected() -> None:
    async with FakeGuacd(after_ready=GUEST_OFF) as guacd:
        tunnel = await open_tunnel(guacd)
        error = await tunnel.receive()
        connected = tunnel.connected
        await tunnel.close()

    assert error == Instruction("error", ("Aborted. See logs.", "519"))
    assert not connected


async def test_instructions_sent_after_ready_in_the_same_read_are_not_lost() -> None:
    async with FakeGuacd(after_ready=GUEST_OFF) as guacd:
        tunnel = await open_tunnel(guacd)
        first, second = await tunnel.receive(), await tunnel.receive()
        await tunnel.close()

    assert [first and first.opcode, second and second.opcode] == ["error", "nop"]


async def test_what_the_browser_sends_reaches_guacd_unchanged() -> None:
    async with FakeGuacd() as guacd:
        tunnel = await open_tunnel(guacd)
        await tunnel.send(Instruction("mouse", ("10", "20", "1")))
        await guacd.wait_for_opcode("mouse")
        await tunnel.close()

    assert guacd.received[-1] == Instruction("mouse", ("10", "20", "1"))


async def test_text_survives_tcp_cuts_inside_instructions_and_characters() -> None:
    async with FakeGuacd(after_ready=(), byte_chunk=1) as guacd:
        tunnel = await open_tunnel(guacd)
        await guacd.push(encode("argv", "zażółć gęślą jaźń 🙂"), encode("nop"))

        first, second = await tunnel.receive(), await tunnel.receive()
        await tunnel.close()

    assert first == Instruction("argv", ("zażółć gęślą jaźń 🙂",))
    assert second == Instruction("nop", ())


async def test_receive_returns_none_once_guacd_hangs_up() -> None:
    async with FakeGuacd(after_ready=()) as guacd:
        tunnel = await open_tunnel(guacd)
        guacd.hang_up()

        assert await tunnel.receive() is None
        assert await tunnel.receive() is None
        await tunnel.close()


async def test_close_is_safe_to_repeat() -> None:
    async with FakeGuacd() as guacd:
        tunnel = await open_tunnel(guacd)
        await tunnel.close()
        await tunnel.close()


async def test_sending_after_guacd_hung_up_is_a_tunnel_error() -> None:
    async with FakeGuacd(after_ready=()) as guacd:
        tunnel = await open_tunnel(guacd)
        guacd.hang_up()
        await tunnel.receive()

        with pytest.raises(TunnelError):
            await send_until_refused(tunnel)
        await tunnel.close()


async def test_a_guacd_that_cannot_be_reached_is_a_tunnel_error() -> None:
    async with FakeGuacd() as guacd:
        unused_port = guacd.port
    with pytest.raises(TunnelError, match="reach"):
        await GuacdTunnel.open("127.0.0.1", unused_port, vnc_port=5900, handshake_timeout_s=1)


@pytest.mark.parametrize("opcode", ["select", "connect"])
async def test_a_guacd_that_hangs_up_during_the_handshake_is_a_tunnel_error(opcode: str) -> None:
    async with FakeGuacd(hang_up_on=opcode) as guacd:
        with pytest.raises(TunnelError, match="closed"):
            await open_tunnel(guacd)


async def test_a_guacd_that_never_says_ready_is_a_tunnel_error_after_the_timeout() -> None:
    async with FakeGuacd(answer_connect=False) as guacd:
        with pytest.raises(TunnelError, match="timed out"):
            await open_tunnel(guacd)


async def test_a_guacd_that_answers_select_with_an_error_is_a_tunnel_error_with_its_message() -> (
    None
):
    async with FakeGuacd(answer_select=encode("error", "no such protocol", "768")) as guacd:
        with pytest.raises(TunnelError, match="no such protocol"):
            await open_tunnel(guacd)


async def test_a_guacd_that_answers_nonsense_is_a_tunnel_error() -> None:
    async with FakeGuacd(answer_select="not an instruction;") as guacd:
        with pytest.raises(TunnelError, match="Guacamole"):
            await open_tunnel(guacd)


async def test_a_guacd_that_never_answers_select_is_a_tunnel_error_after_the_timeout() -> None:
    async with FakeGuacd(answer_select=encode("nop")) as guacd:
        with pytest.raises(TunnelError, match="timed out"):
            await open_tunnel(guacd)
