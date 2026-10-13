"""WebSocket clients for scripts/e2e.sh: they record what the live and desktop sockets send and
print one JSON summary on stdout. They assert nothing; scripts/lib/e2e-live.sh does, over it.

    live_client.py live    BASE ID [--include-api] [--query-probe] [--reconnect] [--deadline S]
    live_client.py desktop BASE ID [--clipboard] [--deadline S]

BASE is the frontend's address (http://host:port); the sockets are opened through it, as a browser
does. Needs the `websockets` package, which the backend's environment has.
"""

import argparse
import asyncio
import base64
import collections
import contextlib
import json
import re
import sys
import time
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.typing import Subprotocol

CLOSE_NORMAL = 1000
CLOSE_NOT_FOUND = 4404
FINAL_CLOSES = (CLOSE_NORMAL, CLOSE_NOT_FOUND)
RECONNECT_PAUSE_S = 1.0
OPEN_TIMEOUT_S = 10
CLIPBOARD_STREAM = 9
# guacd ends a connection (error 776, client timeout) whose client stays silent for 15 s; the
# browser library sends a `nop` every 5 s for the same reason.
KEEP_ALIVE_S = 5.0
DESKTOP_SUBPROTOCOL = Subprotocol("guacamole")
QUERY_PROBE = "process.name:cmd.exe"
INSTRUCTION_HEAD = re.compile(r"^(\d+)\.")


def websocket_url(base: str, analysis_id: str, route: str) -> str:
    return re.sub(r"^http", "ws", base.rstrip("/")) + f"/ws/analyses/{analysis_id}/{route}"


# --- the live feed ---------------------------------------------------------------------------


def call_key(event: dict[str, Any]) -> str:
    """What identifies the call behind an event whatever its id: process, time, action and API."""
    process = event.get("process") or {}
    return f"{process.get('pid')}|{event['@timestamp']}|{event['event']['action']}|{(event.get('api') or {}).get('name')}"


def describe(message: dict[str, Any], seconds: float, connection: int) -> dict[str, Any]:
    kind, data = message["type"], message["data"]
    record: dict[str, Any] = {"t": round(seconds, 2), "conn": connection, "type": kind}
    if kind == "status":
        record.update(status=data["status"], phase=data["phase"])
    elif kind == "events":
        events = data["events"]
        record.update(
            n=len(events),
            dropped=data["dropped"],
            ids=[event["event"]["id"] for event in events],
            calls=[call_key(event) for event in events],
            api=sum(event["tartarus"]["lane"] == "api" for event in events),
        )
    elif kind == "process":
        node = data["node"]
        record.update(op=data["op"], pid=node["pid"], ppid=node.get("ppid"), name=node.get("name"))
    elif kind == "error":
        record.update(code=data["code"])
    elif kind == "phase":
        record.update(phase=data["phase"])
    return record


class LiveRecording:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.started = time.monotonic()
        self.messages: list[dict[str, Any]] = []
        self.connections: list[dict[str, Any]] = []
        self.probe_sent = False

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    async def follow(self, socket: ClientConnection, connection: int) -> None:
        if self.args.include_api:
            await socket.send(json.dumps({"type": "subscribe", "data": {"include_api": True}}))
        async for raw in socket:
            record = describe(json.loads(raw), self.elapsed(), connection)
            self.messages.append(record)
            if self.args.query_probe and record["type"] == "events" and not self.probe_sent:
                self.probe_sent = True
                probe = {"type": "subscribe", "data": {"query": QUERY_PROBE}}
                await socket.send(json.dumps(probe))

    async def connect_once(self, connection: int) -> bool:
        """Follows one connection to its end; True when no further attempt is wanted."""
        opened = self.elapsed()
        entry: dict[str, Any] = {"index": connection, "opened_at": round(opened, 2), "code": None}
        self.connections.append(entry)
        try:
            async with websockets.connect(
                websocket_url(self.args.base, self.args.id, "live"),
                max_size=None,
                open_timeout=OPEN_TIMEOUT_S,
            ) as socket:
                with contextlib.suppress(websockets.ConnectionClosed):
                    await self.follow(socket, connection)
                entry["code"] = socket.close_code
        except (OSError, websockets.InvalidHandshake, TimeoutError) as error:
            entry["error"] = type(error).__name__
        entry["closed_at"] = round(self.elapsed(), 2)
        return entry["code"] in FINAL_CLOSES or not self.args.reconnect

    async def run(self) -> dict[str, Any]:
        timed_out = False
        try:
            async with asyncio.timeout(self.args.deadline):
                connection = 0
                while not await self.connect_once(connection):
                    connection += 1
                    await asyncio.sleep(RECONNECT_PAUSE_S)
        except TimeoutError:
            timed_out = True
        return {"connections": self.connections, "messages": self.messages, "timed_out": timed_out}


# --- the desktop tunnel ----------------------------------------------------------------------


def encode(*elements: str) -> str:
    return ",".join(f"{len(element)}.{element}" for element in elements) + ";"


def decode(frame: str) -> list[str]:
    elements, at = [], 0
    while at < len(frame):
        head = INSTRUCTION_HEAD.match(frame[at:])
        if head is None:
            break
        start = at + head.end()
        length = int(head.group(1))
        elements.append(frame[start : start + length])
        at = start + length + 1
    return elements


class DesktopRecording:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.started = time.monotonic()
        self.first_frame: str | None = None
        self.opcodes: collections.Counter[str] = collections.Counter()
        self.first_display_at: float | None = None
        self.clipboard_sent_at: float | None = None
        self.after_clipboard: collections.Counter[str] = collections.Counter()
        self.clipboard_replies: list[str] = []
        self.ping_echoed = False
        self.errors: list[list[str]] = []
        self.acks: list[str] = []

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    async def send_clipboard(self, socket: ClientConnection) -> None:
        stream = str(CLIPBOARD_STREAM)
        payload = base64.b64encode(b"from the e2e client").decode()
        await socket.send(encode("clipboard", stream, "text/plain"))
        await socket.send(encode("blob", stream, payload))
        await socket.send(encode("end", stream))
        await socket.send(encode("", "ping", str(int(time.time() * 1000))))
        self.clipboard_sent_at = self.elapsed()

    def note(self, frame: str) -> list[str]:
        elements = decode(frame)
        opcode = elements[0] if elements else ""
        self.opcodes[opcode] += 1
        if self.first_frame is None:
            self.first_frame = frame
        if opcode == "error":
            self.errors.append(elements[1:])
        if opcode == "ack":
            self.acks.append(frame)
        if self.first_display_at is None and opcode in ("size", "img"):
            self.first_display_at = self.elapsed()
        if self.clipboard_sent_at is not None:
            self.after_clipboard[opcode] += 1
            if opcode == "clipboard" or (opcode != "blob" and "clipboard" in frame.lower()):
                self.clipboard_replies.append(frame)
            if opcode == "" and elements[1:2] == ["ping"]:
                self.ping_echoed = True
        return elements

    async def keep_alive(self, socket: ClientConnection) -> None:
        while True:
            await asyncio.sleep(KEEP_ALIVE_S)
            await socket.send(encode("nop"))

    async def follow(self, socket: ClientConnection) -> None:
        keep_alive = asyncio.create_task(self.keep_alive(socket))
        try:
            await self.read_frames(socket)
        finally:
            keep_alive.cancel()

    async def read_frames(self, socket: ClientConnection) -> None:
        async for raw in socket:
            elements = self.note(str(raw))
            if elements[:1] == ["sync"]:
                await socket.send(encode("sync", elements[1]))
            if self.args.clipboard and self.first_display_at and self.clipboard_sent_at is None:
                await self.send_clipboard(socket)

    async def run(self) -> dict[str, Any]:
        close_code: int | None = None
        close_reason = ""
        error = None
        timed_out = False
        try:
            async with asyncio.timeout(self.args.deadline):
                async with websockets.connect(
                    websocket_url(self.args.base, self.args.id, "desktop"),
                    subprotocols=[DESKTOP_SUBPROTOCOL],
                    max_size=None,
                    open_timeout=OPEN_TIMEOUT_S,
                ) as socket:
                    with contextlib.suppress(websockets.ConnectionClosed):
                        await self.follow(socket)
                    close_code = socket.close_code
                    close_reason = socket.close_reason or ""
        except TimeoutError:
            timed_out = True
        except (OSError, websockets.InvalidHandshake) as failure:
            error = type(failure).__name__
        return {
            "first_frame": self.first_frame,
            "first_display_at": self.first_display_at,
            "clipboard_sent_at": self.clipboard_sent_at,
            "opcodes": dict(self.opcodes),
            "after_clipboard": dict(self.after_clipboard),
            "clipboard_replies": self.clipboard_replies,
            "ping_echoed": self.ping_echoed,
            "errors": self.errors,
            "acks": self.acks,
            "close_code": close_code,
            "close_reason": close_reason,
            "closed_at": round(self.elapsed(), 2),
            "error": error,
            "timed_out": timed_out,
        }


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["live", "desktop"])
    parser.add_argument("base")
    parser.add_argument("id")
    parser.add_argument("--deadline", type=float, default=600)
    parser.add_argument("--include-api", action="store_true")
    parser.add_argument("--query-probe", action="store_true")
    parser.add_argument("--reconnect", action="store_true")
    parser.add_argument("--clipboard", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_arguments(argv)
    recording = LiveRecording(args) if args.mode == "live" else DesktopRecording(args)
    sys.stdout.write(json.dumps(asyncio.run(recording.run())) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
