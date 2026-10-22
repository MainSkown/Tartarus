import httpx
import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.browser_guard import BrowserOriginGuard, SecurityHeaders
from app.config import Settings

ALLOWED = ("localhost", "127.0.0.1", "[::1]", "backend")


@pytest.fixture
def guarded_app() -> FastAPI:
    app = FastAPI()

    @app.get("/thing")
    async def read_thing() -> dict[str, str]:
        return {"ok": "yes"}

    @app.post("/thing")
    async def write_thing() -> dict[str, str]:
        return {"ok": "yes"}

    @app.websocket("/ws")
    async def socket(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    app.add_middleware(BrowserOriginGuard, allowed_hosts=lambda: frozenset(ALLOWED))
    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8080"
    )


@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:8080", "127.0.0.1:8080", "[::1]:8080", "backend:8000", "LOCALHOST"],
)
async def test_an_allowed_host_is_served(guarded_app: FastAPI, host: str) -> None:
    async with client_for(guarded_app) as client:
        response = await client.get("/thing", headers={"Host": host})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host", ["evil.example", "evil.example:8080", "localhost.evil.example", ""]
)
async def test_a_foreign_host_is_misdirected(guarded_app: FastAPI, host: str) -> None:
    async with client_for(guarded_app) as client:
        response = await client.get("/thing", headers={"Host": host})

    assert response.status_code == 421


async def test_a_post_without_an_origin_is_served(guarded_app: FastAPI) -> None:
    async with client_for(guarded_app) as client:
        response = await client.post("/thing")

    assert response.status_code == 200


async def test_a_post_from_an_allowed_origin_is_served(guarded_app: FastAPI) -> None:
    async with client_for(guarded_app) as client:
        response = await client.post("/thing", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "origin", ["http://evil.example", "http://localhost.evil.example:8080", "null"]
)
async def test_a_post_from_a_foreign_origin_is_forbidden(guarded_app: FastAPI, origin: str) -> None:
    async with client_for(guarded_app) as client:
        response = await client.post("/thing", headers={"Origin": origin})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "foreign_origin"


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_a_safe_method_from_a_foreign_origin_is_not_refused_for_its_origin(
    guarded_app: FastAPI, method: str
) -> None:
    async with client_for(guarded_app) as client:
        response = await client.request(method, "/thing", headers={"Origin": "http://evil.example"})

    assert response.status_code != 403


def receive_from_socket(app: FastAPI, headers: dict[str, str]) -> str:
    with (
        TestClient(app) as client,
        client.websocket_connect("/ws", headers=headers) as websocket,
    ):
        return websocket.receive_text()


def test_a_websocket_without_an_origin_connects(guarded_app: FastAPI) -> None:
    assert receive_from_socket(guarded_app, {"Host": "localhost:8080"}) == "hello"


def test_a_websocket_from_an_allowed_origin_connects(guarded_app: FastAPI) -> None:
    headers = {"Host": "localhost:8080", "Origin": "http://localhost:8080"}

    assert receive_from_socket(guarded_app, headers) == "hello"


def test_a_websocket_from_a_foreign_origin_is_denied(guarded_app: FastAPI) -> None:
    headers = {"Host": "localhost:8080", "Origin": "http://evil.example"}

    with pytest.raises(WebSocketDisconnect):
        receive_from_socket(guarded_app, headers)


def test_a_websocket_to_a_foreign_host_is_denied(guarded_app: FastAPI) -> None:
    with pytest.raises(WebSocketDisconnect):
        receive_from_socket(guarded_app, {"Host": "evil.example"})


async def test_every_response_carries_the_security_headers() -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeaders)

    @app.get("/thing")
    async def read_thing() -> dict[str, str]:
        return {}

    async with client_for(app) as client:
        response = await client.get("/thing")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["content-security-policy"] == "frame-ancestors 'none'"


async def test_a_refusal_carries_the_security_headers_too(guarded_app: FastAPI) -> None:
    guarded_app.add_middleware(SecurityHeaders)

    async with client_for(guarded_app) as client:
        response = await client.get("/thing", headers={"Host": "evil.example"})

    assert response.status_code == 421
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_the_real_app_guards_hosts_and_origins(app: FastAPI) -> None:
    async with client_for(app) as client:
        foreign_host = await client.get("/api/system/health", headers={"Host": "evil.example"})
        foreign_origin = await client.post(
            "/api/rules/reload", headers={"Origin": "http://evil.example"}
        )

    assert foreign_host.status_code == 421
    assert foreign_host.headers["x-frame-options"] == "DENY"
    assert foreign_origin.status_code == 403


def test_the_default_allowed_hosts_are_loopback_and_the_compose_service_name() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@db/t", opensearch_url="http://os:9200"
    )

    assert set(settings.allowed_hosts) == {"localhost", "127.0.0.1", "[::1]", "backend"}


def test_extra_allowed_hosts_come_from_a_comma_separated_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db/t")
    monkeypatch.setenv("OPENSEARCH_URL", "http://os:9200")
    monkeypatch.setenv("TARTARUS_ALLOWED_HOSTS", "lab.lan, Analyst-PC")

    settings = Settings()  # type: ignore[call-arg]

    assert {"lab.lan", "analyst-pc"} <= set(settings.allowed_hosts)
    assert "localhost" in settings.allowed_hosts
