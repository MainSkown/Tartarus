"""The patch that sends CAPE's libvirt machinery through the machine broker for its three writes.

It is applied to a verbatim excerpt of CAPE's `lib/cuckoo/common/abstracts.py` (its imports and
`LibVirtMachinery`, from the pinned CAPE_REF): the anchors must match it exactly once, and the
patched class runs against stand-ins for libvirt and the broker client.
"""

import importlib.util
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

CAPE = Path(__file__).resolve().parent.parent
EXCERPT = (CAPE / "tests" / "fixtures" / "abstracts_libvirt_excerpt.txt").read_text()
CLASS_START = "class LibVirtMachinery"
BROKER_IMPORT = "from lib.cuckoo.common import machine_broker_client\n"


def load_patch():
    spec = importlib.util.spec_from_file_location(
        "machinery_through_broker", CAPE / "patches" / "machinery-through-broker.py"
    )
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    return patch


@pytest.fixture
def patch():
    return load_patch()


@pytest.fixture
def patched(patch):
    return patch.patched(EXCERPT)


def test_the_patched_source_is_valid_python(patched):
    compile(patched, "abstracts.py", "exec")


def test_the_machinery_imports_the_client_that_ships_into_the_cape_tree(patched):
    header = patched[: patched.index(CLASS_START)]

    assert header.count(BROKER_IMPORT) == 1


def test_the_machinery_no_longer_writes_to_libvirt_itself(patched):
    machinery = patched[patched.index(CLASS_START) :]

    for write in ("revertToSnapshot", "coreDump", ".destroy(", "open(path"):
        assert write not in machinery


@pytest.mark.parametrize(
    "anchor",
    [
        "vm.revertToSnapshot(snapshot, flags=0)",
        "vm.destroy()  # Machete's way!",
        "vm.coreDump(path, flags=libvirt.VIR_DUMP_MEMORY_ONLY)",
        "from lib.cuckoo.common.dictionary import Dictionary\n",
    ],
)
def test_the_patch_gives_up_when_an_anchor_moved(patch, anchor):
    with pytest.raises(SystemExit, match="exactly once, found 0"):
        patch.patched(EXCERPT.replace(anchor, "# moved\n"))


def test_the_patch_gives_up_when_an_anchor_is_ambiguous(patch):
    class_source = EXCERPT[EXCERPT.index(CLASS_START) :]

    with pytest.raises(SystemExit, match="exactly once, found 2"):
        patch.patched(EXCERPT + "\n\n" + class_source)


class LibvirtError(Exception):
    pass


class MachineError(Exception):
    pass


class BrokerError(Exception):
    pass


class Vm:
    """A libvirt domain that fails the test if the machinery tries to write to it."""

    def __init__(self, active=True):
        self.active = active

    def snapshotListNames(self, flags=0):  # noqa: N802 - libvirt's name
        return ["tartarus-clean"]

    def snapshotLookupByName(self, name, flags=0):  # noqa: N802 - libvirt's name
        return SimpleNamespace(getName=lambda: name)

    def isActive(self):  # noqa: N802 - libvirt's name
        return self.active

    def revertToSnapshot(self, *_arguments, **_options):  # noqa: N802 - libvirt's name
        raise AssertionError("reverted through libvirt directly")

    def destroy(self):
        raise AssertionError("destroyed through libvirt directly")

    def coreDump(self, *_arguments, **_options):  # noqa: N802 - libvirt's name
        raise AssertionError("dumped through libvirt directly")


class Broker:
    def __init__(self, error=None):
        self.error = error
        self.asked: list[tuple] = []
        self.dumped: list[tuple] = []

    def ask(self, operation, label, *rest):
        self.asked.append((operation, label, *rest))
        if self.error:
            raise self.error

    def dump_memory(self, label, path, dump_path_of):
        self.dumped.append((label, path, dump_path_of(7)))
        if self.error:
            raise self.error


class Machinery:
    POWEROFF = "poweroff"
    RUNNING = "running"


@pytest.fixture
def machines(patched):
    broker = Broker()
    scope = {
        "libvirt": SimpleNamespace(libvirtError=LibvirtError, VIR_DUMP_MEMORY_ONLY=2),
        "CuckooMachineError": MachineError,
        "machine_broker_client": SimpleNamespace(
            REVERT="revert",
            STOP="stop",
            MachineBrokerError=BrokerError,
            ask=broker.ask,
            dump_memory=broker.dump_memory,
        ),
        "get_memdump_path": lambda task_id, analysis_folder=False: (
            f"/analyses/{task_id}/memory.dmp" if analysis_folder else f"/mnt/tmpfs/{task_id}.dmp"
        ),
        "log": SimpleNamespace(debug=lambda *_: None, warning=lambda *_: None),
        "Machinery": Machinery,
        "threading": threading,
    }
    exec(compile(patched[patched.index(CLASS_START) :], "abstracts.py", "exec"), scope)  # noqa: S102 - the test's own fixture
    machinery = scope["LibVirtMachinery"].__new__(scope["LibVirtMachinery"])
    machinery.db = SimpleNamespace(
        view_machine_by_label=lambda _label: SimpleNamespace(snapshot="tartarus-clean")
    )
    machinery.statuses = []
    machinery._status = lambda _label: machinery.status
    machinery.status = "poweroff"
    machinery._connect = lambda _label=None: SimpleNamespace(lookupByName=lambda _l: machinery.vm)
    machinery._wait_status = lambda label, state: machinery.statuses.append((label, state))
    machinery.vm = Vm()
    machinery.broker = broker
    return machinery


def test_start_reverts_through_the_broker_and_waits_for_the_guest_to_run(machines):
    machines.start("win")

    assert machines.broker.asked == [("revert", "win")]
    assert machines.statuses == [("win", "running")]


def test_start_still_refuses_a_guest_that_is_not_powered_off(machines):
    machines.status = "running"

    with pytest.raises(MachineError, match="not been turned off"):
        machines.start("win")

    assert machines.broker.asked == []


def test_start_still_needs_a_snapshot_to_exist(machines):
    machines.vm.snapshotListNames = lambda **_options: []
    machines._get_snapshot = lambda _label, _vm: None

    with pytest.raises(MachineError, match="No snapshot found"):
        machines.start("win")

    assert machines.broker.asked == []


def test_a_broker_that_refuses_the_revert_is_the_error_cape_raises_today(machines):
    machines.broker.error = BrokerError("win is not a registered guest")

    with pytest.raises(
        MachineError, match="Unable to restore snapshot on virtual machine win"
    ) as raised:
        machines.start("win")

    assert "win is not a registered guest" in str(raised.value)
    assert machines.statuses == []


def test_stop_powers_off_through_the_broker_and_waits_for_the_guest_to_stop(machines):
    machines.status = "running"

    machines.stop("win")

    assert machines.broker.asked == [("stop", "win")]
    assert machines.statuses == [("win", "poweroff")]


def test_stop_leaves_an_inactive_domain_alone(machines):
    machines.status = "running"
    machines.vm.active = False

    machines.stop("win")

    assert machines.broker.asked == []


def test_stop_still_refuses_a_guest_that_is_already_stopped(machines):
    with pytest.raises(MachineError, match="already stopped"):
        machines.stop("win")


def test_a_broker_that_fails_the_stop_is_the_error_cape_raises_today(machines):
    machines.status = "running"
    machines.broker.error = BrokerError("libvirt: domain is not running")

    with pytest.raises(MachineError, match="Error stopping virtual machine win") as raised:
        machines.stop("win")

    assert "libvirt: domain is not running" in str(raised.value)
    assert machines.statuses == []


def test_a_memory_dump_goes_through_the_broker_with_the_path_cape_chose(machines):
    machines.dump_memory("win", "/analyses/7/memory.dmp")

    assert machines.broker.dumped == [("win", "/analyses/7/memory.dmp", "/analyses/7/memory.dmp")]


def test_the_dump_path_check_is_against_the_analysis_folder_not_the_tmpfs(machines):
    machines.dump_memory("win", "/analyses/7/memory.dmp")

    assert machines.broker.dumped[0][2] == "/analyses/7/memory.dmp"


def test_a_broker_that_fails_the_dump_is_the_error_cape_raises_today(machines):
    machines.broker.error = BrokerError("the memory dump could not be placed")

    with pytest.raises(MachineError, match="Error dumping memory virtual machine win"):
        machines.dump_memory("win", "/analyses/7/memory.dmp")


def test_the_patch_writes_the_patched_file(patch, tmp_path, monkeypatch):
    target = tmp_path / "abstracts.py"
    target.write_text(EXCERPT)
    monkeypatch.setattr("sys.argv", ["machinery-through-broker.py", str(target)])

    patch.main()

    assert BROKER_IMPORT in target.read_text()


def test_the_patch_needs_exactly_the_file_to_patch(patch, monkeypatch):
    monkeypatch.setattr("sys.argv", ["machinery-through-broker.py"])

    with pytest.raises(SystemExit, match="usage"):
        patch.main()
