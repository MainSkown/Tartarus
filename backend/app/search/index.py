import asyncio
from collections.abc import Iterable, Iterator
from itertools import islice
from typing import Any

from opensearchpy import AsyncOpenSearch, NotFoundError, RequestError
from opensearchpy.helpers import BulkIndexError, async_bulk

from app.search.template import INDEX_PREFIX, TEMPLATE_NAME, build_index_template

REPORTED_FAILURES = 3
INDEX_EXISTS = "resource_already_exists_exception"


class IndexingError(Exception):
    """Raised when OpenSearch rejects events during a bulk index."""


def index_name(analysis_id: int) -> str:
    return f"{INDEX_PREFIX}{analysis_id}"


def analysis_id_of_index(name: str) -> int:
    """The inverse of `index_name`; a hit's `_index` says which analysis it belongs to."""
    suffix = name.removeprefix(INDEX_PREFIX)
    if suffix == name or not suffix.isascii() or not suffix.isdigit():
        raise ValueError(f"{name!r} is not an event index")
    return int(suffix)


def _event_id(event: dict[str, Any]) -> str:
    try:
        return str(event["event"]["id"])
    except (KeyError, TypeError):
        raise IndexingError("event has no event.id") from None


def _describe_failures(failures: list[dict[str, Any]]) -> str:
    shown = []
    for failure in failures[:REPORTED_FAILURES]:
        detail = failure.get("index", failure)
        shown.append(f"{detail.get('_id')}: {detail.get('error')}")
    more = len(failures) - len(shown)
    suffix = f" (and {more} more)" if more > 0 else ""
    return f"{len(failures)} events rejected: {'; '.join(shown)}{suffix}"


def _take(events: Iterator[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    return list(islice(events, count))


class EventIndex:
    def __init__(self, client: AsyncOpenSearch) -> None:
        self._client = client

    async def ensure_template(self) -> None:
        await self._client.indices.put_index_template(
            name=TEMPLATE_NAME, body=build_index_template()
        )

    async def create(self, analysis_id: int) -> None:
        await self._client.indices.create(index=index_name(analysis_id))

    async def ensure_index(self, analysis_id: int) -> None:
        """Creates the analysis's index unless it exists already."""
        try:
            await self.create(analysis_id)
        except RequestError as error:
            if error.error != INDEX_EXISTS:
                raise

    async def drop(self, analysis_id: int) -> None:
        await self._client.indices.delete(index=index_name(analysis_id), ignore_unavailable=True)

    async def set_refresh_interval(self, analysis_id: int, interval: str) -> None:
        await self._client.indices.put_settings(
            index=index_name(analysis_id), body={"index": {"refresh_interval": interval}}
        )

    async def refresh(self, analysis_id: int) -> None:
        await self._client.indices.refresh(index=index_name(analysis_id))

    async def search(
        self, analysis_id: int, body: dict[str, Any], request_timeout: float | None = None
    ) -> dict[str, Any]:
        """Runs a search on one analysis's index; an analysis with no index has no events."""
        try:
            response: dict[str, Any] = await self._client.search(
                index=index_name(analysis_id), body=body, request_timeout=request_timeout
            )
        except NotFoundError:
            return {"hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}
        return response

    async def search_all(
        self, body: dict[str, Any], request_timeout: float | None = None
    ) -> dict[str, Any]:
        """Runs a search over the indices of every analysis; no analysis yet is no events."""
        response: dict[str, Any] = await self._client.search(
            index=f"{INDEX_PREFIX}*",
            body=body,
            ignore_unavailable=True,
            request_timeout=request_timeout,
        )
        return response

    async def bulk_index(
        self, analysis_id: int, events: Iterable[dict[str, Any]], chunk_size: int = 1000
    ) -> int:
        """Index events in chunks, returning how many were stored.

        The iterable is advanced on a worker thread so a normaliser generating events does not
        block the event loop, and only one chunk is held in memory at a time.
        """
        pending = iter(events)
        indexed = 0
        while chunk := await asyncio.to_thread(_take, pending, chunk_size):
            indexed += await self._index_chunk(analysis_id, chunk)
        return indexed

    async def _index_chunk(self, analysis_id: int, chunk: list[dict[str, Any]]) -> int:
        index = index_name(analysis_id)
        actions = [{"_index": index, "_id": _event_id(event), "_source": event} for event in chunk]
        try:
            stored, _ = await async_bulk(self._client, actions, chunk_size=len(actions))
        except BulkIndexError as error:
            raise IndexingError(_describe_failures(list(error.errors))) from error
        return int(stored)
