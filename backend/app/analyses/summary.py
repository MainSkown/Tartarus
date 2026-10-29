from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.analyses.defender import DefenderVerdict
from app.analyses.memory import MemorySummary
from app.analyses.missing_exports import MissingExport, export_warnings, read_missing_exports
from app.analyses.ports import ReportOutcome, ReportUnreadableError
from app.db.models.analysis import Severity
from app.ingest.clock import analysis_dir_of
from app.ingest.json_file import JsonFileTooLargeError, load_json_file

MAX_REPORT_BYTES = 1024**3
CRITICAL_FROM_CAPE_SEVERITY = 4
CAPE_SEVERITY_SCALE = (Severity.INFO, Severity.LOW, Severity.MEDIUM, Severity.HIGH)
SEVERITY_ORDER = list(Severity)


class SignatureSummary(BaseModel):
    name: str
    severity: Severity
    description: str


class AttackTechnique(BaseModel):
    """CAPE gives technique ids without names; the signatures that raised one say what it means."""

    id: str
    signatures: list[str]


class NetworkCounts(BaseModel):
    dns: int = 0
    hosts: int = 0
    tcp: int = 0


class SampleSummary(BaseModel):
    name: str | None = None
    type: str | None = None
    entry_sha256: str | None = None


class ReportSummary(BaseModel):
    """What the Dashboard and the analysis summary tab show; stored as `analysis.summary`."""

    duration_s: int | None = None
    process_count: int = 0
    signatures: list[SignatureSummary] = []
    techniques: list[AttackTechnique] = []
    network: NetworkCounts = NetworkCounts()
    files_written: int = 0
    registry_keys_written: int = 0
    sample: SampleSummary = SampleSummary()
    lane_counts: dict[str, int] = {}
    defender: DefenderVerdict | None = None
    hidden_events: dict[str, int] = {}
    missing_exports: list[MissingExport] = []
    memory: MemorySummary | None = None
    warnings: list[str] = []


def read_report(path: Path) -> ReportOutcome:
    report = load_report(path)
    signatures = _signatures(report)
    return ReportOutcome(
        score=_number(report.get("malscore")),
        max_severity=max(
            (item.severity for item in signatures), key=SEVERITY_ORDER.index, default=None
        ),
        detected_families=_families(report.get("detections")),
        summary=_summarise(report, signatures, analysis_dir_of(path)).model_dump(mode="json"),
    )


def load_report(path: Path) -> dict[str, Any]:
    try:
        report = load_json_file(path, MAX_REPORT_BYTES)
    except FileNotFoundError:
        raise ReportUnreadableError(f"report is missing: {path.name}") from None
    except JsonFileTooLargeError:
        raise ReportUnreadableError(f"report {path.name} is too large to ingest") from None
    except (OSError, ValueError) as error:
        reason = "not valid JSON" if isinstance(error, ValueError) else type(error).__name__
        raise ReportUnreadableError(f"report {path.name} is {reason}") from None
    if not isinstance(report, dict) or not isinstance(report.get("info"), dict):
        raise ReportUnreadableError(f"report {path.name} is not a CAPE report: no `info` section")
    return report


def _summarise(
    report: dict[str, Any], signatures: list[SignatureSummary], analysis_dir: Path
) -> ReportSummary:
    behavior = _section(report, "behavior")
    behavior_summary = _section(behavior, "summary")
    target_file = _section(_section(report, "target"), "file")
    network = _section(report, "network")
    missing_exports = read_missing_exports(analysis_dir)
    return ReportSummary(
        duration_s=_integer(report["info"].get("duration")),
        process_count=process_count_of(report),
        signatures=signatures,
        techniques=_techniques(report.get("ttps")),
        network=NetworkCounts(
            dns=_length(network.get("dns")),
            hosts=_length(network.get("hosts")),
            tcp=_length(network.get("tcp")),
        ),
        files_written=_length(behavior_summary.get("write_files")),
        registry_keys_written=_length(behavior_summary.get("write_keys")),
        sample=SampleSummary(
            name=_text(target_file.get("name")), type=_text(target_file.get("type"))
        ),
        missing_exports=missing_exports,
        warnings=export_warnings(missing_exports),
    )


def process_count_of(report: dict[str, Any]) -> int:
    return _length(_section(report, "behavior").get("processes"))


def _signatures(report: dict[str, Any]) -> list[SignatureSummary]:
    raw = report.get("signatures")
    parsed = [
        SignatureSummary(
            name=str(item.get("name", "")),
            severity=severity_from_cape(item.get("severity")),
            description=str(item.get("description", "")),
        )
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict)
    ]
    return sorted(parsed, key=lambda item: SEVERITY_ORDER.index(item.severity), reverse=True)


def severity_from_cape(cape_severity: object) -> Severity:
    level = _integer(cape_severity) or 0
    if level >= CRITICAL_FROM_CAPE_SEVERITY:
        return Severity.CRITICAL
    return CAPE_SEVERITY_SCALE[max(level, 0)]


def _techniques(ttps: object) -> list[AttackTechnique]:
    signatures_by_id: dict[str, list[str]] = {}
    for entry in ttps if isinstance(ttps, list) else []:
        if not isinstance(entry, dict):
            continue
        for technique_id in entry.get("ttps") or []:
            raised_by = signatures_by_id.setdefault(str(technique_id), [])
            if entry.get("signature"):
                raised_by.append(str(entry["signature"]))
    return [AttackTechnique(id=key, signatures=names) for key, names in signatures_by_id.items()]


def _families(detections: object) -> list[str]:
    if not isinstance(detections, list):
        return []
    return [family for family in detections if isinstance(family, str) and family]


def _section(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    return value if isinstance(value, dict) else {}


def _length(value: object) -> int:
    return len(value) if isinstance(value, list | dict) else 0


def _integer(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
