"""What the tests of the two desktop routes share: a socket that fails instead of hanging, the
fake `guacd` driven from the test thread, and reading what the server sent."""

import asyncio
import re
from collections.abc import Awaitable
from typing import Any

import pytest
from fastapi.websockets import WebSocketDisconnect
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.types import Message

from app.desktop.guacamole import Instruction, InstructionDecoder
from tests.desktop.fake_guacd import FakeGuacd

INTERNAL_FIRST = re.compile(
    r"^0\.,36\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12};$"
)

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


def open_socket(client: TestClient, url: str) -> WebSocketTestSession:
    session = client.websocket_connect(url, subprotocols=["guacamole"])
    session.receive = lambda: receive_within(session, RECEIVE_TIMEOUT_S)
    return session


def desktop_settings(**overrides: Any) -> dict[str, Any]:
    return {
        "guacd_host": "127.0.0.1",
        "port_poll_interval_s": 0.01,
        "port_wait_timeout_s": 5.0,
        "status_check_interval_s": 0.02,
        "handshake_timeout_s": 1.0,
    } | overrides


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
