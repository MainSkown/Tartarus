import asyncio
import re
from collections.abc import Awaitable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.websockets import WebSocketDisconnect
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.types import Message

from app.db.models.analysis import AnalysisStatus
from app.desktop.admission import (
    CLOSE_CONFLICT,
    CLOSE_NOT_AVAILABLE_YET,
    CLOSE_NOT_FOUND,
)
from app.desktop.guacamole import Instruction, InstructionDecoder, encode
from app.main import create_app
from app.ws.desktop import (
    DesktopConfig,
    get_analysis_lookup,
    get_desktop_config,
    get_task_viewer,
    router,
)
from tests.desktop.fake_guacd import GUEST_OFF, FakeGuacd
from tests.desktop.stubs import (
    TASK_ID,
    StubLookup,
    StubViewer,
    cape_unreachable,
    interactive_snapshot,
)

ANALYSIS_ID = 3
URL = f"/ws/analyses/{ANALYSIS_ID}/desktop"
INTERNAL_FIRST = re.compile(
    r"^0\.,36\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12};$"
)
PORT_RECORDED = "interactive=1,nohuman=yes,vnc_port=5902"


RECEIVE_TIMEOUT_S = 3.0


async def _within(seconds: float, receiving: Awaitable[Message]) -> Message:
    async with asyncio.timeout(seconds):
        return await receiving


def receive_within(websocket: WebSocketTestSession, seconds: float) -> Message:
    """The test client's own `receive` blocks forever; a regression should fail, not hang."""
    receiving = websocket._send_rx.receive()
    return websocket.portal.call(_within, seconds, receiving)


class SyncGuacd:
    """`FakeGuacd` driven from the test thread; it lives on the loop the app runs on."""

    def __init__(self, client: TestClient, guacd: FakeGuacd) -> None:
        self._client = client
        self._guacd = guacd

    @property
    def received(self) -> list[Instruction]:
        return list(self._guacd.received)

    @property
    def opcodes(self) -> list[str]:
        return self._guacd.opcodes

    def push(self, *instructions: str) -> None:
        self._client.portal.call(self._guacd.push, *instructions)

    def hang_up(self) -> None:
        self._client.portal.call(self._hang_up)

    async def _hang_up(self) -> None:
        self._guacd.hang_up()

    def wait_for_opcode(self, opcode: str) -> Instruction:
        return self._client.portal.call(self._guacd.wait_for_opcode, opcode)

    def wait_for_disconnect(self) -> None:
        self._client.portal.call(self._guacd.wait_for_disconnect)


@dataclass
class Desk:
    app: FastAPI
    client: TestClient
    lookup: StubLookup
    viewer: StubViewer
    guacd: SyncGuacd
    config: dict[str, Any]

    def connect(self) -> WebSocketTestSession:
        session = self.client.websocket_connect(URL, subprotocols=["guacamole"])
        session.receive = lambda: receive_within(session, RECEIVE_TIMEOUT_S)
        return session


def make_desk(after_ready: tuple[str, ...] | None = None, **config: Any) -> Iterator[Desk]:
    app = FastAPI()
    app.include_router(router)
    lookup = StubLookup({ANALYSIS_ID: interactive_snapshot()})
    viewer = StubViewer({TASK_ID: PORT_RECORDED})
    guacd_args = {} if after_ready is None else {"after_ready": after_ready}
    with TestClient(app) as client:
        fake = client.portal.wrap_async_context_manager(FakeGuacd(**guacd_args))
        with fake as guacd:
            settings: dict[str, Any] = {
                "guacd_host": "127.0.0.1",
                "guacd_port": guacd.port,
                "port_poll_interval_s": 0.01,
                "port_wait_timeout_s": 5.0,
                "status_check_interval_s": 0.02,
                "handshake_timeout_s": 1.0,
            } | config
            app.dependency_overrides[get_analysis_lookup] = lambda: lookup
            app.dependency_overrides[get_task_viewer] = lambda: viewer
            app.dependency_overrides[get_desktop_config] = lambda: DesktopConfig(**settings)
            yield Desk(app, client, lookup, viewer, SyncGuacd(client, guacd), settings)


@pytest.fixture
def desk() -> Iterator[Desk]:
    yield from make_desk()


@pytest.fixture
def desk_with_guest_off() -> Iterator[Desk]:
    yield from make_desk(after_ready=GUEST_OFF)


@pytest.fixture
def desk_without_guacd() -> Iterator[Desk]:
    yield from make_desk(guacd_port=1)


def receive_until_closed(websocket: WebSocketTestSession) -> None:
    while True:
        websocket.receive_text()


def closed_with(websocket: WebSocketTestSession) -> WebSocketDisconnect:
    with pytest.raises(WebSocketDisconnect) as closed:
        receive_until_closed(websocket)
    return closed.value


def instruction_of(frame: str) -> Instruction:
    (instruction,) = InstructionDecoder().feed(frame)
    return instruction


def next_instruction(websocket: WebSocketTestSession) -> Instruction:
    return instruction_of(websocket.receive_text())


def drain_until(websocket: WebSocketTestSession, opcode: str) -> Instruction:
    while (instruction := next_instruction(websocket)).opcode != opcode:
        pass
    return instruction


def test_the_server_accepts_the_guacamole_subprotocol_the_browser_asks_for(desk: Desk) -> None:
    with desk.connect() as websocket:
        assert websocket.accepted_subprotocol == "guacamole"


def test_the_first_frame_is_the_internal_instruction_with_the_tunnel_uuid(desk: Desk) -> None:
    with desk.connect() as websocket:
        first = websocket.receive_text()

    assert INTERNAL_FIRST.match(first), first


def test_each_tunnel_gets_its_own_uuid(desk: Desk) -> None:
    with desk.connect() as first_socket:
        first = first_socket.receive_text()
    with desk.connect() as second_socket:
        second = second_socket.receive_text()

    assert first != second


def test_guacd_is_asked_for_the_vnc_port_cape_recorded_on_localhost(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")

    (connect,) = [i for i in desk.guacd.received if i.opcode == "connect"]
    assert connect.args[1:3] == ("127.0.0.1", "5902")
    assert connect.args[24:26] == ("true", "true")


def test_the_guest_screen_reaches_the_browser_one_instruction_per_frame(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        seen = [next_instruction(websocket) for _ in range(2)]
        desk.guacd.push(encode("sync", "100"), encode("img", "3", "14", "0", "image/png", "0", "0"))
        seen += [next_instruction(websocket) for _ in range(2)]

    assert [i.opcode for i in seen] == ["size", "size", "sync", "img"]
    assert seen[2] == Instruction("sync", ("100",))


def test_the_mouse_and_keyboard_reach_guacd(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        websocket.send_text(encode("mouse", "10", "20", "1"))
        websocket.send_text(encode("key", "65", "1"))
        websocket.send_text(encode("sync", "100"))
        desk.guacd.wait_for_opcode("sync")

    forwarded = desk.guacd.received[-3:]
    assert forwarded == [
        Instruction("mouse", ("10", "20", "1")),
        Instruction("key", ("65", "1")),
        Instruction("sync", ("100",)),
    ]


def test_two_instructions_in_one_frame_are_both_forwarded(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        websocket.send_text(encode("mouse", "1", "2", "0") + encode("key", "65", "1"))
        desk.guacd.wait_for_opcode("key")

    assert desk.guacd.opcodes[-2:] == ["mouse", "key"]


@pytest.mark.parametrize(
    "dropped",
    [
        encode("clipboard", "5", "text/plain"),
        encode("file", "5", "application/octet-stream", "evil.exe"),
        encode("put", "5", "x"),
        encode("get", "5", "x"),
        encode("pipe", "5", "text/plain", "x"),
        encode("argv", "5", "text/plain", "x"),
        encode("disconnect"),
        encode("select", "rdp"),
        encode("connect", "VERSION_1_5_0", "10.0.0.1", "22"),
    ],
)
def test_instructions_off_the_allowlist_never_reach_guacd(desk: Desk, dropped: str) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        websocket.send_text(dropped)
        websocket.send_text(encode("nop"))
        desk.guacd.wait_for_opcode("nop")

    dropped_opcode = instruction_of(dropped).opcode
    sent_after_handshake = desk.guacd.opcodes[desk.guacd.opcodes.index("connect") + 1 :]
    assert dropped_opcode not in sent_after_handshake
    assert desk.guacd.opcodes.count("select") == 1
    assert desk.guacd.opcodes.count("connect") == 1


def test_the_internal_ping_is_echoed_and_not_forwarded(desk: Desk) -> None:
    ping = encode("", "ping", "1700000000000")
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        websocket.send_text(ping)
        echoed = drain_until(websocket, "")
        websocket.send_text(encode("nop"))
        desk.guacd.wait_for_opcode("nop")

    assert echoed == Instruction("", ("ping", "1700000000000"))
    assert "" not in desk.guacd.opcodes


def test_the_ping_is_answered_while_the_port_is_still_being_waited_for(desk: Desk) -> None:
    desk.viewer.options[TASK_ID] = "interactive=1"
    with desk.connect() as websocket:
        websocket.receive_text()
        websocket.send_text(encode("", "ping", "1"))
        echoed = next_instruction(websocket)

    assert echoed == Instruction("", ("ping", "1"))


def test_an_unknown_analysis_closes_with_4404(desk: Desk) -> None:
    desk.lookup.snapshots.clear()

    with desk.connect() as websocket:
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (CLOSE_NOT_FOUND, "analysis not found")
    assert desk.guacd.received == []


@pytest.mark.parametrize(
    "status", [AnalysisStatus.QUEUED, AnalysisStatus.PROCESSING, AnalysisStatus.DONE]
)
def test_an_analysis_that_is_not_running_closes_with_4409(
    desk: Desk, status: AnalysisStatus
) -> None:
    desk.lookup.snapshots[ANALYSIS_ID] = interactive_snapshot(status)

    with desk.connect() as websocket:
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (
        CLOSE_CONFLICT,
        f"analysis is {status.value}, not running",
    )
    assert desk.guacd.received == []


def test_an_analysis_submitted_without_interactive_closes_with_4409(desk: Desk) -> None:
    desk.lookup.snapshots[ANALYSIS_ID] = interactive_snapshot(interactive=False)

    with desk.connect() as websocket:
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (
        CLOSE_CONFLICT,
        "analysis was not submitted as interactive",
    )
    assert desk.guacd.received == []


def test_a_refused_connection_gets_no_internal_instruction(desk: Desk) -> None:
    desk.lookup.snapshots.clear()

    with desk.connect() as websocket:
        message = websocket.receive()

    assert message["type"] == "websocket.close"


def test_the_tunnel_waits_for_a_port_that_cape_records_late(desk: Desk) -> None:
    desk.viewer.options[TASK_ID] = "interactive=1,nohuman=yes"
    with desk.connect() as websocket:
        websocket.receive_text()
        desk.viewer.options[TASK_ID] = PORT_RECORDED
        first = next_instruction(websocket)

    assert first.opcode == "size"
    assert desk.viewer.viewed.count(TASK_ID) >= 1


def test_a_port_that_never_appears_closes_with_4408(desk: Desk) -> None:
    desk.viewer.options[TASK_ID] = "interactive=1"
    desk.config["port_wait_timeout_s"] = 0.1

    with desk.connect() as websocket:
        websocket.receive_text()
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (CLOSE_NOT_AVAILABLE_YET, "desktop not available yet")
    assert desk.guacd.received == []


def test_waiting_for_the_port_survives_a_cape_that_fails_for_a_moment(desk: Desk) -> None:
    desk.viewer.errors.append(cape_unreachable())

    with desk.connect() as websocket:
        websocket.receive_text()
        first = next_instruction(websocket)

    assert first.opcode == "size"


def test_the_analysis_stopping_while_waiting_for_the_port_closes_with_4409(desk: Desk) -> None:
    desk.viewer.options[TASK_ID] = "interactive=1"
    with desk.connect() as websocket:
        websocket.receive_text()
        desk.lookup.snapshots[ANALYSIS_ID] = interactive_snapshot(AnalysisStatus.PROCESSING)
        closed = closed_with(websocket)

    assert closed.code == CLOSE_CONFLICT


def test_a_guest_that_is_off_gets_its_error_forwarded_and_then_the_tunnel_closes(
    desk_with_guest_off: Desk,
) -> None:
    with desk_with_guest_off.connect() as websocket:
        websocket.receive_text()
        error = next_instruction(websocket)
        closed = closed_with(websocket)

    assert error == Instruction("error", ("Aborted. See logs.", "519"))
    assert closed.code == 1000
    desk_with_guest_off.guacd.wait_for_disconnect()


def test_the_tunnel_closes_when_guacd_hangs_up(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        desk.guacd.hang_up()
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (1000, "desktop closed")


def test_the_tunnel_closes_when_the_analysis_stops_running(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        desk.lookup.snapshots[ANALYSIS_ID] = interactive_snapshot(AnalysisStatus.PROCESSING)
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (1000, "analysis is no longer running")
    desk.guacd.wait_for_disconnect()


def test_the_analysis_being_deleted_closes_the_tunnel(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        desk.lookup.snapshots.clear()
        closed = closed_with(websocket)

    assert closed.code == 1000


def test_the_browser_leaving_closes_the_connection_to_guacd(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")

    desk.guacd.wait_for_disconnect()


def test_a_malformed_frame_from_the_browser_closes_with_1002(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        websocket.send_text("this is not guacamole")
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (1002, "malformed instruction")
    desk.guacd.wait_for_disconnect()


def test_a_guacd_that_cannot_be_reached_closes_with_1011(desk_without_guacd: Desk) -> None:
    with desk_without_guacd.connect() as websocket:
        websocket.receive_text()
        closed = closed_with(websocket)

    assert (closed.code, closed.reason) == (1011, "desktop service unavailable")


def test_binary_frames_from_the_browser_are_ignored(desk: Desk) -> None:
    with desk.connect() as websocket:
        websocket.receive_text()
        drain_until(websocket, "size")
        websocket.send_bytes(b"\x00\x01")
        websocket.send_text(encode("nop"))
        desk.guacd.wait_for_opcode("nop")


def test_the_route_is_wired_into_the_application() -> None:
    app = create_app()
    app.dependency_overrides[get_analysis_lookup] = lambda: StubLookup()  # noqa: PLW0108 - FastAPI would read the class's fields as parameters
    app.dependency_overrides[get_task_viewer] = lambda: StubViewer()  # noqa: PLW0108
    app.dependency_overrides[get_desktop_config] = lambda: DesktopConfig("127.0.0.1", 1)

    with TestClient(app).websocket_connect(URL) as websocket:
        closed = closed_with(websocket)

    assert closed.code == CLOSE_NOT_FOUND
