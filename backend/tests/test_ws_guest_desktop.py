import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient, WebSocketTestSession

from app.desktop.admission import (
    CLOSE_CONFLICT,
    CLOSE_NOT_AVAILABLE_YET,
    CLOSE_NOT_FOUND,
)
from app.desktop.guacamole import Instruction, encode
from app.guest.schemas import BuildProgress, GuestDisplay
from app.main import create_app
from app.ws.desktop import DesktopConfig, get_desktop_config, get_guest_build_control, router
from tests.desktop.fake_guacd import OBSERVED_ARGS, FakeGuacd
from tests.desktop.sockets import (
    INTERNAL_FIRST,
    SyncGuacd,
    closed_with,
    desktop_settings,
    drain_until,
    next_instruction,
    open_socket,
)
from tests.desktop.stubs import (
    BUILD_ID,
    BUILD_SCREEN,
    GUEST,
    StubGuestControl,
    build_status,
    building_guest,
    control_unreachable,
    guest_building_with_a_desktop,
)

URL = f"/ws/guests/{GUEST}/desktop"


def wait_until(condition: Callable[[], bool], *, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, "the condition never held"
        time.sleep(0.005)


@dataclass
class BuildDesk:
    app: FastAPI
    client: TestClient
    control: StubGuestControl
    guacd: SyncGuacd
    config: dict[str, Any]

    def connect(self, url: str = URL) -> WebSocketTestSession:
        return open_socket(self.client, url)


@pytest.fixture
def desk() -> Iterator[BuildDesk]:
    app = FastAPI()
    app.include_router(router)
    control = guest_building_with_a_desktop()
    with TestClient(app) as client, client.portal.wrap_async_context_manager(FakeGuacd()) as guacd:
        settings = desktop_settings(guacd_port=guacd.port)
        app.dependency_overrides[get_guest_build_control] = lambda: control
        app.dependency_overrides[get_desktop_config] = lambda: DesktopConfig(**settings)
        yield BuildDesk(app, client, control, SyncGuacd(client, guacd), settings)


def test_the_server_accepts_the_guacamole_subprotocol_and_starts_with_the_tunnel_uuid(
    desk: BuildDesk,
) -> None:
    with desk.connect() as websocket:
        first = websocket.receive_text()

        assert websocket.accepted_subprotocol == "guacamole"
    assert INTERNAL_FIRST.match(first), first


def test_guacd_connects_to_the_host_and_port_the_control_service_named(desk: BuildDesk) -> None:
    desk.control.screens[GUEST] = GuestDisplay(host="localhost", port=5947)

    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")

    (connect,) = [i for i in desk.guacd.received if i.opcode == "connect"]
    assert connect.args[OBSERVED_ARGS.index("hostname")] == "localhost"
    assert connect.args[OBSERVED_ARGS.index("port")] == "5947"


def test_the_clipboard_stays_off_and_the_allowlist_holds_as_for_an_analysis(
    desk: BuildDesk,
) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        websocket.send_text(encode("clipboard", "5", "text/plain"))
        websocket.send_text(encode("mouse", "1", "2", "0"))
        desk.guacd.wait_for_opcode("mouse")

    (connect,) = [i for i in desk.guacd.received if i.opcode == "connect"]
    assert connect.args[24:26] == ("true", "true")
    assert "clipboard" not in desk.guacd.opcodes


def test_the_mouse_and_keyboard_reach_guacd_during_a_pause(desk: BuildDesk) -> None:
    desk.control.builds[BUILD_ID] = build_status(status="paused")

    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        websocket.send_text(encode("key", "65", "1"))
        desk.guacd.wait_for_opcode("key")

    assert desk.guacd.received[-1] == Instruction("key", ("65", "1"))


def test_an_unknown_guest_closes_with_4404(desk: BuildDesk) -> None:
    desk.control.guests.clear()

    with desk.connect() as websocket:
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (CLOSE_NOT_FOUND, "guest not found")
    assert desk.guacd.received == []


def test_a_refused_connection_gets_no_internal_instruction(desk: BuildDesk) -> None:
    desk.control.guests.clear()

    with desk.connect() as websocket:
        message = websocket.receive()

    assert message["type"] == "websocket.close"


@pytest.mark.parametrize(
    "arrange",
    [
        pytest.param(
            lambda c: c.guests.update({GUEST: building_guest(build_id=None)}), id="no-build"
        ),
        pytest.param(lambda c: c.builds.clear(), id="build-unknown"),
        pytest.param(
            lambda c: c.builds.update({BUILD_ID: build_status(desktop=False)}),
            id="not-at-a-desktop-step",
        ),
        pytest.param(
            lambda c: c.builds.update({BUILD_ID: build_status(status="succeeded", desktop=False)}),
            id="succeeded",
        ),
        pytest.param(
            lambda c: c.builds.update({BUILD_ID: build_status(status="failed", desktop=False)}),
            id="failed",
        ),
    ],
)
def test_a_guest_without_a_build_at_a_desktop_step_closes_with_4409(
    desk: BuildDesk, arrange: Any
) -> None:
    arrange(desk.control)

    with desk.connect() as websocket:
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (
        CLOSE_CONFLICT,
        "this guest has no build that shows a desktop",
    )
    assert desk.guacd.received == []


@pytest.mark.parametrize("name", ["LAB1", "lab_1", "x" * 40, "1lab", "a"])
def test_a_name_that_is_not_a_slug_closes_with_4404_and_the_service_is_not_asked(
    desk: BuildDesk, name: str
) -> None:
    with desk.connect(f"/ws/guests/{name}/desktop") as websocket:
        closed = closed_with(websocket)

    assert closed.code == CLOSE_NOT_FOUND
    assert desk.control.calls == []
    assert desk.guacd.received == []


def test_the_tunnel_waits_for_a_display_that_appears_late(desk: BuildDesk) -> None:
    desk.control.screens.clear()
    desk.control.screen_once_asked = (3, BUILD_SCREEN)

    with desk.connect() as websocket:
        websocket.receive_text()
        first = next_instruction(websocket)

    assert first.opcode == "size"


def test_a_display_that_never_appears_closes_with_4408(desk: BuildDesk) -> None:
    desk.control.screens.clear()
    desk.config["port_wait_timeout_s"] = 0.1

    with desk.connect() as websocket:
        websocket.receive_text()
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (CLOSE_NOT_AVAILABLE_YET, "desktop not available yet")
    assert desk.guacd.received == []


def test_the_ping_is_answered_while_the_display_is_still_being_waited_for(
    desk: BuildDesk,
) -> None:
    desk.control.screens.clear()

    with desk.connect() as websocket:
        websocket.receive_text()
        websocket.send_text(encode("", "ping", "1"))
        echoed = next_instruction(websocket)

    assert echoed == Instruction("", ("ping", "1"))


def test_an_unreachable_control_service_closes_with_1011(desk: BuildDesk) -> None:
    desk.control.error = control_unreachable()

    with desk.connect() as websocket:
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (1011, "guest control service unavailable")
    assert desk.guacd.received == []


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_the_tunnel_closes_when_the_build_ends(desk: BuildDesk, status: BuildProgress) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        desk.control.builds[BUILD_ID] = build_status(status=status, desktop=False)
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (1000, "the build no longer shows a desktop")
    desk.guacd.wait_for_disconnect()


def test_the_tunnel_stays_open_through_a_control_service_that_fails_for_a_moment(
    desk: BuildDesk,
) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        checks_before = len(desk.control.calls)
        desk.control.error = control_unreachable()
        wait_until(lambda: len(desk.control.calls) > checks_before)
        desk.control.error = None
        websocket.send_text(encode("key", "66", "1"))
        desk.guacd.wait_for_opcode("key")


def test_the_browser_leaving_closes_the_connection_to_guacd(desk: BuildDesk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")

    desk.guacd.wait_for_disconnect()


def test_the_route_is_wired_into_the_application() -> None:
    app = create_app()
    app.dependency_overrides[get_guest_build_control] = lambda: StubGuestControl()  # noqa: PLW0108 - FastAPI would read the dataclass fields as parameters
    app.dependency_overrides[get_desktop_config] = lambda: DesktopConfig("127.0.0.1", 1)

    with TestClient(app).websocket_connect(URL) as websocket:
        closed = closed_with(websocket)

    assert closed.code == CLOSE_NOT_FOUND
