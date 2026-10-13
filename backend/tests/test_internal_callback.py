from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI

from app.api.dependencies import get_runner
from app.api.internal import router as internal_router
from app.api.operation_ids import generate_operation_id
from app.errors import install_error_handlers

CALLBACK_PATH = "/internal/cape/callback"


@dataclass
class FakeRunner:
    nudges: int = 0

    def nudge(self) -> None:
        self.nudges += 1


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
async def callback_client(
    runner: FakeRunner, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    install_error_handlers(app)
    app.include_router(internal_router)
    app.dependency_overrides[get_runner] = lambda: runner
    async with make_client(app) as client:
        yield client


async def test_the_exact_body_cape_sends_is_accepted_and_only_nudges_the_runner(
    callback_client: httpx.AsyncClient, runner: FakeRunner
) -> None:
    response = await callback_client.post(CALLBACK_PATH, json={"task_id": 6})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert runner.nudges == 1


async def test_a_callback_for_a_task_nobody_tracks_is_still_a_200(
    callback_client: httpx.AsyncClient, runner: FakeRunner
) -> None:
    response = await callback_client.post(CALLBACK_PATH, json={"task_id": 999999})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_extra_fields_in_the_body_are_ignored(
    callback_client: httpx.AsyncClient,
) -> None:
    response = await callback_client.post(CALLBACK_PATH, json={"task_id": 6, "more": "x"})

    assert response.status_code == 200


@pytest.mark.parametrize("body", [{}, {"task_id": "six"}, []])
async def test_a_malformed_body_is_a_422_that_does_not_nudge(
    callback_client: httpx.AsyncClient, runner: FakeRunner, body: object
) -> None:
    response = await callback_client.post(CALLBACK_PATH, json=body)

    assert response.status_code == 422
    assert runner.nudges == 0


def test_the_callback_is_not_part_of_the_openapi_schema() -> None:
    app = FastAPI(generate_unique_id_function=generate_operation_id)
    app.include_router(internal_router)

    assert app.openapi()["paths"] == {}
