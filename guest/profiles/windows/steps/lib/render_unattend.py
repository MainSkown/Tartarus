#!/usr/bin/python3
"""Renders the Windows answer file and the provisioning parameter file from the guest's record.

Usage: render_unattend.py <answer file> <parameters file>   (reads TT_GUEST_JSON and TT_PROFILE_DIR)

Every value is XML-escaped before it is substituted, so no value can change the document, and the
product key element is built here: Setup fails without a message on an empty one, so with no key it
is absent. The password is in the answer file, hence the file is created readable by its owner only.

provision.ps1 reads its parameters from the second file instead of the first-logon command line:
Windows 10 silently skips a long RunOnce command, and Setup stores that command there.
"""

import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from string import Template
from typing import Any
from xml.sax.saxutils import escape

TEMPLATE_FILE = "autounattend.xml.tpl"
NAMES_FILE = "names.json"
KEYBOARDS_FILE = "keyboards.json"
QUOTE_ENTITIES = {'"': "&quot;", "'": "&apos;"}
# What XML 1.0 forbids as a character: control characters other than tab, line feed and
# carriage return, and the two non-characters U+FFFE and U+FFFF.
XML_FORBIDDEN = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
OWNER_ONLY = 0o600
ARGUMENT_COUNT = 3  # the program name and the two output files
# powershell.exe -File passes every argument as a string and cannot bind one to a [bool], so the
# switches of provision.ps1 are integers.
POWERSHELL_SWITCHES = {True: "1", False: "0"}


class RenderError(ValueError):
    """The record or a table lacks something the answer file needs."""


def xml_text(value: str) -> str:
    if XML_FORBIDDEN.search(value):
        raise RenderError("a value holds a character that cannot be written in XML")
    return escape(value, QUOTE_ENTITIES)


def product_key_block(key: object) -> str:
    stripped = key.strip() if isinstance(key, str) else ""
    # Without the element Setup stops at its product key page; an empty <Key /> with OnError is the
    # form M0b proved, which installs without a key and asks only if Setup truly needs one.
    key_element = f"<Key>{xml_text(stripped)}</Key>" if stripped else "<Key />"
    return f"<ProductKey>{key_element}<WillShowUI>OnError</WillShowUI></ProductKey>"


def _lookup(record: Mapping[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise RenderError(f"the guest record has no {path}")
        value = value[part]
    return value


def _required_text(record: Mapping[str, Any], path: str) -> str:
    value = _lookup(record, path)
    if not isinstance(value, str) or not value:
        raise RenderError(f"the guest record has no {path}")
    return value


def _required_bool(record: Mapping[str, Any], path: str) -> str:
    value = _lookup(record, path)
    if not isinstance(value, bool):
        raise RenderError(f"the guest record's {path} must be true or false")
    return POWERSHELL_SWITCHES[value]


def _input_locale(record: Mapping[str, Any], keyboards: Mapping[str, str]) -> str:
    layout = _required_text(record, "options.keyboard")
    if layout not in keyboards:
        raise RenderError(f"keyboard layout '{layout}' is not in the keyboard table")
    return keyboards[layout]


def placeholder_values(
    record: Mapping[str, Any], names: Mapping[str, str], keyboards: Mapping[str, str]
) -> dict[str, str]:
    """Every placeholder of the template with its raw (not yet escaped) value."""
    return {
        "UI_LANG": _required_text(record, "media.language"),
        "INPUT_LOCALE": _input_locale(record, keyboards),
        "IMAGE_INDEX": _required_text(record, "media.variant"),
        "GUEST_USERNAME": _required_text(record, "identity.account"),
        "GUEST_PASSWORD": _required_text(record, "identity.password"),
        "GUEST_HOSTNAME": _required_text(record, "identity.machine"),
        "CD_MARKER_FILE": names["cd_marker_file"],
        "FIRST_LOGON_DESCRIPTION": names["first_logon_description"],
    }


def provision_parameters(record: Mapping[str, Any], names: Mapping[str, str]) -> dict[str, str]:
    """The parameters of provision.ps1 other than -Media, keyed by their PowerShell names."""
    return {
        "WorkDir": _required_text(record, "work_dir"),
        "GuestIp": _required_text(record, "ip"),
        "Defender": _required_bool(record, "options.defender"),
        "Decoys": _required_bool(record, "options.decoys"),
        "Sysmon": _required_bool(record, "options.sysmon"),
        "FirewallRuleName": names["firewall_rule"],
        "TaskName": names["scheduled_task"],
        "LogName": names["log_file"],
        "DoneMarker": names["done_marker"],
    }


def provision_parameters_json(record: Mapping[str, Any], names: Mapping[str, str]) -> str:
    # json.dumps escapes every non-ASCII character, so PowerShell 5 has no encoding to guess.
    return json.dumps(provision_parameters(record, names), indent=2)


def render_answer_file(
    template: str,
    record: Mapping[str, Any],
    names: Mapping[str, str],
    keyboards: Mapping[str, str],
) -> str:
    escaped = {
        placeholder: xml_text(value)
        for placeholder, value in placeholder_values(record, names, keyboards).items()
    }
    escaped["PRODUCT_KEY_BLOCK"] = product_key_block(_lookup(record, "options").get("key"))
    try:
        return Template(template).substitute(escaped)
    except KeyError as missing:
        raise RenderError(f"the template needs {missing.args[0]}, which nothing fills") from None
    except ValueError as malformed:
        raise RenderError(f"the template is malformed: {malformed}") from None


def _write_owner_only(path: Path, text: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, OWNER_ONLY)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    path.chmod(OWNER_ONLY)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str]) -> int:
    if len(argv) != ARGUMENT_COUNT:
        sys.stderr.write("usage: render_unattend.py <answer file> <parameters file>\n")
        return 2
    profile_dir = Path(os.environ["TT_PROFILE_DIR"])
    record = _load(Path(os.environ["TT_GUEST_JSON"]))
    names = _load(profile_dir / NAMES_FILE)
    try:
        answer_file = render_answer_file(
            (profile_dir / TEMPLATE_FILE).read_text(encoding="utf-8"),
            record,
            names,
            _load(profile_dir / KEYBOARDS_FILE),
        )
        parameters = provision_parameters_json(record, names)
    except RenderError as problem:
        sys.stderr.write(f"render_unattend: {problem}\n")
        return 1
    _write_owner_only(Path(argv[1]), answer_file)
    _write_owner_only(Path(argv[2]), parameters)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
