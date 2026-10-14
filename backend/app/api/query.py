from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_event_index, require_analysis
from app.db.session import get_session
from app.events.execution import run_search
from app.events.values import build_values_body, read_values, value_paths
from app.query.compiler import compile_query
from app.query.fields_api import field_catalog, suggest_fields
from app.schemas.events_api import (
    FieldRead,
    FieldValues,
    QueryErrorRead,
    QueryValidateRequest,
    QueryValidation,
    ValuesParams,
)
from app.search.index import EventIndex

router = APIRouter(tags=["query"])

MAX_FIELD_SUGGESTIONS = 50

Session = Annotated[AsyncSession, Depends(get_session)]
Events = Annotated[EventIndex, Depends(get_event_index)]


@router.post("/query/validate")
async def validate(request: QueryValidateRequest) -> QueryValidation:
    """Whether the query compiles, with each problem as a span of the text and, for an unknown
    field, the closest name. An empty query is fine."""
    errors = compile_query(request.query).errors
    return QueryValidation(
        ok=not errors, errors=[QueryErrorRead(**asdict(error)) for error in errors]
    )


@router.get("/query/fields")
async def fields(
    prefix: Annotated[str, Query(description="Typed text; empty lists the whole catalog.")] = "",
) -> list[FieldRead]:
    """The field catalog for autocomplete. With a prefix, only searchable fields whose name or
    alias starts with it, then those that contain it, at most 50."""
    catalog = suggest_fields(prefix, MAX_FIELD_SUGGESTIONS) if prefix else field_catalog()
    return [FieldRead(**asdict(entry)) for entry in catalog]


@router.get("/analyses/{analysis_id}/query/values")
async def values(
    analysis_id: int, params: Annotated[ValuesParams, Query()], session: Session, events: Events
) -> FieldValues:
    """The most common values of a keyword field that start with the prefix, as indexed
    (lowercase). The composite alias `domain` merges its two fields. `422` for a field that is
    not a keyword."""
    await require_analysis(session, analysis_id)
    body = build_values_body(value_paths(params.field), params.prefix, params.limit)
    return read_values(params.limit, await run_search(events, analysis_id, body))
