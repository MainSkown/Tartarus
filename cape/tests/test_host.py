from pathlib import Path

import pytest
from fixtures.fake_host import SNAPSHOT, FakeHost, failure, ok
from fixtures.profile_samples import FIXTURE_DIR

from guest_engine.host import Host, HostError, files_referenced_by, parse_display
from guest_engine.media import Fault, MediaProblem


@pytest.fixture
def world(tmp_path):
    fake = FakeHost(tmp_path / "lib", tmp_path / "guests", tmp_path / "conf.d")
    (tmp_path / "guests" / "alpha").mkdir(parents=True)
    return fake


def define(world, name="alpha", snapshot=True):
    (world.guests_root / name).mkdir(parents=True, exist_ok=True)
    (world.guests_root / name / "defined").write_text("")
    if snapshot:
        (world.guests_root / name / "snapshotted").write_text("")


# --- asking libvirt ----------------------------------------------------------------------


def test_every_virsh_call_names_the_connection(world):
    host = Host(world, "qemu:///system")
    define(world)

    host.domain_exists("alpha")

    assert world.calls == [["virsh", "-c", "qemu:///system", "dominfo", "alpha"]]


def test_a_domain_exists_only_when_virsh_knows_it(world):
    host = Host(world, "qemu:///system")
    assert not host.domain_exists("alpha")
    define(world)
    assert host.domain_exists("alpha")


def test_running_follows_the_domain_state(world):
    host = Host(world, "qemu:///system")
    define(world)
    assert not host.is_running("alpha")
    world.running.add("alpha")
    assert host.is_running("alpha")


def test_snapshots_are_listed_by_name(world):
    host = Host(world, "qemu:///system")
    define(world, snapshot=False)
    assert host.snapshot_names("alpha") == []
    define(world)
    assert host.snapshot_names("alpha") == [SNAPSHOT]
    assert host.snapshot_names("ghost") == []


def test_the_domain_xml_is_none_for_an_unknown_domain(world):
    host = Host(world, "qemu:///system")
    define(world)
    assert "<name>alpha</name>" in host.domain_xml("alpha")
    assert host.domain_xml("ghost") is None


def test_a_tool_that_is_not_installed_is_a_failed_command_not_a_crash():
    def missing(args, timeout=None):
        raise MediaProblem(Fault.TOOL_MISSING, detail=args[0])

    host = Host(missing, "qemu:///system")

    assert host.domain_exists("alpha") is False
    with pytest.raises(HostError, match="supervisorctl"):
        host.restart_cape()


# --- files a domain owns -----------------------------------------------------------------


def test_the_files_of_the_real_guest_are_found_in_its_xml():
    xml = (FIXTURE_DIR / "win.dumpxml.xml").read_text()

    files = files_referenced_by(xml)

    assert Path("/var/lib/libvirt/images/win.qcow2") in files
    assert Path("/var/lib/libvirt/images/win.1792073956") in files
    assert Path("/var/lib/libvirt/nvram/win_VARS.fd") in files


def test_a_snapshots_memory_file_and_overlay_are_found():
    xml = (
        "<domainsnapshot><memory snapshot='external' file='/v/win-clean.mem'/>"
        "<disks><disk name='sda'><source file='/v/win-clean.qcow2'/></disk></disks>"
        "</domainsnapshot>"
    )

    assert set(files_referenced_by(xml)) == {Path("/v/win-clean.mem"), Path("/v/win-clean.qcow2")}


def test_xml_that_is_not_xml_references_nothing():
    assert files_referenced_by("not xml at all") == []


def test_all_the_files_of_a_guest_come_from_its_domain_and_snapshots(world, tmp_path):
    host = Host(world, "qemu:///system")
    define(world)

    owned = set(host.owned_files("alpha"))

    assert set(world.files_of("alpha")) <= owned
    assert world.outside_file in owned


# --- display -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("vnc://127.0.0.1:0\n", {"host": "127.0.0.1", "port": 5900}),
        ("vnc://127.0.0.1:3\n", {"host": "127.0.0.1", "port": 5903}),
        ("vnc://localhost:12\n", {"host": "localhost", "port": 5912}),
        ("vnc://0.0.0.0:1\n", {"host": "127.0.0.1", "port": 5901}),
        ("vnc://[::1]:2\n", {"host": "::1", "port": 5902}),
        ("spice://127.0.0.1:5901\n", None),
        ("", None),
        ("vnc://127.0.0.1\n", None),
        ("garbage", None),
    ],
)
def test_the_vnc_display_is_turned_into_host_and_port(printed, expected):
    assert parse_display(printed) == expected


def test_a_running_domains_display_is_its_vnc_address(world):
    host = Host(world, "qemu:///system")
    define(world)
    assert host.display("alpha") is None
    world.running.add("alpha")
    assert host.display("alpha") == {"host": "127.0.0.1", "port": 5901}


# --- changing things ---------------------------------------------------------------------


def test_destroy_and_revert_go_to_virsh(world):
    host = Host(world, "qemu:///system")
    define(world)

    host.revert("alpha", SNAPSHOT)
    host.destroy("alpha")

    assert world.events == ["revert alpha", "destroy alpha"]


def test_a_failed_revert_says_why(world):
    def refuse(args, timeout=None):
        return failure("error: snapshot not found")

    with pytest.raises(HostError, match="snapshot not found"):
        Host(refuse, "qemu:///system").revert("alpha", SNAPSHOT)


def test_undefine_removes_the_nvram_tpm_and_snapshot_metadata_too(world):
    host = Host(world, "qemu:///system")
    define(world)

    host.undefine("alpha")

    flags = next(call for call in world.calls if "undefine" in call)
    assert {"--nvram", "--tpm", "--snapshots-metadata"} <= set(flags)
    assert not host.domain_exists("alpha")


def test_undefine_of_a_domain_that_is_already_gone_is_not_an_error(world):
    Host(world, "qemu:///system").undefine("ghost")


def test_a_failed_undefine_is_an_error(tmp_path):
    def refuse(args, timeout=None):
        if "dominfo" in args:
            return ok()
        return failure("error: cannot undefine: domain is running")

    with pytest.raises(HostError, match="cannot undefine"):
        Host(refuse, "qemu:///system").undefine("alpha")


def test_restarting_cape_then_killing_the_sniffer_strays(world):
    Host(world, "qemu:///system").restart_cape()

    assert world.calls == [
        ["supervisorctl", "restart", "cape"],
        ["pkill", "-x", "tcpdump"],
    ]


def test_a_failed_cape_restart_is_an_error_with_the_output(world):
    world.cape_fails = True

    with pytest.raises(HostError, match="spawn error"):
        Host(world, "qemu:///system").restart_cape()
