from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.read import mark_process_tree, mark_processes
from app.api.dependencies import get_event_index, require_analysis
from app.db.annotation_repository import process_marks
from app.db.session import get_session
from app.schemas.views_events import NetworkView, ProcessDetail, ProcessTree, RegistryView
from app.search.index import EventIndex
from app.views.network import DEFAULT_LIST_LIMIT, INETSIM_ROUTE, MAX_LIST_LIMIT, network_view
from app.views.processes import process_detail, process_tree
from app.views.registry import registry_view

router = APIRouter(prefix="/analyses", tags=["views"])

Session = Annotated[AsyncSession, Depends(get_session)]
Events = Annotated[EventIndex, Depends(get_event_index)]


@router.get("/{analysis_id}/processes")
async def processes(analysis_id: int, session: Session, events: Events) -> ProcessTree:
    """The process tree as nested roots. A process whose parent is not in the analysis is a root.

    Each node carries its lifetime, detections, injection targets, network hosts and event counts
    per lane, and the analyst's `tags` and `note_count`. `integrity` is null: no source reports
    it yet.
    """
    await require_analysis(session, analysis_id)
    tree = await process_tree(events, analysis_id)
    await mark_process_tree(session, analysis_id, tree.roots)
    return tree


@router.get("/{analysis_id}/processes/{pid}")
async def process(analysis_id: int, pid: int, session: Session, events: Events) -> ProcessDetail:
    """One process (the first, if the pid was reused) with its loaded modules, its 15 most called
    APIs, and its 200 most recent file, registry, network and process events (newest first) with
    the total, and the analyst's `tags` and `note_count`. `404` for a pid the analysis never saw.
    """
    await require_analysis(session, analysis_id)
    found = await process_detail(events, analysis_id, pid)
    if found is None:
        raise HTTPException(404, f"Process {pid} not found in analysis {analysis_id}")
    mark_processes([found], await process_marks(session, analysis_id))
    return found


@router.get("/{analysis_id}/network")
async def network(
    analysis_id: int,
    session: Session,
    events: Events,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIST_LIMIT, description="Rows kept in each list.")
    ] = DEFAULT_LIST_LIMIT,
) -> NetworkView:
    """DNS, HTTP, TLS, flows, alerts and contacted hosts, each as `{items, total}`.

    Each list holds its first `limit` rows by time; `total` counts them all. A row names its
    process only where the report attributed it exactly. `tls` and `alerts` stay empty until
    Suricata is a source. `simulated` is true when the analysis was routed through INetSim.
    """
    analysis = await require_analysis(session, analysis_id)
    simulated = analysis.options.get("route") == INETSIM_ROUTE
    return await network_view(events, analysis_id, simulated=simulated, limit=limit)


@router.get("/{analysis_id}/registry")
async def registry(analysis_id: int, session: Session, events: Events) -> RegistryView:
    """Registry changes grouped by hive and key, groups ordered by their first change."""
    await require_analysis(session, analysis_id)
    return await registry_view(events, analysis_id)
