import pytest
from fastapi import FastAPI
from fastapi.websockets import WebSocketDisconnect
from starlette.testclient import TestClient

from app.live.hub import LiveHub
from app.live.manager import LiveCollectionManager
from app.ws.live import get_progress_source


class NoSuchAnalysis:
    async def read(self, analysis_id: int) -> None:
        return None


def test_the_live_socket_is_mounted_on_the_app(app: FastAPI) -> None:
    app.dependency_overrides[get_progress_source] = NoSuchAnalysis

    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/analyses/1/live") as session,
        pytest.raises(WebSocketDisconnect) as closed,
    ):
        session.receive_json()

    assert closed.value.code == 4404


async def test_the_lifespan_builds_the_hub_and_hands_the_runner_the_collection_manager(
    app: FastAPI,
) -> None:
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.live_hub, LiveHub)
        assert isinstance(app.state.live_collection, LiveCollectionManager)
        assert app.state.runner._live is app.state.live_collection


async def test_the_lifespan_stops_the_collectors_on_shutdown(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[str] = []

    async def record_close(self: LiveCollectionManager) -> None:
        closed.append("collectors")

    monkeypatch.setattr(LiveCollectionManager, "aclose", record_close)

    async with app.router.lifespan_context(app):
        assert closed == []

    assert closed == ["collectors"]


async def test_the_collection_manager_polls_at_the_configured_interval(app: FastAPI) -> None:
    async with app.router.lifespan_context(app):
        manager = app.state.live_collection

        assert manager._poll_interval_s == 0.25
