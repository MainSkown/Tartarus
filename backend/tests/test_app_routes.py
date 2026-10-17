import httpx
from fastapi import FastAPI

from app.api.dependencies import get_guest_control, get_runner
from app.guest.errors import GuestControlUnreachable


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


def test_the_guest_endpoints_are_served_under_api_and_documented(app: FastAPI) -> None:
    paths = app.openapi()["paths"]

    assert set(paths["/api/guests"]) == {"get"}
    assert set(paths["/api/guests/{name}"]) == {"get", "delete"}
    assert set(paths["/api/guests/{name}/check"]) == {"post"}
    assert {"/api/guests/media", "/api/guests/profiles"} <= set(paths)


def test_the_guest_build_endpoints_are_served_under_api_and_answer_202_to_a_start(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]

    starts = ["/api/guests/build", "/api/guests/{name}/clone"]
    starts += [
        f"/api/guests/builds/{{build_id}}/{action}"
        for action in ("resume", "restart", "continue", "cancel")
    ]
    for path in starts:
        assert set(paths[path]) == {"post"}
        assert "202" in paths[path]["post"]["responses"]
    assert set(paths["/api/guests/builds/active"]) == {"get"}
    assert set(paths["/api/guests/builds/{build_id}"]) == {"get"}


async def test_a_guest_control_failure_is_answered_by_the_real_app_as_a_502(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    class Unreachable:
        async def guests(self) -> list[object]:
            raise GuestControlUnreachable("guests", "ConnectError")

    app.dependency_overrides[get_guest_control] = Unreachable

    response = await client.get("/api/guests")

    assert response.status_code == 502
    assert response.json()["error"]["message"] == "The guest control service is not reachable"
