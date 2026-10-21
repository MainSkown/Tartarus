"""Running a search for an endpoint: the one place OpenSearch's failures become API errors."""

import logging
from collections.abc import Awaitable
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
    return await _guarded(
        index.search(analysis_id, body, request_timeout=REQUEST_TIMEOUT_S),
        f"the events of analysis {analysis_id}",
    )


async def run_search_all(index: EventIndex, body: dict[str, Any]) -> dict[str, Any]:
    """`run_search` over the events of every analysis."""
    return await _guarded(
        index.search_all(body, request_timeout=REQUEST_TIMEOUT_S), "the events of all analyses"
    )


async def _guarded(search: Awaitable[dict[str, Any]], target: str) -> dict[str, Any]:
    try:
        response = await search
    except ConnectionTimeout:
        raise _timed_out() from None
    except TransportError:
        logger.exception("Search on %s failed", target)
        raise ApiError(502, "search_failed", "The event store could not answer") from None
    if response.get("timed_out"):
        raise _timed_out()
    return response


def _timed_out() -> ApiError:
    return ApiError(504, "search_timeout", "The search took too long; narrow the query")
