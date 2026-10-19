"""What a Volatility3 row means: the finding, its address, and the detection it raises.

Only `windows.malware.malfind` and `windows.malware.hollowprocesses` have findings; the other
plugins are context. Mapping and severities: docs/specs/data-model.md, "volatility".
"""

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.ingest.ecs import EventShape, detection_match
from app.ingest.reading import text_or_none, to_int

MALFIND = "windows.malware.malfind"
HOLLOWPROCESSES = "windows.malware.hollowprocesses"
LANE = "memory"
CATEGORIES = ("malware", "process")
PE_HEADER_NOTE = "MZ header"
PROTECTION_LETTERS = {"PAGE_EXECUTE_READWRITE": "RWX", "PAGE_EXECUTE_READ": "RX"}
_HEX_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


@dataclass(frozen=True)
class Rule:
    """The detection a plugin's findings raise, and how its summary reads."""

    id: str
    name: str
    description: str
    action: str
    technique_id: str
    technique_name: str
    what_it_found: str | None
    note_separator: str
    severity: int
    severity_with_pe_header: int
    one_per_pid: bool


RULES: Mapping[str, Rule] = {
    MALFIND: Rule(
        id="volatility.malfind",
        name="Executable private memory region",
        description=(
            "A private memory region of the process is executable and holds code or a PE "
            "image, which is how injected code looks"
        ),
        action="injection-detected",
        technique_id="T1055",
        technique_name="Process Injection",
        what_it_found="an executable private region",
        note_separator=", ",
        severity=2,
        severity_with_pe_header=3,
        one_per_pid=False,
    ),
    HOLLOWPROCESSES: Rule(
        id="volatility.hollowprocesses",
        name="Hollowed process image",
        description=(
            "The process's executable image was replaced in memory: its PEB base address "
            "or its VAD does not match the image it was started from"
        ),
        action="hollowing-detected",
        technique_id="T1055.012",
        technique_name="Process Hollowing",
        what_it_found=None,
        note_separator=": ",
        severity=3,
        severity_with_pe_header=3,
        one_per_pid=True,
    ),
}


@dataclass(frozen=True)
class Finding:
    plugin: str
    index: int
    pid: int
    process_name: str | None
    address: str | None
    protection: str | None
    note: str | None
    row: Mapping[str, Any]
    problems: int = 1

    @property
    def rule(self) -> Rule:
        return RULES[self.plugin]

    @property
    def plugin_name(self) -> str:
        return self.plugin.rsplit(".", 1)[-1]

    @property
    def severity(self) -> int:
        has_pe_header = self.note == PE_HEADER_NOTE
        return self.rule.severity_with_pe_header if has_pe_header else self.rule.severity


def read_finding(plugin: str, index: int, row: object) -> Finding | None:
    """None for a row that is not a mapping or names no process."""
    if not isinstance(row, Mapping) or (pid := to_int(row.get("PID"))) is None:
        return None
    note = text_or_none(row.get("Notes"))
    return Finding(
        plugin=plugin,
        index=index,
        pid=pid,
        process_name=text_or_none(row.get("Process")),
        address=_address(row, note),
        protection=text_or_none(row.get("Protection")),
        note=note,
        row=row,
    )


def one_finding_per_pid(findings: Iterable[Finding]) -> Iterator[Finding]:
    """The findings of one pid become one, at the pid's first row, with every note kept once.

    Volatility gives one row per problem it found in a process, so the notes of a pid are the
    problems of one hollowed image, not findings of their own.
    """
    by_pid: dict[int, list[Finding]] = {}
    for finding in findings:
        by_pid.setdefault(finding.pid, []).append(finding)
    for group in by_pid.values():
        yield _joined(group)


def _joined(group: list[Finding]) -> Finding:
    first = group[0]
    if len(group) == 1:
        return first
    notes = list(dict.fromkeys(finding.note for finding in group if finding.note))
    return replace(first, note="; ".join(notes) or None, problems=len(group))


def _address(row: Mapping[str, Any], note: str | None) -> str | None:
    """`Start VPN` is an integer; hollowprocesses names its address only inside the note."""
    if (start := to_int(row.get("Start VPN"))) is not None:
        return hex(start)
    found = _HEX_ADDRESS.search(note or "")
    return hex(int(found[0], 16)) if found else None


def finding_shape(finding: Finding) -> EventShape:
    return EventShape(
        "memory-finding", CATEGORIES, ("info",), LANE, f"volatility.{finding.plugin_name}"
    )


def detection_shape(finding: Finding) -> EventShape:
    return EventShape(
        finding.rule.action,
        CATEGORIES,
        ("info", "indicator"),
        LANE,
        f"volatility.{finding.plugin_name}",
        "alert",
    )


def memory_section(finding: Finding) -> dict[str, str]:
    optional = {
        "address": finding.address,
        "protection": finding.protection,
        "note": finding.note,
    }
    return {"plugin": finding.plugin} | {k: v for k, v in optional.items() if v is not None}


def process_label(finding: Finding, name: str | None) -> str:
    return f"{name} (pid {finding.pid})" if name else f"pid {finding.pid}"


def finding_summary(finding: Finding, label: str) -> str:
    rule = finding.rule
    summary = f"{finding.plugin_name} found {_what_it_found(finding)} in {label}"
    if finding.address:
        summary += f" at {finding.address}"
    if finding.protection:
        summary += f", {PROTECTION_LETTERS.get(finding.protection, finding.protection)}"
    if finding.note:
        summary += f"{rule.note_separator}{finding.note}"
    return summary


def _what_it_found(finding: Finding) -> str:
    if finding.rule.what_it_found is not None:
        return finding.rule.what_it_found
    noun = "problem" if finding.problems == 1 else "problems"
    return f"{finding.problems} {noun}"


def detection_summary(finding: Finding, label: str) -> str:
    where = f" at {finding.address}" if finding.address else ""
    return f"{finding.rule.name}: {label}{where}"


def rule_section(finding: Finding) -> dict[str, str]:
    rule = finding.rule
    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "ruleset": "volatility",
    }


def threat_section(finding: Finding) -> dict[str, Any]:
    rule = finding.rule
    return {"technique": {"id": [rule.technique_id], "name": rule.technique_name}}


def match_text(finding: Finding) -> str | None:
    pieces = (
        f"{label}: {value}"
        for label, value in (
            ("address", finding.address),
            ("protection", finding.protection),
            ("note", finding.note),
        )
        if value
    )
    return detection_match(pieces)
