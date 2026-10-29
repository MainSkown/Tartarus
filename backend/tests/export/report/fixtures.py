"""A small finished analysis as the report builder receives it: every view filled in."""

import io
from datetime import UTC, datetime, timedelta
from typing import Any

from PIL import Image

from app.db.models import Analysis, Sample
from app.db.models.analysis import AnalysisPhase, AnalysisStatus, Severity
from app.export.inputs import ExportAnnotations, ExportNote, TargetType
from app.export.report.assemble import ReportInputs, ScreenshotFile
from app.export.report.key_events import EventFacts
from app.schemas.views_events import (
    DnsRow,
    FlowRow,
    HostRow,
    HttpRow,
    Listing,
    NetworkView,
    ProcessNode,
    ProcessRef,
    ProcessTree,
)
from app.schemas.views_findings import (
    AttackMatrix,
    AttackTactic,
    AttackTechniqueHit,
    Detection,
    DetectionGroup,
    DetectionsView,
    IocsView,
    IocType,
    RelatedEvent,
)
from tests.export.conftest import EVERY_TYPE, SAMPLE_MD5, SAMPLE_SHA1, SAMPLE_SHA256

START = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
SAMPLE_NAME = "invoice.exe"


def picture(image_format: str, colour: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 40), colour).save(buffer, image_format)
    return buffer.getvalue()


PNG_BYTES = picture("PNG", "#3987e5")
JPEG_BYTES = picture("JPEG", "#d55181")
SUMMARY: dict[str, Any] = {
    "duration_s": 183,
    "process_count": 3,
    "signatures": [],
    "techniques": [],
    "network": {"dns": 1, "hosts": 2, "tcp": 3},
    "files_written": 4,
    "registry_keys_written": 5,
    "sample": {"name": SAMPLE_NAME, "type": "PE32 executable (GUI) Intel 80386"},
    "lane_counts": {},
}


def at(seconds: int) -> datetime:
    return START + timedelta(seconds=seconds)


def make_analysis(**changes: Any) -> Analysis:
    fields: dict[str, Any] = {
        "id": 7,
        "sample_sha256": SAMPLE_SHA256,
        "filename": SAMPLE_NAME,
        "cape_task_id": 3,
        "status": AnalysisStatus.DONE,
        "phase": AnalysisPhase.FINAL,
        "options": {"route": "inetsim", "package": "auto", "timeout": 180, "guest": "lab1"},
        "score": 7.5,
        "max_severity": Severity.HIGH,
        "detected_families": ["emotet"],
        "event_count": 13178,
        "disk_bytes": 0,
        "error": None,
        "submitted_at": START,
        "started_at": at(2),
        "finished_at": at(185),
        "summary": SUMMARY,
    }
    return Analysis(**{**fields, **changes})


ARCHIVE_NAME = "invoice.zip"
ARCHIVE_ENTRY = "bin/invoice.exe"
ARCHIVE_PASSWORD = "Tartarus-Canary-7f3a"  # noqa: S105 -- a distinctive marker, not a credential
ENTRY_SHA256 = "e" * 64


def make_archive_analysis(entry_sha256: str | None = ENTRY_SHA256, **changes: Any) -> Analysis:
    summary = {**SUMMARY, "sample": {**SUMMARY["sample"], "entry_sha256": entry_sha256}}
    options = {
        "route": "inetsim",
        "package": "zip",
        "archive_entry": ARCHIVE_ENTRY,
        "archive_password": ARCHIVE_PASSWORD,
    }
    return make_analysis(
        filename=ARCHIVE_NAME,
        options=options,
        summary=summary,
        **changes,
    )


def make_sample() -> Sample:
    return Sample(
        sha256=SAMPLE_SHA256,
        sha1=SAMPLE_SHA1,
        md5=SAMPLE_MD5,
        size=2048,
        file_type="PE32",
        original_name=SAMPLE_NAME,
        stored_path="/data/samples/x.zip",
    )


def process(pid: int, name: str, children: list[ProcessNode] | None = None, **changes: Any):
    fields: dict[str, Any] = {
        "entity_id": f"7:{pid}",
        "pid": pid,
        "ppid": None,
        "name": name,
        "executable": None,
        "command_line": None,
        "start": at(pid),
        "end": None,
        "integrity": None,
        "max_severity": None,
        "detection_count": 0,
        "injected_into": [],
        "network_hosts": [],
        "event_counts_by_lane": {},
        "children": children or [],
    }
    return ProcessNode(**{**fields, **changes})


def make_tree() -> ProcessTree:
    roots = [
        process(
            100,
            "explorer.exe",
            [
                process(
                    4242,
                    SAMPLE_NAME,
                    [process(4300, "cmd.exe", injected_into=[], detection_count=1)],
                    max_severity=Severity.HIGH,
                    detection_count=2,
                    injected_into=[4300],
                )
            ],
        ),
        process(200, "svchost.exe"),
    ]
    return ProcessTree(roots=roots, total=4)


def related(event_id: str, second: int, lane: str = "api") -> RelatedEvent:
    return RelatedEvent(
        id=event_id,
        time=at(second),
        lane=lane,
        action="NtCreateFile",
        summary=f"summary of {event_id}",
        process=ProcessRef(pid=4242, name=SAMPLE_NAME),
    )


def detection(detection_id: str, name: str, severity: Severity, ruleset: str, **changes: Any):
    fields: dict[str, Any] = {
        "id": detection_id,
        "name": name,
        "description": f"{name} description",
        "severity": severity,
        "ruleset": ruleset,
        "techniques": [],
        "match": None,
        "references": [],
        "author": None,
        "time": at(30),
        "process": ProcessRef(pid=4242, name=SAMPLE_NAME),
        "related_events": [],
        "related_event_total": 0,
    }
    return Detection(**{**fields, **changes})


def make_detections() -> DetectionsView:
    run_key = detection(
        "det-1",
        "Run key written",
        Severity.HIGH,
        "sigma",
        author="Florian Roth",
        techniques=["T1547.001"],
        match="registry.path: *\\Run\\*",
        related_events=[related(f"cited-{n}", 20 + n, "registry") for n in range(8)],
        related_event_total=8,
    )
    recon = detection(
        "det-2",
        "recon_systeminfo",
        Severity.MEDIUM,
        "cape",
        techniques=["T1059"],
        related_events=[related("cited-x", 41)],
        related_event_total=1,
    )
    return DetectionsView(
        groups=[
            DetectionGroup(ruleset="sigma", detections=[run_key]),
            DetectionGroup(ruleset="cape", detections=[recon]),
        ],
        total=2,
    )


def make_attack() -> AttackMatrix:
    return AttackMatrix(
        tactics=[
            AttackTactic(
                id="TA0003",
                name="Persistence",
                techniques=[
                    AttackTechniqueHit(
                        id="T1547.001",
                        name="Registry Run Keys / Startup Folder",
                        hit_count=1,
                        severity=Severity.HIGH,
                        detection_ids=["det-1"],
                    )
                ],
            ),
            AttackTactic(
                id="TA0002",
                name="Execution",
                techniques=[
                    AttackTechniqueHit(
                        id="T1059",
                        name="Command and Scripting Interpreter",
                        hit_count=1,
                        severity=Severity.MEDIUM,
                        detection_ids=["det-2"],
                    ),
                    AttackTechniqueHit(
                        id="T9999",
                        name=None,
                        hit_count=1,
                        severity=Severity.LOW,
                        detection_ids=["det-gone"],
                    ),
                ],
            ),
        ],
        attack_version="16.1",
    )


def flow_row(n: int, destination_ip: str) -> FlowRow:
    return FlowRow(
        event_id=f"flow-{n}",
        time=at(12 + n),
        transport="tcp",
        source_ip="192.168.150.10",
        source_port=50000 + n,
        destination_ip=destination_ip,
        destination_port=443,
        process=ProcessRef(pid=4242, name=SAMPLE_NAME),
    )


def make_network(flows: int = 3, sandbox_flows: int = 0, dns: int = 1) -> NetworkView:
    """`sandbox_flows` more flows, listed first, go to the sandbox gateway like most of a run's."""
    dropper = ProcessRef(pid=4242, name=SAMPLE_NAME)
    return NetworkView(
        dns=Listing(
            items=[
                DnsRow(
                    event_id=f"dns-{n}",
                    time=at(10 + n),
                    query="evil.example" if n == 0 else f"host{n}.example",
                    type="A",
                    answers=["203.0.113.7"],
                    process=dropper,
                )
                for n in range(dns)
            ],
            total=dns,
        ),
        http=Listing(
            items=[
                HttpRow(
                    event_id="http-1",
                    time=at(11),
                    method="GET",
                    url="http://evil.example/a.php?x=1",
                    host="evil.example",
                    status=200,
                    user_agent="Mozilla/5.0",
                    process=dropper,
                )
            ],
            total=1,
        ),
        tls=Listing(items=[], total=0),
        flows=Listing(
            items=[
                *[flow_row(n, "192.168.150.1") for n in range(sandbox_flows)],
                *[flow_row(sandbox_flows + n, "203.0.113.7") for n in range(flows)],
            ],
            total=sandbox_flows + flows,
        ),
        alerts=Listing(items=[], total=0),
        hosts=Listing(
            items=[HostRow(host="203.0.113.7", kind="ip", count=4, related=["evil.example"])],
            total=1,
        ),
        simulated=True,
    )


def make_iocs() -> IocsView:
    return IocsView(iocs=list(EVERY_TYPE), truncated_types=[IocType.FILE])


def facts(
    event_id: str, second: int, lane: str, summary: str | None = None, **changes: Any
) -> EventFacts:
    fields: dict[str, Any] = {
        "id": event_id,
        "time": at(second),
        "sequence": second,
        "lane": lane,
        "action": "act",
        "summary": summary or f"summary of {event_id}",
        "severity": None,
        "process_name": SAMPLE_NAME,
        "pid": 4242,
    }
    return EventFacts(**{**fields, **changes})


NOTES = (
    ExportNote("Looks like an Emotet dropper.", TargetType.ANALYSIS, None),
    ExportNote("Spawns the DNS lookups.", TargetType.PROCESS, "4242"),
    ExportNote("The beacon, check the URI.", TargetType.EVENT, "ev-dns"),
    ExportNote("Second note on the dropper.", TargetType.PROCESS, "4242"),
)


def make_inputs(**changes: Any) -> ReportInputs:
    fields: dict[str, Any] = {
        "analysis": make_analysis(),
        "sample": make_sample(),
        "tree": make_tree(),
        "detections": make_detections(),
        "attack": make_attack(),
        "network": make_network(),
        "iocs": make_iocs(),
        "annotations": ExportAnnotations(tags=("phishing", "tlp:amber"), notes=NOTES),
        "process_events": [facts("proc-1", 3, "process", "started cmd.exe")],
        "file_and_registry_events": [facts("file-1", 5, "file", "created stage2.dll")],
        "network_events": [facts("net-1", 12, "network", "connect", destination="203.0.113.7")],
        "note_events": {"ev-dns": facts("ev-dns", 10, "network", "dns lookup evil.example")},
        "screenshots": [
            ScreenshotFile(1, "image/png", PNG_BYTES),
            ScreenshotFile(2, "image/jpeg", JPEG_BYTES),
        ],
        "generated_at": at(3600),
    }
    return ReportInputs(**{**fields, **changes})
