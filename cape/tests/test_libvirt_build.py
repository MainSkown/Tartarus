"""The libvirt the image runs is built from a pinned, checksum-verified source tarball.

QEMU 11 removed what Ubuntu 24.04's libvirt 10.0 relies on to revert a snapshot and to save memory,
so libvirt is built from source in its own stage. The measured behaviour (the guest reverts and
runs, the polkit access driver refuses `cape`) is proven against a running container by
scripts/verify-guest.sh and scripts/verify-cape-hardening.sh; these keep the Dockerfile from
drifting away from it.
"""

import re
import shlex
from pathlib import Path

CAPE = Path(__file__).resolve().parents[1]
DOCKERFILE = (CAPE / "Dockerfile").read_text()
UBUNTU_BASE = "FROM ubuntu:24.04@sha256:"


def stage(name: str) -> str:
    start = DOCKERFILE.rindex(UBUNTU_BASE, 0, DOCKERFILE.index(f" AS {name}\n") + 1)
    following = DOCKERFILE.find(UBUNTU_BASE, start + 1)
    return DOCKERFILE[start : following if following != -1 else len(DOCKERFILE)]


def runtime_stage() -> str:
    return DOCKERFILE[DOCKERFILE.rindex(UBUNTU_BASE) :]


def instructions(text: str) -> str:
    """The Dockerfile without comments, line continuations joined."""
    uncommented = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return uncommented.replace("\\\n", " ")


def meson_setup_arguments() -> list[str]:
    command = re.search(r"meson setup (.*?)(?:&&|\n)", instructions(stage("libvirt-build")))
    assert command, "the libvirt stage runs meson setup"
    return shlex.split(command.group(1))


def test_the_stage_starts_from_the_same_pinned_ubuntu_as_the_qemu_stage():
    qemu_base = stage("qemu-build").splitlines()[0].split(" AS ")[0]

    assert stage("libvirt-build").splitlines()[0].split(" AS ")[0] == qemu_base


def test_the_version_and_the_sha256_of_the_tarball_are_build_arguments():
    libvirt = stage("libvirt-build")

    assert re.search(r"^ARG LIBVIRT_VERSION=12\.\d+\.\d+$", libvirt, re.MULTILINE)
    assert re.search(r"^ARG LIBVIRT_SHA256=[0-9a-f]{64}$", libvirt, re.MULTILINE)


def test_libvirt_is_a_release_that_has_stopped_using_what_qemu_11_removed():
    version = re.search(r"^ARG LIBVIRT_VERSION=(\d+)\.(\d+)\.", stage("libvirt-build"), re.M)
    assert version

    assert (int(version[1]), int(version[2])) >= (12, 1)


def test_the_tarball_is_checksum_verified_before_it_is_unpacked_or_built():
    libvirt = instructions(stage("libvirt-build"))
    download = libvirt.index("https://libvirt.org/sources/libvirt-${LIBVIRT_VERSION}.tar.xz")
    verified = libvirt.index('echo "${LIBVIRT_SHA256}  ')

    assert download < verified < libvirt.index("tar ") < libvirt.index("meson setup")
    assert "sha256sum -c -" in libvirt[verified:]


def test_the_build_installs_into_a_staging_directory_the_runtime_stage_copies():
    libvirt = instructions(stage("libvirt-build"))

    assert "DESTDIR=/out/root meson install" in libvirt
    assert re.search(r"COPY --from=libvirt-build /out/root/? /\n", runtime_stage()), (
        "the whole staging tree lands on /"
    )


def test_every_path_is_the_one_ubuntus_package_used():
    options = meson_setup_arguments()

    assert "--prefix=/usr" in options
    assert "--sysconfdir=/etc" in options
    assert "--localstatedir=/var" in options
    assert "-Drunstatedir=/run" in options
    assert "--libdir=lib/x86_64-linux-gnu" in options
    assert "--libexecdir=lib/libvirt" in options, "dnsmasq's lease helper stays in /usr/lib/libvirt"


def test_qemu_runs_as_the_users_ubuntus_package_created():
    options = meson_setup_arguments()

    assert "-Dqemu_user=libvirt-qemu" in options
    assert "-Dqemu_group=kvm" in options


def test_the_container_uses_polkit_and_nothing_that_confines_with_a_host_policy():
    options = meson_setup_arguments()

    assert "-Dpolkit=enabled" in options
    confinement = (
        "apparmor",
        "secdriver_apparmor",
        "apparmor_profiles",
        "selinux",
        "secdriver_selinux",
    )
    for off in confinement:
        assert f"-D{off}=disabled" in options


def test_only_the_drivers_the_container_uses_are_built():
    options = meson_setup_arguments()

    for on in ("driver_qemu", "driver_network", "driver_storage", "driver_remote", "libvirtd"):
        assert f"-D{on}=enabled" in options
    for off in (
        "driver_lxc",
        "driver_libxl",
        "driver_ch",
        "driver_bhyve",
        "driver_esx",
        "driver_vbox",
        "driver_vmware",
        "driver_openvz",
        "driver_hyperv",
        "driver_vz",
        "driver_test",
        "driver_nodedev",
        "driver_interface",
        "driver_nwfilter",
        "tests",
    ):
        assert f"-D{off}=disabled" in options


def test_clients_reach_the_monolithic_daemon_not_a_per_driver_one():
    assert "-Dremote_default_mode=legacy" in meson_setup_arguments()


def test_the_network_driver_keeps_the_iptables_rules_libvirt_10_wrote():
    # Libvirt 12 prefers nftables when no priority is given, which the rooter's iptables rules
    # were not written against.
    assert "-Dfirewall_backend_priority=iptables" in meson_setup_arguments()


def test_the_runtime_libraries_are_computed_from_what_the_build_installed():
    libvirt = instructions(stage("libvirt-build"))

    assert "COPY cape/build/runtime-packages.sh" in libvirt
    assert re.search(r"\./runtime-packages\.sh .*> /out/runtime-packages", libvirt)
    assert "COPY --from=libvirt-build /out/runtime-packages /tmp/libvirt/" in runtime_stage()
    assert re.search(r"\$\(cat [^)]*/tmp/libvirt/runtime-packages", instructions(runtime_stage()))


def test_no_ubuntu_libvirt_package_is_installed_anywhere():
    packages = re.findall(
        r"\blibvirt(?:-daemon[\w-]*|-clients|-dev|-bin|0|-sanlock[\w-]*)\b",
        instructions(DOCKERFILE),
    )

    assert packages == []


def test_what_the_ubuntu_daemon_package_pulled_in_is_installed_explicitly():
    apt = instructions(runtime_stage())

    for needed in ("dbus", "dmidecode", "polkitd", "dnsmasq-base", "iproute2", "iptables", "swtpm"):
        assert re.search(rf"\b{needed}\b", apt.split("apt-get install")[1].split("&&")[0])


def test_the_users_and_groups_ubuntus_package_made_exist_before_the_gids_move():
    image = instructions(runtime_stage())
    created = image.index("groupadd --system libvirt")
    moved = image.index("for group in cape libvirt kvm libvirt-dnsmasq")

    assert created < image.index("usermod -aG libvirt,kvm cape") < moved
    assert re.search(r"groupadd --system --gid 64055 libvirt-qemu", image)
    assert re.search(r"useradd --system --uid 64055 --gid kvm .*libvirt-qemu", image)
    assert re.search(r"groupadd --system libvirt-dnsmasq", image)
    assert re.search(r"useradd --system --gid libvirt-dnsmasq .*libvirt-dnsmasq", image)


def test_dnsmasq_runs_as_libvirt_dnsmasq_which_only_ubuntus_libvirt_asked_for():
    template = (CAPE / "templates" / "tt-guest.xml").read_text()

    assert "<dnsmasq:option value='user=libvirt-dnsmasq'/>" in template


def test_libvirt_python_is_built_against_the_source_built_libvirt_it_is_pinned_to():
    build = instructions(stage("cape-build"))

    assert "COPY --from=libvirt-build /out/root/usr /usr" in build
    assert "libvirt-python==$(pkg-config --modversion libvirt)" in build
    assert build.index("COPY --from=libvirt-build") < build.index("libvirt-python==")


def test_the_api_description_for_the_python_bindings_is_built_but_no_manual_ships():
    # libvirt-api.xml comes out of the documentation build, so docs stay on; the pages are not
    # shipped.
    libvirt = instructions(stage("libvirt-build"))

    assert "-Ddocs=enabled" in meson_setup_arguments()
    assert re.search(r"rm -rf [^&]*/out/root/usr/share/doc[^&]*/out/root/usr/share/man", libvirt)


def test_every_firmware_descriptor_qemu_installs_stays_because_libvirt_12_parses_them_all():
    # libvirt 10.0 aborted the lookup on QEMU's loongarch64 descriptor, so the image deleted every
    # descriptor but the x86_64 ones.
    assert "/usr/share/qemu/firmware" not in instructions(DOCKERFILE)
