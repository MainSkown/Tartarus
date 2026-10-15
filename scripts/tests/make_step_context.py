#!/usr/bin/env python3
"""Writes a build's `context.json` and `guest.json` for the tests of the Windows build steps.

Usage: make_step_context.py <output dir> <agent port> <libvirt dir> <media dir>

The guest is a record the engine's own code makes (cape/tests/fixtures), the profile is the real
Windows profile, and the guest's address is the loopback one the fake agent listens on.
"""

import dataclasses
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "cape"), str(REPO / "cape" / "tests")]

from fixtures.guest_samples import make_guest  # noqa: E402

from guest_engine.profile import parse_profile  # noqa: E402

WORK_DIR = "C:\\ProgramData\\abcdefgh"
PASSWORD = "Sup3r-secret-pw"  # noqa: S105 - a fixture value the tests look for in the output
OPTIONS = {
    "defender": True,
    "decoys": False,
    "sysmon": True,
    "key": "",
    "keyboard": "Polish (Programmers)",
}


def main(output: Path, agent_port: int, libvirt_dir: Path, media_dir: Path) -> None:
    profile_data = json.loads((REPO / "guest/profiles/windows/profile.json").read_text())
    profile = parse_profile(profile_data).to_dict()
    del profile["adoption"]
    guest = dataclasses.replace(
        make_guest("alpha", ip="127.0.0.1"),
        work_dir=WORK_DIR,
        options=OPTIONS,
        identity=dataclasses.replace(make_guest("alpha").identity, password=PASSWORD),
    ).to_dict()
    profile["agent"]["port"] = agent_port
    context = {
        "guest": guest,
        "profile": profile,
        "source": None,
        "build": {"id": "b1", "kind": "build", "steps": []},
        "host": {
            "subnet": "192.168.150.0/24",
            "gateway": "192.168.150.1",
            "registry_root": str(libvirt_dir / "tartarus" / "guests"),
            "libvirt_dir": str(libvirt_dir),
            "media_dir": str(media_dir),
            "registration_dir": str(libvirt_dir / "tartarus" / "kvm.conf.d"),
            "libvirt_uri": "qemu:///system",
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "context.json").write_text(json.dumps(context, indent=2))
    (output / "guest.json").write_text(json.dumps(guest, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
