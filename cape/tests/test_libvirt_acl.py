"""libvirt's access control for the `cape` user (audit finding 1).

libvirtd runs as root and its socket is open to the `cape` group, so without a policy any code
that runs as `cape` could ask it to define a domain on any device. The polkit access driver
leaves `cape` the reads CAPE's LibVirtMachinery makes and nothing that writes: libvirt cannot
allow a revert or a memory dump without also allowing a root-owned write anywhere, so the machine
broker does those as root (tests/test_machine_broker_logic.py). The measured behaviour is proven
against a running container by scripts/verify-cape-hardening.sh; these keep the files that build
it from drifting.
"""

import configparser
import os
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import pytest

CAPE = Path(__file__).resolve().parents[1]
RULES = CAPE / "libvirt" / "polkit" / "50-tartarus-libvirt.rules"
BUS_CONFIG = CAPE / "libvirt" / "dbus-system.conf"
LIBVIRTD_CONF = CAPE / "templates" / "libvirtd.conf"
WAIT_THEN_EXEC = CAPE / "bin" / "wait-then-exec"
RUNTIME_STAGE = (CAPE / "Dockerfile").read_text().rpartition("FROM ubuntu:24.04@sha256:")[2]

# One entry per libvirt read CAPE's LibVirtMachinery and its startup check make (abstracts.py,
# kvm.py, startup.py): open, list and look up domains, read state and XML (snapshots too).
CAPE_MAY = {
    "org.libvirt.api.connect.getattr",
    "org.libvirt.api.connect.search-domains",
    "org.libvirt.api.domain.getattr",
    "org.libvirt.api.domain.read",
}


def cape_allow_list() -> set[str]:
    array = re.search(r"const CAPE_MAY = \[(.*?)\];", RULES.read_text(), re.DOTALL)
    assert array, "the rules file declares CAPE_MAY"
    return set(re.findall(r'"(org\.libvirt\.api\.[a-z-]+\.[a-z-]+)"', array.group(1)))


def test_libvirtd_asks_polkit_before_serving_a_client():
    active = [
        line.split("#")[0].strip()
        for line in LIBVIRTD_CONF.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]

    assert 'access_drivers = [ "polkit" ]' in active


def test_the_allow_list_is_exactly_what_cape_does_to_a_registered_guest():
    assert cape_allow_list() == CAPE_MAY


@pytest.mark.parametrize(
    "action",
    [
        "connect.write",
        "domain.write",
        "domain.start",
        "domain.stop",
        "domain.snapshot",
        "domain.core-dump",
        "domain.save",
        "domain.hibernate",
        "domain.migrate",
        "domain.delete",
        "domain.block-write",
        "domain.open-device",
        "domain.open-graphics",
        "domain.open-namespace",
        "domain.inject-nmi",
        "domain.send-input",
        "domain.send-signal",
        "domain.mem-read",
        "domain.read-secure",
        "domain.screenshot",
        "domain.fs-freeze",
        "domain.set-password",
        "network.write",
        "network.start",
        "network.stop",
        "storage-pool.write",
        "storage-pool.start",
        "storage-vol.delete",
        "storage-vol.data-read",
        "node-device.write",
        "secret.write",
        "secret.read-secure",
        "interface.write",
        "nwfilter.write",
    ],
)
def test_nothing_that_defines_attaches_saves_opens_or_touches_the_host_is_allowed(action):
    assert f"org.libvirt.api.{action}" not in cape_allow_list()


def test_cape_gets_nothing_outside_the_connection_and_domain_classes():
    classes = {action.split(".")[3] for action in cape_allow_list()}

    assert classes == {"connect", "domain"}


def test_the_rule_gives_the_allow_list_to_the_cape_user_of_the_qemu_driver_and_refuses_the_rest():
    rules = RULES.read_text()

    assert 'subject.user === "cape"' in rules
    assert 'action.lookup("connect_driver") === "QEMU"' in rules
    assert re.search(r"return polkit\.Result\.NO;\s*\}\);\s*$", rules)


def test_actions_of_other_programs_are_left_to_polkits_own_rules():
    assert 'action.id.indexOf("org.libvirt.api.") !== 0' in RULES.read_text()


def test_the_image_installs_the_rules_where_polkitd_reads_them():
    assert re.search(
        r"COPY cape/libvirt/polkit/50-tartarus-libvirt\.rules /etc/polkit-1/rules\.d/\n",
        RUNTIME_STAGE,
    )


def test_both_files_are_made_readable_to_the_users_that_read_them():
    assert re.search(
        r"RUN chmod 0644 /etc/polkit-1/rules\.d/50-tartarus-libvirt\.rules"
        r" /etc/dbus-1/tartarus-system\.conf\n",
        RUNTIME_STAGE,
    )


def test_the_image_installs_the_bus_config_that_supervisord_starts_dbus_with():
    assert "COPY cape/libvirt/dbus-system.conf /etc/dbus-1/tartarus-system.conf" in RUNTIME_STAGE


def test_the_entrypoint_creates_the_directory_of_the_bus_socket_on_the_run_tmpfs():
    entrypoint = (CAPE / "entrypoint.sh").read_text()

    assert "install -d /run/dbus" in entrypoint


def programs() -> dict[str, configparser.SectionProxy]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(CAPE / "supervisord.conf")
    return {
        section.removeprefix("program:"): parser[section]
        for section in parser.sections()
        if section.startswith("program:")
    }


def test_the_bus_and_polkitd_start_through_the_secret_wrapper_before_libvirtd():
    started = programs()
    wrapper = "/usr/local/lib/tartarus/keep-secrets -- "

    assert started["dbus"]["command"].startswith(wrapper + "/usr/bin/dbus-daemon ")
    assert started["polkitd"]["command"].startswith(wrapper)
    assert "/usr/lib/polkit-1/polkitd --no-debug" in started["polkitd"]["command"]
    assert int(started["dbus"]["priority"]) < int(started["polkitd"]["priority"])
    assert int(started["polkitd"]["priority"]) < int(started["libvirtd"]["priority"])


def test_dbus_runs_in_the_foreground_with_the_bus_config_of_this_repository():
    command = programs()["dbus"]["command"]

    assert "--config-file=/etc/dbus-1/tartarus-system.conf" in command
    assert "--nofork" in command
    assert "--nopidfile" in command


def test_polkitd_runs_unprivileged_once_the_bus_answers():
    polkitd = programs()["polkitd"]

    assert polkitd["user"] == "polkitd"
    assert "wait-then-exec dbus --" in polkitd["command"]


def test_libvirtd_serves_nobody_before_polkitd_owns_its_bus_name():
    command = programs()["libvirtd"]["command"]

    assert "wait-then-exec polkit -- /usr/sbin/libvirtd" in command


@pytest.mark.parametrize("name", ["dbus", "polkitd", "libvirtd"])
def test_the_chain_is_restarted_even_after_a_clean_exit(name):
    # libvirtd exits with status 0 when the bus goes away, which supervisord's default (restart
    # only after an unexpected exit code) would leave stopped, with CAPE unable to reach libvirt.
    assert programs()[name]["autorestart"] == "true"


@pytest.mark.parametrize("name", ["dbus", "polkitd"])
def test_the_new_programs_log_to_the_container_output_like_the_others(name):
    program = programs()[name]

    assert program["stdout_logfile"] == "/dev/fd/1"
    assert program["stdout_logfile_maxbytes"] == "0"
    assert program["redirect_stderr"] == "true"


def bus_default_policy() -> ElementTree.Element:
    config = ElementTree.parse(BUS_CONFIG).getroot()  # noqa: S314 - this repository's own file
    policy = config.find("policy[@context='default']")
    assert policy is not None
    return policy


def test_only_root_and_polkitd_may_connect_to_the_bus():
    permitted = {rule.get("user") for rule in bus_default_policy().findall("allow[@user]")}

    assert permitted == {"root", "polkitd"}


def test_the_bus_cannot_start_other_services():
    config = BUS_CONFIG.read_text()

    assert "servicedir" not in config
    assert "standard_system_servicedirs" not in config
    assert "servicehelper" not in config


def test_only_polkitd_may_own_a_name_on_the_bus():
    config = BUS_CONFIG.read_text()
    default = bus_default_policy()

    assert default.find("deny[@own='*']") is not None
    assert default.find("allow[@own]") is None
    assert "PolicyKit1.conf" in config


@pytest.fixture
def fake_dbus_send(tmp_path):
    def install(reply: str) -> dict[str, str]:
        script = tmp_path / "dbus-send"
        script.write_text(f"#!/bin/sh\necho '{reply}'\n")
        script.chmod(0o755)
        return {"PATH": f"{tmp_path}:{os.environ['PATH']}"}

    return install


def wait_for(condition: str, environment: dict[str, str]):
    return subprocess.run(  # noqa: S603 - this repository's own script
        [str(WAIT_THEN_EXEC), condition, "--", "echo", "started"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )


@pytest.mark.parametrize("condition", ["dbus", "polkit"])
def test_the_condition_holds_once_the_bus_answers_and_polkit_owns_its_name(
    fake_dbus_send, condition
):
    environment = fake_dbus_send("   boolean true")

    assert wait_for(condition, environment).stdout.endswith("started\n")


def test_the_polkit_condition_waits_while_the_bus_says_nobody_owns_the_name(fake_dbus_send):
    environment = fake_dbus_send("   boolean false")

    with pytest.raises(subprocess.TimeoutExpired):
        wait_for("polkit", environment)


def test_waiting_for_a_registered_guest_asks_only_what_the_cape_user_may_read():
    # `virsh dominfo` also asks for the host's security model, which the policy refuses the cape
    # user: the wait would never end and CAPE would never start.
    script = WAIT_THEN_EXEC.read_text()

    assert "dominfo" not in script
    assert 'domstate "$machine"' in script


def test_cape_starts_only_once_the_machine_broker_listens():
    cape = programs()["cape"]["command"]
    broker = programs()["machine-broker"]

    assert "machine-broker" in cape.split(" -- ")[1].split()
    assert broker["command"] == (
        "/usr/local/lib/tartarus/keep-secrets -- /usr/local/lib/tartarus/machine-broker"
    )
    assert "user" not in broker, "the broker asks libvirt as root"
    assert int(broker["priority"]) < int(programs()["cape"]["priority"])
    assert "[[ -S $MACHINE_BROKER_SOCKET ]]" in WAIT_THEN_EXEC.read_text()


def test_the_image_patches_capes_machinery_and_fails_the_build_if_the_patch_did_not_take():
    stage = RUNTIME_STAGE.replace("\\\n", " ")
    abstracts = "/opt/CAPEv2/lib/cuckoo/common/abstracts.py"

    assert f"python3 /tmp/machinery-through-broker.py {abstracts}" in stage
    assert f"ast.parse(open('{abstracts}').read())" in stage
    for write in ("revertToSnapshot(", "vm.destroy()", "coreDump("):
        assert f"! grep -qF '{write}' {abstracts}" in stage
    assert "COPY cape/bin/machine_broker_client.py /opt/CAPEv2/lib/cuckoo/common/" in RUNTIME_STAGE
