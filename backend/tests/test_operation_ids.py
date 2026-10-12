import re

import pytest
from fastapi import FastAPI

from app.api.operation_ids import generate_operation_id

HTTP_METHODS = {"get", "put", "post", "delete", "patch"}


def operation_ids(app: FastAPI) -> dict[tuple[str, str], str]:
    paths = app.openapi()["paths"]
    return {
        (method, path): operation["operationId"]
        for path, operations in paths.items()
        for method, operation in operations.items()
        if method in HTTP_METHODS
    }


def test_every_operation_id_is_a_tag_prefixed_snake_case_name(app: FastAPI) -> None:
    ids = operation_ids(app)

    assert ids
    for route, operation_id in ids.items():
        assert re.fullmatch(r"[a-z]+_[a-z_]+", operation_id), route


def test_operation_ids_are_unique(app: FastAPI) -> None:
    ids = list(operation_ids(app).values())

    assert len(ids) == len(set(ids))


def test_health_operation_id_is_system_health(app: FastAPI) -> None:
    assert operation_ids(app)[("get", "/api/system/health")] == "system_health"


def test_every_route_lives_under_the_api_prefix(app: FastAPI) -> None:
    paths = [path for _, path in operation_ids(app)]

    assert paths
    assert all(path.startswith("/api/") for path in paths)


def test_route_without_a_tag_cannot_get_an_operation_id() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)

    async def untagged() -> None: ...

    with pytest.raises(ValueError, match="untagged"):
        app.get("/untagged")(untagged)
