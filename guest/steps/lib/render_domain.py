"""Renders a guest's libvirt domain XML from its context, the hardware fragments and a persona.

`render-domain` is the command line over this module; the generic steps and the profiles' own
steps (install, provision) all call it, so there is one implementation of the domain.
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any
from xml.sax.saxutils import escape

MODES = ("install", "run")
BOOT_ORDER = {"install": "<boot dev='cdrom'/>\n<boot dev='hd'/>", "run": "<boot dev='hd'/>"}
FRAGMENT_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*")
PERSONA_NAME = re.compile(r"[a-z][a-z0-9-]{1,31}")
BLOCK_LINE = re.compile(r"(?P<indent>[ \t]*)\$\{(?P<name>\w+)\}[ \t]*")
KIB_PER_MIB = 1024
REFUSED = 2

# Where the domain and persona files sit: beside the steps in the image, under guest/ in a checkout.
DATA_ROOT = Path(__file__).resolve().parents[2]
ATTRIBUTE_ESCAPES = {"'": "&apos;", '"': "&quot;"}


class RenderError(Exception):
    pass


@dataclass(frozen=True)
class DomainPaths:
    """Files the domain refers to; the media are attached in install mode only."""

    disk: str
    nvram: str
    installer_media: str | None = None
    extra_media: str | None = None


def render_domain(
    context: Mapping[str, Any],
    mode: str,
    paths: DomainPaths,
    *,
    domain_dir: Path = DATA_ROOT / "domain",
    personas_dir: Path = DATA_ROOT / "personas",
) -> str:
    if mode not in MODES:
        raise RenderError(f"mode must be one of {', '.join(MODES)}, not '{mode}'")
    guest, hardware = context["guest"], context["profile"]["hardware"]
    scalars = _scalars(guest, hardware, paths)
    blocks = {
        placeholder: _fragment(domain_dir, name, value, scalars)
        for placeholder, (name, value) in _fragment_choices(hardware).items()
    }
    blocks["sysinfo"] = _sysinfo(_persona(personas_dir, hardware["persona"]), guest["machine"])
    blocks["boot_order"] = BOOT_ORDER[mode]
    blocks["install_drives"] = _install_drives(paths) if mode == "install" else ""
    xml = _fill((domain_dir / "domain.xml.tpl").read_text(), scalars, blocks)
    _require_well_formed(xml)
    return xml


def _fragment_choices(hardware: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    """Placeholder -> (fragment name, value) for each hardware choice the profile makes."""
    return {
        "boot": ("boot", _boot_value(hardware)),
        "secure_boot": ("secure_boot", "on" if hardware["secure_boot"] else "off"),
        "tpm": ("tpm", "tpm-2.0" if hardware["tpm"] else "none"),
        "disk_bus": ("disk_bus", hardware["disk_bus"]),
        "nic_model": ("nic_model", hardware["nic_model"]),
        "clock": ("clock", hardware["clock"]),
        "machine_controllers": ("machine", hardware["machine"]),
    }


def _boot_value(hardware: Mapping[str, Any]) -> str:
    if hardware["boot"] == "bios":
        return "bios"
    return "uefi-secureboot" if hardware["secure_boot"] else "uefi"


def _fragment(domain_dir: Path, name: str, value: str, scalars: Mapping[str, str]) -> str:
    path = domain_dir / "fragments" / f"{name}.{value}.xml"
    if not FRAGMENT_VALUE.fullmatch(value) or not path.is_file():
        available = sorted(
            file.name.split(".", 1)[1].removesuffix(".xml")
            for file in (domain_dir / "fragments").glob(f"{name}.*.xml")
        )
        raise RenderError(
            f"hardware {name} '{value}' is not supported (available: {', '.join(available)})"
        )
    return Template(path.read_text()).substitute(scalars)


def _scalars(
    guest: Mapping[str, Any], hardware: Mapping[str, Any], paths: DomainPaths
) -> dict[str, str]:
    machine, resources = guest["machine"], guest["resources"]
    raw = {
        "name": guest["name"],
        "uuid": machine["uuid"],
        "mac": machine["mac"],
        "disk_serial": machine["disk_serial"],
        "vcpus": resources["vcpus"],
        "ram_kib": resources["ram_mb"] * KIB_PER_MIB,
        "machine": hardware["machine"],
        "disk": paths.disk,
        "nvram": paths.nvram,
    }
    return {key: escape(str(value), ATTRIBUTE_ESCAPES) for key, value in raw.items()}


def _media_source(path: str | None) -> str:
    return f"<source file='{escape(path, ATTRIBUTE_ESCAPES)}'/>" if path else ""


def _install_drives(paths: DomainPaths) -> str:
    """The two optical drives of an installation. An absent medium leaves a blank line, which
    `_fill` drops, so that drive is attached empty as before."""
    return f"""<disk type='file' device='cdrom'>
  <driver name='qemu' type='raw'/>
  {_media_source(paths.installer_media)}
  <target dev='sdb' bus='sata'/>
  <readonly/>
  <address type='drive' controller='0' bus='0' target='0' unit='1'/>
</disk>
<disk type='file' device='cdrom'>
  <driver name='qemu' type='raw'/>
  {_media_source(paths.extra_media)}
  <target dev='sdc' bus='sata'/>
  <readonly/>
  <address type='drive' controller='0' bus='0' target='0' unit='2'/>
</disk>"""


def _persona(personas_dir: Path, name: str) -> dict[str, Any]:
    path = personas_dir / f"{name}.json"
    if not PERSONA_NAME.fullmatch(name) or not path.is_file():
        raise RenderError(f"hardware persona '{name}' is not an installed persona")
    return json.loads(path.read_text())


# libvirt's element is <baseBoard>; it silently drops a lowercase <baseboard>.
SYSINFO_SECTIONS = {
    "bios": "bios",
    "system": "system",
    "baseboard": "baseBoard",
    "chassis": "chassis",
}


def _sysinfo(persona: Mapping[str, Any], machine: Mapping[str, str]) -> str:
    root = ET.Element("sysinfo", type="smbios")
    for key, element in SYSINFO_SECTIONS.items():
        section = ET.SubElement(root, element)
        for entry_name, value in persona[key].items():
            ET.SubElement(section, "entry", name=entry_name).text = Template(value).substitute(
                machine
            )
    strings = ET.SubElement(root, "oemStrings")
    for value in persona["oem_strings"]:
        ET.SubElement(strings, "entry").text = value
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


def _fill(skeleton: str, scalars: Mapping[str, str], blocks: Mapping[str, str]) -> str:
    """Substitute line by line: a block fills a whole line, a scalar is never re-read."""
    lines: list[str] = []
    for line in skeleton.splitlines():
        block = BLOCK_LINE.fullmatch(line)
        if block and block["name"] in blocks:
            parts = [part for part in blocks[block["name"]].splitlines() if part.strip()]
            lines += [block["indent"] + part for part in parts]
        else:
            lines.append(Template(line).substitute(scalars))
    return "\n".join(lines) + "\n"


def _require_well_formed(xml: str) -> None:
    try:
        ET.fromstring(xml)  # noqa: S314 - our own output
    except ET.ParseError as error:
        raise RenderError(f"the rendered domain is not well-formed XML ({error})") from None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="render-domain", description=__doc__)
    parser.add_argument("--context", default=os.environ.get("TT_CONTEXT_JSON"))
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--disk", required=True)
    parser.add_argument("--nvram", required=True)
    parser.add_argument("--media", help="the installation medium, attached in install mode")
    parser.add_argument("--extra-media", help="a second disc, attached in install mode")
    arguments = parser.parse_args(argv)
    if not arguments.context:
        sys.stderr.write("render-domain: no --context and TT_CONTEXT_JSON is not set\n")
        return REFUSED
    paths = DomainPaths(arguments.disk, arguments.nvram, arguments.media, arguments.extra_media)
    try:
        context = json.loads(Path(arguments.context).read_text())
        sys.stdout.write(render_domain(context, arguments.mode, paths))
    except (RenderError, OSError, ValueError, KeyError) as error:
        sys.stderr.write(f"render-domain: {error}\n")
        return REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
