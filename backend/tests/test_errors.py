from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field


class ItemIn(BaseModel):
    name: str
    quantity: int = Field(ge=1)


@pytest.fixture
def error_app(app: FastAPI) -> FastAPI:
    @app.post("/api/test/items/{item_id}", tags=["test"])
    async def create_item(item_id: int, item: ItemIn) -> ItemIn:
        return item

    @app.get("/api/test/boom", tags=["test"])
    async def boom() -> None:
        raise RuntimeError("secret internals: password=hunter2")

    return app


@pytest.fixture
async def error_client(
    error_app: FastAPI, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> httpx.AsyncClient:
    return make_client(error_app)


async def test_unknown_route_uses_the_error_envelope(error_client: httpx.AsyncClient) -> None:
    response = await error_client.get("/api/nope")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "details": {}}
    }


async def test_wrong_method_keeps_its_status_and_headers(error_client: httpx.AsyncClient) -> None:
    response = await error_client.get("/api/test/items/1")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"
    assert "POST" in response.headers["allow"]


async def test_validation_failure_lists_field_errors_with_locations(
    error_client: httpx.AsyncClient,
) -> None:
    response = await error_client.post(
        "/api/test/items/not-a-number", json={"name": "x", "quantity": 0}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Request validation failed"
    fields = {tuple(field["location"]): field for field in error["details"]["fields"]}
    assert set(fields) == {("path", "item_id"), ("body", "quantity")}
    assert fields[("body", "quantity")]["type"] == "greater_than_equal"
    assert "greater than or equal to 1" in fields[("body", "quantity")]["message"]


async def test_unhandled_exception_returns_a_generic_500(
    error_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("ERROR"):
        response = await error_client.get("/api/test/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error", "details": {}}
    }
    assert "hunter2" not in response.text


async def test_unhandled_exception_is_logged_with_its_traceback(
    error_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("ERROR"):
        await error_client.get("/api/test/boom")

    record = next(record for record in caplog.records if record.exc_info)
    assert record.exc_info is not None
    assert "hunter2" in str(record.exc_info[1])


async def test_openapi_documents_the_error_envelope(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()

    health = schema["paths"]["/api/system/health"]["get"]
    assert health["responses"]["default"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorEnvelope"
    }
