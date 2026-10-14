from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_event_index, get_rule_registry, require_analysis
from app.db.session import get_session
from app.rules.registry import RuleFileUnavailable, RuleRegistry, RuleState
from app.schemas.rules import RuleDetail, RuleEnabledUpdate, RuleHit, RuleRead
from app.search.index import EventIndex
from app.views.rule_hits import hits_across_analyses, hits_in_analysis

router = APIRouter(prefix="/rules", tags=["rules"])
analysis_router = APIRouter(prefix="/analyses", tags=["rules"])

Registry = Annotated[RuleRegistry, Depends(get_rule_registry)]
Index = Annotated[EventIndex, Depends(get_event_index)]


@router.get("", name="list")
async def list_all(registry: Registry, index: Index) -> list[RuleRead]:
    """Every loaded rule, valid or not, with the analyst's enabled flag and the number of Sigma
    detections it raised across all analyses. Filtering is left to the client.
    """
    return _read_all(registry.states(), await hits_across_analyses(index))


@router.post("/reload", name="reload")
async def reload(registry: Registry, index: Index) -> list[RuleRead]:
    """Re-reads the rules directory now (it is also watched) and lists the rules as `GET /rules`."""
    await registry.reload()
    return _read_all(registry.states(), await hits_across_analyses(index))


@router.get("/{rule_id}", name="read")
async def read(rule_id: str, registry: Registry, index: Index) -> RuleDetail:
    """One rule with the text of its file. `404` for an unknown rule, or one whose file is gone
    or lies outside the rules directory.
    """
    state = _require_state(registry, rule_id)
    try:
        yaml_text = await registry.rule_yaml(rule_id)
    except RuleFileUnavailable:
        raise HTTPException(404, f"The file of rule {rule_id} is not available") from None
    rule = _read(state, await hits_across_analyses(index))
    return RuleDetail(**rule.model_dump(), yaml=yaml_text)


@router.patch("/{rule_id}", name="update")
async def update(
    rule_id: str, body: RuleEnabledUpdate, registry: Registry, index: Index
) -> RuleRead:
    """Enables or disables a rule; the choice survives reloads and restarts."""
    if not await registry.set_enabled(rule_id, body.enabled):
        raise HTTPException(404, f"Rule {rule_id} not found")
    return _read(_require_state(registry, rule_id), await hits_across_analyses(index))


@analysis_router.get("/{analysis_id}/rules/hits", name="hits")
async def hits(
    analysis_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    registry: Registry,
    index: Index,
) -> list[RuleHit]:
    """Sigma detections per rule in one analysis, most hit first. A rule with no hit is left out."""
    await require_analysis(session, analysis_id)
    counts = await hits_in_analysis(index, analysis_id)
    known_ids = {state.rule.id.lower(): state.rule.id for state in registry.states()}
    found = [RuleHit(rule_id=known_ids.get(key, key), count=count) for key, count in counts.items()]
    return sorted(found, key=lambda hit: (-hit.count, hit.rule_id))


def _require_state(registry: RuleRegistry, rule_id: str) -> RuleState:
    state = registry.state_of(rule_id)
    if state is None:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return state


def _read_all(states: list[RuleState], hit_counts: Mapping[str, int]) -> list[RuleRead]:
    return [_read(state, hit_counts) for state in states]


def _read(state: RuleState, hit_counts: Mapping[str, int]) -> RuleRead:
    rule = state.rule
    return RuleRead(
        id=rule.id,
        title=rule.title,
        description=rule.description,
        level=rule.level,
        status=rule.status,
        tags=list(rule.tags),
        logsource_category=rule.logsource_category,
        validity=rule.validity,
        error=rule.error,
        enabled=state.enabled,
        path=str(rule.path),
        # The index stores rule ids lower-cased; the file may not.
        hits=hit_counts.get(rule.id.lower(), 0),
    )
