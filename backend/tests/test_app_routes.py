import httpx
from fastapi import FastAPI

from app.api.dependencies import get_runner


def test_the_analysis_endpoints_are_served_under_api_and_documented(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/api/analyses"]) == {"get", "post"}
    assert set(paths["/api/analyses/{analysis_id}"]) == {"get", "delete"}
    assert set(paths["/api/analyses/{analysis_id}/cancel"]) == {"post"}


async def test_the_cape_callback_is_served_outside_api_and_left_out_of_the_schema(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    nudges: list[None] = []

    class FakeRunner:
        def nudge(self) -> None:
            nudges.append(None)

    app.dependency_overrides[get_runner] = FakeRunner

    response = await client.post("/internal/cape/callback", json={"task_id": 7})

    assert response.status_code == 200
    assert nudges == [None]
    assert not any("callback" in path for path in app.openapi()["paths"])


def test_the_report_summary_reaches_the_schema_so_the_client_gets_its_types(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]

    assert {"ReportSummary", "AnalysisRead", "AnalysisPage"} <= set(schemas)
