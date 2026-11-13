"""A guest's port on the shared bridge is isolated by the qemu hook, before it is bound."""

import json
import re

import pytest
from test_guest_firewall import STARTED_XML

from guest_engine.firewall import GuestPort, ports_in
from guest_engine.media import CommandResult
from guest_engine.media.errors import Fault, MediaProblem
from guest_engine.port_isolation import isolate_ports

PORT = GuestPort(domain="lab1", tap="vnet10", mac="00:14:22:8d:44:27")
OTHER = GuestPort(domain="lab1", tap="vnet11", mac="52:54:00:00:00:01")


class Bridge:
    """Stands in for the `bridge` program: remembers which taps it was told to isolate."""

    def __init__(self, *, set_fails=(), ignores_set=(), missing=False):
        self.commands: list[list[str]] = []
        self.timeouts: list[float | None] = []
        self.isolated: set[str] = set()
        self.set_fails = set(set_fails)
        self.ignores_set = set(ignores_set)
        self.missing = missing

    def __call__(self, args, timeout=None):
        self.commands.append(list(args))
        self.timeouts.append(timeout)
        if self.missing:
            raise MediaProblem(Fault.TOOL_MISSING, detail="bridge")
        assert args[0] == "bridge"
        tap = args[args.index("dev") + 1]
        if "set" in args:
            return self._set(tap)
        flag = tap in self.isolated
        return CommandResult(0, json.dumps([{"ifname": tap, "isolated": flag}]), "")

    def _set(self, tap):
        if tap in self.set_fails:
            return CommandResult(255, "", "RTNETLINK answers: Operation not supported")
        if tap not in self.ignores_set:
            self.isolated.add(tap)
        return CommandResult(0, "", "")


def test_a_port_is_isolated_with_the_bridge_command_and_a_timeout():
    bridge = Bridge()

    isolate_ports([PORT], bridge)

    assert bridge.commands[0] == ["bridge", "link", "set", "dev", "vnet10", "isolated", "on"]
    assert bridge.timeouts[0]
    assert bridge.isolated == {"vnet10"}


def test_the_flag_is_read_back_because_a_set_that_did_nothing_must_not_pass():
    bridge = Bridge()

    isolate_ports([PORT], bridge)

    assert ["bridge", "-d", "-j", "link", "show", "dev", "vnet10"] in bridge.commands


def test_every_port_is_isolated():
    bridge = Bridge()

    isolate_ports([PORT, OTHER], bridge)

    assert bridge.isolated == {"vnet10", "vnet11"}


def test_no_ports_run_no_command():
    bridge = Bridge()

    isolate_ports([], bridge)

    assert bridge.commands == []


def test_a_set_the_kernel_refuses_raises_and_says_which_port_and_why():
    bridge = Bridge(set_fails={"vnet10"})

    with pytest.raises(
        RuntimeError, match=re.escape("vnet10: RTNETLINK answers: Operation not supported")
    ):
        isolate_ports([PORT], bridge)


def test_a_failure_with_no_message_still_names_the_exit_status():
    class Silent(Bridge):
        def _set(self, tap):
            return CommandResult(1, "", "")

    with pytest.raises(RuntimeError, match="vnet10: exit status 1"):
        isolate_ports([PORT], Silent())


def test_a_flag_that_reads_back_off_raises():
    bridge = Bridge(ignores_set={"vnet10"})

    with pytest.raises(RuntimeError, match="port vnet10 is not isolated"):
        isolate_ports([PORT], bridge)


def test_a_tap_that_is_not_a_bridge_port_reads_back_as_nothing_and_raises():
    class NotAPort(Bridge):
        def __call__(self, args, timeout=None):
            result = super().__call__(args, timeout)
            return CommandResult(0, "[]", "") if "show" in args else result

    with pytest.raises(RuntimeError, match="vnet10"):
        isolate_ports([PORT], NotAPort())


def test_a_missing_bridge_program_is_a_failure_with_a_reason():
    with pytest.raises(RuntimeError, match="bridge"):
        isolate_ports([PORT], Bridge(missing=True))


def test_output_that_is_not_json_raises_rather_than_passes():
    class Garbled(Bridge):
        def __call__(self, args, timeout=None):
            result = super().__call__(args, timeout)
            return CommandResult(0, "not json", "") if "show" in args else result

    with pytest.raises(RuntimeError, match="vnet10"):
        isolate_ports([PORT], Garbled())


@pytest.mark.parametrize("tap", ["", "vnet 1", "a;b", "x" * 16, "vnet\n0"])
def test_a_tap_name_that_could_be_an_option_or_is_not_an_interface_name_never_reaches_a_command(
    tap,
):
    bridge = Bridge()

    with pytest.raises(ValueError, match="tap"):
        isolate_ports([GuestPort("lab1", tap, PORT.mac)], bridge)

    assert bridge.commands == []


def test_the_ports_of_the_started_xml_are_isolated_the_way_the_hook_will_do_it():
    bridge = Bridge()

    isolate_ports(ports_in(STARTED_XML, "tt-guest"), bridge)

    assert bridge.isolated == {"vnet10"}
