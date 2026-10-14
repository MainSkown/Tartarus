"""Running a search for an endpoint: the one place OpenSearch's failures become API errors."""

import logging
from typing import Any

from opensearchpy.exceptions import ConnectionTimeout, TransportError

from app.errors import ApiError
from app.search.index import EventIndex

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT = "10s"
REQUEST_TIMEOUT_S = 15.0


async def run_search(index: EventIndex, analysis_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """Runs the search; a slow one is a 504 and any other OpenSearch failure a 502, never the
    raw error."""
    try:
        response = await index.search(analysis_id, body, request_timeout=REQUEST_TIMEOUT_S)
    except ConnectionTimeout:
        raise _timed_out() from None
    except TransportError:
        logger.exception("Search on the events of analysis %s failed", analysis_id)
        raise ApiError(502, "search_failed", "The event store could not answer") from None
    if response.get("timed_out"):
        raise _timed_out()
    return response


def _timed_out() -> ApiError:
    return ApiError(504, "search_timeout", "The search took too long; narrow the query")
