from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_event_index
from app.errors import ApiError
from app.schemas.views_findings import AnalysisHitRead, IocType
from app.search.index import EventIndex
from app.views.ioc_pivot import UnpivotableIocError, analyses_containing

router = APIRouter(prefix="/iocs", tags=["iocs"])

Events = Annotated[EventIndex, Depends(get_event_index)]


@router.get("/{kind}/{value:path}/analyses")
async def analyses(kind: IocType, value: str, events: Events) -> list[AnalysisHitRead]:
    """The analyses whose events hold this indicator, most matching events first, with how many
    each holds. The value may contain slashes, encoded or not. Only domains, IPs, URLs, registry
    paths, file paths and hashes are in events; a `mutex` is `422`.
    """
    try:
        hits = await analyses_containing(events, kind, value)
    except UnpivotableIocError as error:
        raise ApiError(422, "unpivotable_ioc", str(error)) from error
    return [AnalysisHitRead(analysis_id=hit.analysis_id, count=hit.count) for hit in hits]
