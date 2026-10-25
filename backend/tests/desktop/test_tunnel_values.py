import pytest

from app.desktop.guacamole import Instruction
from app.desktop.tunnel import (
    BROWSER_OPCODES,
    connect_instruction,
    forwardable_from_browser,
)
from tests.desktop.fake_guacd import OBSERVED_ARGS

# Copied from the D1 transcript in docs/history/m2-live.md, section 4.
OBSERVED_CONNECT = (
    "connect,VERSION_1_5_0,127.0.0.1,5900,false,,,,,,24,remote,0,,,,,,,,,,,,,true,true,,,,,,,,,"
)


def test_the_connect_for_the_observed_args_is_the_connect_guacd_accepted() -> None:
    instruction = connect_instruction(OBSERVED_ARGS, vnc_port=5900)

    assert ",".join((instruction.opcode, *instruction.args)) == OBSERVED_CONNECT


def test_the_connect_has_one_value_per_arg_name() -> None:
    instruction = connect_instruction(OBSERVED_ARGS, vnc_port=5900)

    assert len(instruction.args) == len(OBSERVED_ARGS)


def test_the_connect_uses_the_port_it_is_given() -> None:
    instruction = connect_instruction(("VERSION_1_5_0", "hostname", "port"), vnc_port=5917)

    assert instruction == Instruction("connect", ("VERSION_1_5_0", "127.0.0.1", "5917"))


def test_the_connect_uses_the_host_it_is_given() -> None:
    instruction = connect_instruction(
        ("VERSION_1_5_0", "hostname", "port"), vnc_host="localhost", vnc_port=5931
    )

    assert instruction == Instruction("connect", ("VERSION_1_5_0", "localhost", "5931"))


def test_the_connect_follows_the_order_guacd_listed_even_when_it_changes() -> None:
    names = ("VERSION_1_6_0", "disable-paste", "future-option", "port", "hostname")

    instruction = connect_instruction(names, vnc_port=5901)

    assert instruction.args == ("VERSION_1_6_0", "true", "", "5901", "127.0.0.1")


def test_a_name_we_do_not_know_gets_an_empty_value() -> None:
    instruction = connect_instruction(
        ("VERSION_1_5_0", "recording-path", "sftp-host"), vnc_port=5900
    )

    assert instruction.args == ("VERSION_1_5_0", "", "")


def test_clipboard_is_switched_off_in_both_directions() -> None:
    names = ("VERSION_1_5_0", "disable-copy", "disable-paste", "read-only")

    instruction = connect_instruction(names, vnc_port=5900)

    assert instruction.args == ("VERSION_1_5_0", "true", "true", "false")


@pytest.mark.parametrize("opcode", ["mouse", "key", "size", "sync", "ack", "blob", "end", "nop"])
def test_these_browser_instructions_reach_guacd(opcode: str) -> None:
    assert forwardable_from_browser(Instruction(opcode, ("1",)))


@pytest.mark.parametrize(
    "opcode",
    [
        "clipboard",
        "file",
        "put",
        "get",
        "pipe",
        "argv",
        "disconnect",
        "select",
        "connect",
        "nest",
        "audio",
        "video",
        "image",
        "ready",
        "args",
        "error",
        "",
        "MOUSE",
        "mouse ",
    ],
)
def test_every_other_browser_instruction_is_dropped(opcode: str) -> None:
    assert not forwardable_from_browser(Instruction(opcode, ("1",)))


def test_the_allowlist_is_exactly_the_documented_one() -> None:
    assert {"mouse", "key", "size", "sync", "ack", "blob", "end", "nop"} == BROWSER_OPCODES
