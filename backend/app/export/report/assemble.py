"""The report model from what the views already answered: no query, no file, no clock."""

import base64
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from ipaddress import ip_address, ip_network

from pydantic import BaseModel

from app.analyses.guest_choice import recorded_guest
from app.analyses.summary import ReportSummary
from app.db.models import Analysis, Sample
from app.export.inputs import ExportAnnotations, TargetType
from app.export.report.key_events import (
    Citation,
    EventFacts,
    KeyEventCandidates,
    facts_from_detection,
    facts_from_related,
    select_key_events,
)
from app.export.report.model import (
    IocGroup,
    NetworkSection,
    NoteGroup,
    ReportArchive,
    ReportCounts,
    ReportDetection,
    ReportDetectionGroup,
    ReportHeader,
    ReportInclude,
    ReportModel,
    ReportScreenshot,
    ReportTechnique,
)
from app.export.report.process_tree_svg import layout_rows
from app.schemas.views_events import (
    FlowRow,
    Listing,
    NetworkView,
    ProcessNode,
    ProcessTree,
)
from app.schemas.views_findings import (
    AttackMatrix,
    Detection,
    DetectionsView,
    Ioc,
    IocsView,
    IocType,
)
from app.views.iocs import SANDBOX_NETWORK

FLOW_ROWS = 50
NETWORK_LIST_ROWS = 100
IOC_ROWS_PER_TYPE = 200
IOC_SAMPLE_PER_TYPE = 5
ANALYSIS_NOTE_TITLE = "Analysis"


@dataclass(frozen=True)
class ScreenshotFile:
    n: int
    media_type: str
    content: bytes


@dataclass(frozen=True)
class ReportInputs:
    """What was read for the report. The event pools hold each rung's candidates for the key
    events; `note_events` the events the analyst's event notes are about.
    """

    analysis: Analysis
    sample: Sample | None
    tree: ProcessTree
    detections: DetectionsView
    attack: AttackMatrix
    network: NetworkView
    iocs: IocsView
    annotations: ExportAnnotations
    process_events: Sequence[EventFacts]
    file_and_registry_events: Sequence[EventFacts]
    network_events: Sequence[EventFacts]
    note_events: Mapping[str, EventFacts]
    screenshots: Sequence[ScreenshotFile]
    generated_at: datetime


def build_report_model(inputs: ReportInputs, include: ReportInclude) -> ReportModel:
    analysis = inputs.analysis
    summary = (
        ReportSummary.model_validate(analysis.summary) if analysis.summary else ReportSummary()
    )
    all_detections = [d for group in inputs.detections.groups for d in group.detections]
    citations = [_citation(detection) for detection in all_detections]
    key_events = select_key_events(
        KeyEventCandidates(
            alerts=[facts_from_detection(detection) for detection in all_detections],
            process=inputs.process_events,
            file_and_registry=inputs.file_and_registry_events,
            citations=citations,
            network=inputs.network_events,
        )
    )
    return ReportModel(
        header=_header(inputs, summary),
        score=analysis.score,
        max_severity=analysis.max_severity,
        families=tuple(analysis.detected_families),
        tags=inputs.annotations.tags,
        counts=_counts(inputs, summary),
        techniques=_techniques(inputs.attack, all_detections),
        process_tree=layout_rows(
            inputs.tree.roots, _sample_pid(inputs.tree.roots, analysis, summary)
        ),
        key_events=key_events,
        detections=_detection_groups(inputs.detections, citations),
        network=_network(inputs.network),
        iocs=_ioc_groups(inputs.iocs, include),
        screenshots=_screenshots(inputs.screenshots) if include.screenshots else (),
        notes=_note_groups(inputs) if include.notes else (),
        include=include,
    )


def _header(inputs: ReportInputs, summary: ReportSummary) -> ReportHeader:
    analysis, sample = inputs.analysis, inputs.sample
    return ReportHeader(
        analysis_id=analysis.id,
        sample_name=analysis.filename,
        sample_type=summary.sample.type,
        sha256=analysis.sample_sha256,
        md5=sample.md5 if sample else None,
        sha1=sample.sha1 if sample else None,
        archive=_archive(analysis, summary),
        status=analysis.status,
        route=analysis.options.get("route"),
        guest=recorded_guest(analysis.options),
        submitted_at=analysis.submitted_at,
        started_at=analysis.started_at,
        finished_at=analysis.finished_at,
        duration_s=summary.duration_s,
        generated_at=inputs.generated_at,
    )


def _archive(analysis: Analysis, summary: ReportSummary) -> ReportArchive | None:
    entry = analysis.options.get("archive_entry")
    if not isinstance(entry, str):
        return None
    return ReportArchive(entry_name=entry, entry_sha256=summary.sample.entry_sha256)


def _counts(inputs: ReportInputs, summary: ReportSummary) -> ReportCounts:
    return ReportCounts(
        events=inputs.analysis.event_count,
        processes=inputs.tree.total,
        detections=inputs.detections.total,
        files_written=summary.files_written,
        registry_keys_written=summary.registry_keys_written,
        dns_queries=summary.network.dns,
        hosts=summary.network.hosts,
        tcp_flows=summary.network.tcp,
    )


def _techniques(
    attack: AttackMatrix, detections: Iterable[Detection]
) -> tuple[ReportTechnique, ...]:
    names = {detection.id: detection.name for detection in detections}
    return tuple(
        ReportTechnique(
            id=hit.id,
            name=hit.name,
            tactic=tactic.name,
            severity=hit.severity,
            hit_count=hit.hit_count,
            signatures=tuple(names[i] for i in hit.detection_ids if i in names),
        )
        for tactic in attack.tactics
        for hit in tactic.techniques
    )


def _sample_pid(
    roots: Sequence[ProcessNode], analysis: Analysis, summary: ReportSummary
) -> int | None:
    names = {name.casefold() for name in (analysis.filename, summary.sample.name) if name}
    return next(
        (process.pid for process in _walk(roots) if (process.name or "").casefold() in names), None
    )


def _walk(nodes: Sequence[ProcessNode]) -> Iterable[ProcessNode]:
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _citation(detection: Detection) -> Citation:
    return Citation(
        detection.id,
        [facts_from_related(event) for event in detection.related_events],
        detection.related_event_total,
    )


def _detection_groups(
    view: DetectionsView, citations: Sequence[Citation]
) -> tuple[ReportDetectionGroup, ...]:
    cited = {citation.detection_id: citation for citation in citations}
    return tuple(
        ReportDetectionGroup(
            ruleset=group.ruleset,
            detections=tuple(
                _report_detection(detection, cited[detection.id]) for detection in group.detections
            ),
        )
        for group in view.groups
    )


def _report_detection(detection: Detection, citation: Citation) -> ReportDetection:
    return ReportDetection(
        id=detection.id,
        name=detection.name,
        description=detection.description,
        severity=detection.severity,
        ruleset=detection.ruleset,
        techniques=tuple(detection.techniques),
        match=detection.match,
        references=tuple(detection.references),
        author=detection.author,
        time=detection.time,
        process=detection.process,
        cited_events=citation.shown,
        more_events=citation.more,
    )


def _network(view: NetworkView) -> NetworkSection:
    outside = [flow for flow in view.flows.items if not _in_sandbox_network(flow.destination_ip)]
    return NetworkSection(
        dns=_first_rows(view.dns),
        http=_first_rows(view.http),
        hosts=_first_rows(view.hosts),
        flows=Listing[FlowRow](items=outside[:FLOW_ROWS], total=len(outside)),
        simulated=view.simulated,
    )


def _first_rows[T: BaseModel](listing: Listing[T]) -> Listing[T]:
    return listing.model_copy(update={"items": listing.items[:NETWORK_LIST_ROWS]})


def _in_sandbox_network(address: str | None) -> bool:
    """Every flow touches the guest and its gateway, so a flow to the sandbox says nothing."""
    return address is not None and ip_address(address) in ip_network(SANDBOX_NETWORK)


def _ioc_groups(view: IocsView, include: ReportInclude) -> tuple[IocGroup, ...]:
    by_type: dict[IocType, list[Ioc]] = defaultdict(list)
    for ioc in view.iocs:
        by_type[ioc.type].append(ioc)
    listed = IOC_ROWS_PER_TYPE if include.raw_iocs else IOC_SAMPLE_PER_TYPE
    return tuple(
        IocGroup(
            type=type_,
            total=len(iocs),
            shown=tuple(iocs[:listed]),
            more=max(len(iocs) - listed, 0),
            truncated=type_ in view.truncated_types,
        )
        for type_, iocs in by_type.items()
    )


def _screenshots(files: Iterable[ScreenshotFile]) -> tuple[ReportScreenshot, ...]:
    return tuple(
        ReportScreenshot(
            n=file.n,
            data_uri=f"data:{file.media_type};base64,{base64.b64encode(file.content).decode()}",
        )
        for file in sorted(files, key=lambda file: file.n)
    )


def _note_groups(inputs: ReportInputs) -> tuple[NoteGroup, ...]:
    grouped: dict[tuple[TargetType, str | None], list[str]] = defaultdict(list)
    for note in inputs.annotations.notes:
        grouped[(note.target_type, note.target_ref)].append(note.body)
    names = {process.pid: process.name for process in _walk(inputs.tree.roots)}
    return tuple(
        _note_group(target, bodies, names, inputs.note_events)
        for target, bodies in sorted(
            grouped.items(), key=lambda item: _target_order(item[0], inputs.note_events)
        )
    )


def _target_order(
    target: tuple[TargetType, str | None], events: Mapping[str, EventFacts]
) -> tuple[int, float | str]:
    kind, ref = target
    if kind is TargetType.ANALYSIS:
        return (0, 0)
    if kind is TargetType.PROCESS:
        return (1, int(ref or 0))
    found = events.get(ref or "")
    return (2, found.time.timestamp() if found else 0)


def _note_group(
    target: tuple[TargetType, str | None],
    bodies: list[str],
    process_names: Mapping[int, str | None],
    events: Mapping[str, EventFacts],
) -> NoteGroup:
    kind, ref = target
    if kind is TargetType.ANALYSIS:
        return NoteGroup(
            target_type=kind, title=ANALYSIS_NOTE_TITLE, detail=None, notes=tuple(bodies)
        )
    if kind is TargetType.PROCESS:
        name = process_names.get(int(ref or 0))
        title = f"Process {name} ({ref})" if name else f"Process {ref}"
        return NoteGroup(target_type=kind, title=title, detail=None, notes=tuple(bodies))
    event = events.get(ref or "")
    title = f"Event: {event.summary}" if event else f"Event {ref}"
    return NoteGroup(
        target_type=kind, title=title, detail=ref if event else None, notes=tuple(bodies)
    )
