"""Reads everything a report needs from the stores, through the views the GUI uses."""

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.read import load_annotations
from app.db.base import utc_now
from app.db.models import Analysis, Sample
from app.events.event_model import EVENT_SOURCE_FIELDS, event_from_source
from app.events.execution import run_search
from app.export.assembly import export_annotations
from app.export.inputs import ExportAnnotations, TargetType
from app.export.report.assemble import ReportInputs, ScreenshotFile, build_report_model
from app.export.report.key_events import MAX_KEY_EVENTS, EventFacts, facts_from_event
from app.export.report.model import ReportInclude, ReportModel
from app.schemas.views_events import NetworkView
from app.search.index import EventIndex
from app.views.artifacts import SCREENSHOT_MEDIA_TYPES, AnalysisFiles, read_analysis_files
from app.views.attack import attack_matrix
from app.views.attack_table import AttackTable
from app.views.detections import list_detections
from app.views.event_fields import TIME_ORDER, hits_of
from app.views.iocs import SANDBOX_NETWORK, collect_iocs
from app.views.network import INETSIM_ROUTE, MAX_LIST_LIMIT, network_view
from app.views.processes import process_tree

logger = logging.getLogger(__name__)

type ProgressCallback = Callable[[str, int], None]

# Only the first network event of each destination is listed, so the pool needs the first events
# of the run, not all of them.
NETWORK_EVENT_POOL = 2000
PROCESS_LANES = ["process"]
FILE_AND_REGISTRY_LANES = ["file", "registry"]
NETWORK_LANES = ["network"]


@dataclass(frozen=True)
class ReportSources:
    session: AsyncSession
    index: EventIndex
    storage_root: Path
    attack_table: AttackTable


def ignore_progress(step: str, percent: int) -> None:
    """The progress callback of a caller that does not report any."""


async def gather_report(
    analysis: Analysis,
    sources: ReportSources,
    include: ReportInclude,
    progress: ProgressCallback = ignore_progress,
    clock: Callable[[], datetime] = utc_now,
) -> ReportModel:
    """The report of a finished analysis, built from the same views the GUI shows.

    `progress` hears each step with a percentage that only rises and stays below 100: the render
    that follows is the caller's last step.
    """
    index, session = sources.index, sources.session
    progress("Reading the analysis files", 5)
    files = await asyncio.to_thread(
        read_analysis_files, sources.storage_root, analysis.cape_task_id
    )
    progress("Reading the process tree", 15)
    tree = await process_tree(index, analysis.id)
    progress("Reading the detections", 30)
    detections = await list_detections(index, analysis.id)
    attack = await attack_matrix(index, analysis.id, sources.attack_table)
    progress("Reading the network activity", 45)
    network = await _network(analysis, index)
    progress("Collecting the indicators", 55)
    iocs = await collect_iocs(index, analysis, files)
    progress("Selecting the key events", 65)
    pools = await _event_pools(index, analysis.id)
    progress("Reading the analyst's tags and notes", 80)
    annotations = export_annotations(await load_annotations(session, index, analysis.id))
    note_events = await _note_events(index, analysis.id, annotations, include)
    progress("Reading the screenshots", 90)
    screenshots = await _screenshots(files, include)
    progress("Assembling the report", 95)
    return build_report_model(
        ReportInputs(
            analysis=analysis,
            sample=await session.get(Sample, analysis.sample_sha256),
            tree=tree,
            detections=detections,
            attack=attack,
            network=network,
            iocs=iocs,
            annotations=annotations,
            process_events=pools.process,
            file_and_registry_events=pools.file_and_registry,
            network_events=pools.network,
            note_events=note_events,
            screenshots=screenshots,
            generated_at=clock(),
        ),
        include,
    )


async def _network(analysis: Analysis, index: EventIndex) -> NetworkView:
    simulated = analysis.options.get("route") == INETSIM_ROUTE
    return await network_view(index, analysis.id, simulated=simulated, limit=MAX_LIST_LIMIT)


@dataclass(frozen=True)
class _EventPools:
    process: list[EventFacts]
    file_and_registry: list[EventFacts]
    network: list[EventFacts]


async def _event_pools(index: EventIndex, analysis_id: int) -> _EventPools:
    inside_the_sandbox = [{"term": {"destination.ip": SANDBOX_NETWORK}}]
    return _EventPools(
        process=await _earliest_in_lanes(index, analysis_id, PROCESS_LANES, MAX_KEY_EVENTS),
        file_and_registry=await _earliest_in_lanes(
            index, analysis_id, FILE_AND_REGISTRY_LANES, MAX_KEY_EVENTS
        ),
        network=await _earliest_in_lanes(
            index, analysis_id, NETWORK_LANES, NETWORK_EVENT_POOL, must_not=inside_the_sandbox
        ),
    )


async def _earliest_in_lanes(
    index: EventIndex,
    analysis_id: int,
    lanes: list[str],
    size: int,
    must_not: Sequence[dict[str, Any]] = (),
) -> list[EventFacts]:
    body = {
        "size": size,
        "query": {
            "bool": {"filter": [{"terms": {"tartarus.lane": lanes}}], "must_not": list(must_not)}
        },
        "sort": TIME_ORDER,
        "_source": {"includes": EVENT_SOURCE_FIELDS},
    }
    response = await run_search(index, analysis_id, body)
    return [facts_from_event(event_from_source(source)) for source in hits_of(response)]


async def _note_events(
    index: EventIndex, analysis_id: int, annotations: ExportAnnotations, include: ReportInclude
) -> dict[str, EventFacts]:
    refs = sorted(
        {
            note.target_ref
            for note in annotations.notes
            if note.target_type is TargetType.EVENT and note.target_ref
        }
    )
    if not include.notes or not refs:
        return {}
    response = await run_search(
        index,
        analysis_id,
        {
            "size": len(refs),
            "query": {"ids": {"values": refs}},
            "_source": {"includes": EVENT_SOURCE_FIELDS},
        },
    )
    found = [facts_from_event(event_from_source(source)) for source in hits_of(response)]
    return {facts.id: facts for facts in found}


async def _screenshots(files: AnalysisFiles, include: ReportInclude) -> list[ScreenshotFile]:
    if not include.screenshots:
        return []
    return await asyncio.to_thread(read_screenshots, files.catalog.screenshots)


def read_screenshots(paths: Sequence[Path]) -> list[ScreenshotFile]:
    """Blocking. A file numbered as the artifact list numbers it; one that is gone is skipped."""
    read: list[ScreenshotFile] = []
    for number, path in enumerate(paths, start=1):
        try:
            content = path.read_bytes()
        except OSError:
            logger.warning("Screenshot %s is gone; the report leaves it out", path.name)
            continue
        read.append(ScreenshotFile(number, SCREENSHOT_MEDIA_TYPES[path.suffix.lower()], content))
    return read
