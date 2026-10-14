from typing import Any

import pytest
from opensearchpy.exceptions import ConnectionError as OpenSearchConnectionError
from opensearchpy.exceptions import ConnectionTimeout, RequestError

from app.errors import ApiError
from app.events.execution import REQUEST_TIMEOUT_S, run_search
from app.search.index import EventIndex


class FakeIndex:
    def __init__(self, response: dict[str, Any] | None = None, raises: Exception | None = None):
        self.response = response or {"hits": {"hits": []}}
        self.raises = raises
        self.calls: list[tuple[int, dict[str, Any], float | None]] = []

    async def search(
        self, analysis_id: int, body: dict[str, Any], request_timeout: float | None = None
    ) -> dict[str, Any]:
        self.calls.append((analysis_id, body, request_timeout))
        if self.raises is not None:
            raise self.raises
        return self.response


async def run(index: FakeIndex) -> dict[str, Any]:
    fake: EventIndex = index  # type: ignore[assignment]
    return await run_search(fake, 7, {"query": {"match_all": {}}})


async def test_the_response_comes_back_and_the_client_is_given_a_request_timeout() -> None:
    index = FakeIndex({"hits": {"hits": [], "total": {"value": 0}}})

    assert await run(index) == {"hits": {"hits": [], "total": {"value": 0}}}
    assert index.calls == [(7, {"query": {"match_all": {}}}, REQUEST_TIMEOUT_S)]


async def test_a_client_side_timeout_is_a_504() -> None:
    with pytest.raises(ApiError) as caught:
        await run(FakeIndex(raises=ConnectionTimeout("TIMEOUT", "took too long", Exception())))

    assert (caught.value.status_code, caught.value.code) == (504, "search_timeout")


async def test_a_search_that_timed_out_inside_opensearch_is_a_504_not_partial_results() -> None:
    with pytest.raises(ApiError) as caught:
        await run(FakeIndex({"timed_out": True, "hits": {"hits": []}}))

    assert (caught.value.status_code, caught.value.code) == (504, "search_timeout")


@pytest.mark.parametrize(
    "failure",
    [
        OpenSearchConnectionError("N/A", "connection refused to 10.1.2.3:9200", Exception()),
        RequestError(400, "search_phase_execution_exception", {"error": "secret internals"}),
    ],
)
async def test_any_other_failure_is_a_502_that_does_not_leak_the_original_error(
    failure: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("ERROR"), pytest.raises(ApiError) as caught:
        await run(FakeIndex(raises=failure))

    assert (caught.value.status_code, caught.value.code) == (502, "search_failed")
    assert "10.1.2.3" not in caught.value.message
    assert "secret" not in caught.value.message
    assert "Search on the events of analysis 7 failed" in caplog.text
