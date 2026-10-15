"""The domain renderer behind guest/steps/lib/render-domain: XML from a context and a path set."""

import copy
import importlib.util
import json
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fixtures.guest_samples import make_guest
from fixtures.profile_samples import sample_profile

from guest_engine.registry import MachineIdentity

REPO = Path(__file__).parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
LIB = REPO / "guest" / "steps" / "lib"


def _load():
    spec = importlib.util.spec_from_file_location("render_domain", LIB / "render_domain.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


render = _load()

IDENTITY = MachineIdentity(
    "11111111-2222-3333-4444-555555555555",
    "00:14:22:ab:cd:ef",
    "7ABCDE1",
    "/7ABCDE1/CN123456789012/",
    "S4EWNX0ABCDEF",
)
INSTALLER = "/media/installer.iso"
EXTRA = "/media/extra.iso"


def paths(**changes: Any):
    base = {
        "disk": "/var/lib/libvirt/images/alpha.qcow2",
        "nvram": "/var/lib/libvirt/nvram/alpha_VARS.fd",
        "installer_media": INSTALLER,
        "extra_media": EXTRA,
    }
    return render.DomainPaths(**{**base, **changes})


def context(profile_name: str = "windows", **guest_changes: Any) -> dict[str, Any]:
    profile = sample_profile(profile_name)
    guest = replace(make_guest("alpha", profile=profile_name), machine=IDENTITY, **guest_changes)
    view = profile.to_dict()
    view.pop("adoption", None)
    # The Linux fixture names a persona that is not installed; the default is the one that is.
    view["hardware"]["persona"] = "default"
    return {"guest": guest.to_dict(), "profile": view}


def with_hardware(base: dict[str, Any], **changes: Any) -> dict[str, Any]:
    changed = copy.deepcopy(base)
    changed["profile"]["hardware"].update(changes)
    return changed


def rendered(ctx: dict[str, Any], mode: str = "run", **path_changes: Any) -> ET.Element:
    return ET.fromstring(render.render_domain(ctx, mode, paths(**path_changes)))  # noqa: S314


def canonical(xml: str) -> str:
    """The XML without insignificant whitespace; a disk's children are order-free to libvirt."""
    root = ET.fromstring(xml)  # noqa: S314
    for disk in root.iter("disk"):
        disk[:] = sorted(disk, key=lambda child: child.tag)
    return ET.canonicalize(ET.tostring(root, encoding="unicode"), strip_text=True)


# --- the Windows hardware block renders the domain M0b proved ---------------------------------


@pytest.mark.parametrize("mode", ["install", "run"])
def test_windows_hardware_renders_the_proven_m0b_domain(mode):
    golden = (FIXTURES / f"render_windows_{mode}.xml").read_text()
    result = render.render_domain(context(), mode, paths())
    assert canonical(result) == canonical(golden)


# --- a Linux-like hardware block: BIOS, no TPM, virtio ----------------------------------------


@pytest.fixture
def linux_domain():
    base = context("ubuntu")
    return rendered(
        with_hardware(
            base,
            boot="bios",
            secure_boot=False,
            tpm=False,
            disk_bus="virtio",
            nic_model="virtio",
            clock="utc",
        )
    )


def test_bios_boot_has_no_firmware_elements(linux_domain):
    assert linux_domain.find("os/loader") is None
    assert linux_domain.find("os/nvram") is None
    assert linux_domain.find("features/smm") is None


def test_no_tpm_means_no_tpm_device(linux_domain):
    assert linux_domain.find("devices/tpm") is None


def test_virtio_disk_and_nic(linux_domain):
    target = linux_domain.find("devices/disk[@device='disk']/target")
    assert (target.get("dev"), target.get("bus")) == ("vda", "virtio")
    assert linux_domain.find("devices/interface/model").get("type") == "virtio"


def test_utc_clock(linux_domain):
    assert linux_domain.find("clock").get("offset") == "utc"


def test_ubuntu_fixture_as_it_is_renders_uefi_with_secure_boot_and_no_tpm():
    domain = rendered(context("ubuntu"))
    assert domain.find("os/loader").get("secure") == "yes"
    assert domain.find("devices/tpm") is None
    assert domain.find("clock").get("offset") == "utc"
    assert domain.find("devices/disk[@device='disk']/target").get("bus") == "sata"


# --- the persona and the guest's own identity ------------------------------------------------


def test_identity_values_come_from_the_guest_record():
    domain = rendered(context())
    system = {entry.get("name"): entry.text for entry in domain.findall("sysinfo/system/entry")}
    assert system["serial"] == IDENTITY.smbios_serial
    assert system["uuid"] == IDENTITY.uuid
    assert domain.find("uuid").text == IDENTITY.uuid
    assert domain.find("devices/interface/mac").get("address") == IDENTITY.mac
    assert domain.find("devices/disk[@device='disk']/serial").text == IDENTITY.disk_serial
    board = domain.find("sysinfo/baseBoard/entry[@name='serial']")
    assert board.text == IDENTITY.board_serial


def test_persona_supplies_the_vendor_strings():
    system = {
        entry.get("name"): entry.text
        for entry in rendered(context()).findall("sysinfo/system/entry")
    }
    assert (system["manufacturer"], system["product"]) == ("Dell Inc.", "OptiPlex 7090")


# libvirt's element is <baseBoard>; it silently drops a lowercase <baseboard>.
def test_baseboard_uses_libvirts_capitalisation():
    text = render.render_domain(context(), "run", paths())
    assert "<baseBoard>" in text
    assert "<baseboard>" not in text


def test_another_persona_is_selected_by_hardware_persona(tmp_path):
    personas = tmp_path / "personas"
    personas.mkdir()
    default = json.loads((REPO / "guest" / "personas" / "default.json").read_text())
    default["system"]["product"] = "ThinkCentre"
    (personas / "lab-desktop.json").write_text(json.dumps(default))
    ctx = with_hardware(context(), persona="lab-desktop")
    domain = ET.fromstring(  # noqa: S314
        render.render_domain(ctx, "run", paths(), personas_dir=personas)
    )
    assert domain.find("sysinfo/system/entry[@name='product']").text == "ThinkCentre"


def test_an_unknown_persona_is_refused_by_name():
    with pytest.raises(render.RenderError, match="no-such-persona"):
        render.render_domain(with_hardware(context(), persona="no-such-persona"), "run", paths())


# --- unknown hardware values fail by name ------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"machine": "pc-i440fx"}, "pc-i440fx"),
        ({"disk_bus": "ide"}, "ide"),
        ({"nic_model": "ne2k"}, "ne2k"),
        ({"boot": "uefi", "secure_boot": False}, "uefi"),
        ({"machine": "../../etc/passwd"}, "../../etc/passwd"),
    ],
)
def test_unsupported_hardware_names_the_value(change, named):
    with pytest.raises(render.RenderError) as refusal:
        render.render_domain(with_hardware(context(), **change), "run", paths())
    assert named in str(refusal.value)


def test_unknown_mode_is_refused():
    with pytest.raises(render.RenderError, match="install"):
        render.render_domain(context(), "boot", paths())


# --- boot order and media ----------------------------------------------------------------------


def test_install_mode_boots_the_cdrom_first_and_attaches_the_media():
    domain = rendered(context(), "install")
    assert [boot.get("dev") for boot in domain.findall("os/boot")] == ["cdrom", "hd"]
    sources = [s.get("file") for s in domain.findall("devices/disk[@device='cdrom']/source")]
    assert sources == [INSTALLER, EXTRA]


def test_run_mode_boots_the_disk_and_ejects_every_cdrom():
    domain = rendered(context(), "run")
    assert [boot.get("dev") for boot in domain.findall("os/boot")] == ["hd"]
    assert domain.findall("devices/disk[@device='cdrom']/source") == []


def test_install_mode_without_extra_media_leaves_that_drive_empty():
    domain = rendered(context(), "install", extra_media=None)
    sources = [s.get("file") for s in domain.findall("devices/disk[@device='cdrom']/source")]
    assert sources == [INSTALLER]


# --- hostile values cannot change the document -------------------------------------------------

HOSTILE = "a<b>&\"c'<!--]]></name><Evil/>"


def test_a_hostile_guest_name_stays_text():
    ctx = context()
    ctx["guest"]["name"] = HOSTILE
    domain = rendered(ctx)
    assert domain.find("name").text == HOSTILE
    assert domain.find(".//Evil") is None


def test_hostile_paths_and_serials_stay_values():
    ctx = context()
    ctx["guest"]["machine"]["disk_serial"] = HOSTILE
    ctx["guest"]["machine"]["smbios_serial"] = HOSTILE
    domain = rendered(ctx, "install", disk=HOSTILE, nvram=HOSTILE, installer_media=HOSTILE)
    assert domain.find("devices/disk[@device='disk']/source").get("file") == HOSTILE
    assert domain.find("devices/disk[@device='disk']/serial").text == HOSTILE
    assert domain.find("os/nvram").text == HOSTILE
    assert domain.findall(".//Evil") == []


# --- the command line --------------------------------------------------------------------------


def run_cli(tmp_path, *arguments: str):
    context_file = tmp_path / "context.json"
    context_file.write_text(json.dumps(context()))
    return subprocess.run(  # noqa: S603
        [str(LIB / "render-domain"), "--context", str(context_file), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_prints_the_domain_xml(tmp_path):
    done = run_cli(
        tmp_path,
        "--mode",
        "install",
        "--disk",
        "/d.qcow2",
        "--nvram",
        "/n.fd",
        "--media",
        INSTALLER,
        "--extra-media",
        EXTRA,
    )
    assert done.returncode == 0, done.stderr
    assert ET.fromstring(done.stdout).find("name").text == "alpha"  # noqa: S314


def test_cli_exits_2_with_a_message_for_unsupported_hardware(tmp_path):
    ctx = with_hardware(context(), disk_bus="ide")
    (tmp_path / "context.json").write_text(json.dumps(ctx))
    done = subprocess.run(  # noqa: S603
        [
            str(LIB / "render-domain"),
            "--context",
            str(tmp_path / "context.json"),
            "--mode",
            "run",
            "--disk",
            "/d",
            "--nvram",
            "/n",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 2
    assert "ide" in done.stderr
