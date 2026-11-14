"""No program in the cape container holds SYS_ADMIN (the last open item of the 2026-11-12 audit).

Root with SYS_ADMIN can remount /proc/sys writable and reach the host kernel's settings. The
entrypoint needs it for one mount, so the container is given it, and the entrypoint takes it out of
the bounding set when it hands over to supervisord: nothing started afterwards can get it back,
whatever it runs. libvirt is configured not to need it. The measured behaviour is proven against a
running container by scripts/verify-cape-hardening.sh; these keep the files from drifting.
"""

from pathlib import Path

CAPE = Path(__file__).resolve().parents[1]


def active_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_the_entrypoint_hands_over_to_supervisord_without_sys_admin():
    last = active_lines(CAPE / "entrypoint.sh")[-1]

    assert last == (
        "exec setpriv --bounding-set -sys_admin --inh-caps -sys_admin "
        "supervisord -n -c /etc/supervisor/supervisord.conf"
    )


def test_the_one_mount_happens_in_the_entrypoint_before_the_hand_over():
    entrypoint = (CAPE / "entrypoint.sh").read_text()

    assert entrypoint.index("\nmake_network_sysctls_writable\n") < entrypoint.index("exec setpriv")


def test_libvirt_gives_qemu_no_mount_namespace_of_its_own():
    # Entering a mount namespace takes SYS_ADMIN. The namespace hides /dev from QEMU, and the
    # container's /dev already holds only the devices docker-compose.yml lists.
    assert "namespaces = [ ]" in active_lines(CAPE / "libvirt" / "qemu.conf")


def test_libvirt_does_not_record_file_owners_in_trusted_attributes():
    # Writing a trusted.* attribute takes SYS_ADMIN: without it libvirt cannot set up a domain.
    assert "remember_owner = 0" in active_lines(CAPE / "libvirt" / "qemu.conf")
