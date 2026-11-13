#!/usr/bin/python3
"""Patches CAPE's libvirt machinery (lib/cuckoo/common/abstracts.py, `LibVirtMachinery`) so that
reverting a guest, powering it off and dumping its memory go through the machine broker.

The `cape` user, which runs CAPE and parses hostile sample output, has no libvirt write permission
(audit finding 1): libvirt cannot grant a revert or a core dump without also granting a root-owned
write at an arbitrary place. `machine-broker` does those three things as root for a registered
guest (cape/bin/machine_broker_logic.py); CAPE's reads stay direct over libvirt. The broker
client ships beside this file's target as `lib/cuckoo/common/machine_broker_client.py`.

`start`, `stop` and `dump_memory` keep their checks, their state waits and the `CuckooMachineError`
CAPE raises today; only the call that wrote to libvirt is replaced. `dump_memory` no longer creates
the file first: the broker creates it, exclusively, in the analysis folder. A dump path that is not
the analysis folder's `memory.dmp` (CAPE's tmpfs option moves it elsewhere) is refused.

Usage: machinery-through-broker.py <abstracts.py>. Every anchor must match exactly once, otherwise
nothing is written and the exit status is non-zero, so a CAPE_REF bump that moves the code fails the
build instead of silently leaving `cape` to write to libvirt.
"""

import sys
from pathlib import Path

IMPORT_ANCHOR = "from lib.cuckoo.common.dictionary import Dictionary\n"

REVERT_ANCHOR = """\
            vm.revertToSnapshot(snapshot, flags=0)
        except libvirt.libvirtError as e:
            raise CuckooMachineError(f"Unable to restore snapshot on virtual machine {label}. Your snapshot MUST BE in running state!") from e
"""

STOP_ANCHOR = """\
                vm.destroy()  # Machete's way!
        except libvirt.libvirtError as e:
"""

DUMP_ANCHOR = """\
        conn = self._connect(label)
        try:
            # create the memory dump file ourselves first so it doesn't end up root/root 0600
            # it'll still be owned by root, so we can't delete it, but at least we can read it
            fd = open(path, "w")
            fd.close()
            vm = conn.lookupByName(label)
            vm.coreDump(path, flags=libvirt.VIR_DUMP_MEMORY_ONLY)
        except libvirt.libvirtError as e:
"""

REPLACEMENTS = {
    "import": (
        IMPORT_ANCHOR,
        IMPORT_ANCHOR + "from lib.cuckoo.common import machine_broker_client\n",
    ),
    "revert": (
        REVERT_ANCHOR,
        """\
            # Tartarus: the machine broker reverts to the snapshot it has on record for this guest.
            machine_broker_client.ask(machine_broker_client.REVERT, label)
        except machine_broker_client.MachineBrokerError as e:
            raise CuckooMachineError(f"Unable to restore snapshot on virtual machine {label}: {e}. Your snapshot MUST BE in running state!") from e
""",
    ),
    "stop": (
        STOP_ANCHOR,
        """\
                # Tartarus: the machine broker destroys it.
                machine_broker_client.ask(machine_broker_client.STOP, label)
        except (libvirt.libvirtError, machine_broker_client.MachineBrokerError) as e:
""",
    ),
    "dump": (
        DUMP_ANCHOR,
        """\
        try:
            # Tartarus: the machine broker dumps into a root-only staging folder, then places the file.
            machine_broker_client.dump_memory(
                label, path, lambda task_id: get_memdump_path(task_id, analysis_folder=True)
            )
        except machine_broker_client.MachineBrokerError as e:
""",
    ),
}


def patched(source: str) -> str:
    for anchor, replacement in REPLACEMENTS.values():
        found = source.count(anchor)
        if found != 1:
            raise SystemExit(
                f"machinery-through-broker: expected the anchor exactly once, found {found}:\n{anchor}"
            )
        source = source.replace(anchor, replacement)
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: machinery-through-broker.py <abstracts.py>")
    target = Path(sys.argv[1])
    target.write_text(patched(target.read_text(encoding="utf-8")), encoding="utf-8")


if __name__ == "__main__":
    main()
