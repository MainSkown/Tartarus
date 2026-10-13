"""The connection from the backend to `guacd`, and the rules for what may pass through it.

Nothing the browser sends decides where `guacd` connects: the host is a constant and the port
is the VNC port CAPE recorded for the task (see `app.desktop.vnc`).
"""

import asyncio
import codecs
import contextlib
import logging
from collections import deque
from collections.abc import Mapping, Sequence
from typing import Self

from app.desktop.guacamole import Instruction, InstructionDecoder, ProtocolError, encode

logger = logging.getLogger(__name__)

VNC_HOST = "127.0.0.1"
SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_DPI = "1280", "800", "96"
IMAGE_MIMETYPES = ("image/png", "image/jpeg", "image/webp")
HANDSHAKE_TIMEOUT_S = 10.0
READ_SIZE = 65536
VERSION_ARG_PREFIX = "VERSION_"

# `guacd` offers no clipboard to a browser that never asks for one, and the parameters below
# switch it off at `guacd` too; this list is the second lock.
BROWSER_OPCODES = frozenset({"mouse", "key", "size", "sync", "ack", "blob", "end", "nop"})
# The first of these after `ready` means the desktop is drawing; `ready` alone also arrives
# when the guest is off (followed by `error`).
DISPLAY_OPCODES = frozenset({"size", "img", "blob", "rect", "cfill", "copy", "cursor"})


class TunnelError(Exception):
    """`guacd` could not be reached, or did not speak the handshake."""


def forwardable_from_browser(instruction: Instruction) -> bool:
    return instruction.opcode in BROWSER_OPCODES


def connect_values(vnc_port: int) -> Mapping[str, str]:
    return {
        "hostname": VNC_HOST,
        "port": str(vnc_port),
        "read-only": "false",
        "disable-copy": "true",
        "disable-paste": "true",
        "color-depth": "24",
        "cursor": "remote",
        "autoretry": "0",
    }


def connect_instruction(arg_names: Sequence[str], *, vnc_port: int) -> Instruction:
    """One value per name `guacd` listed, in its order; names we have no value for stay empty."""
    values = connect_values(vnc_port)
    return Instruction(
        "connect",
        tuple(
            name if name.startswith(VERSION_ARG_PREFIX) else values.get(name, "")
            for name in arg_names
        ),
    )


class GuacdTunnel:
    """A handshaken connection to `guacd`; `receive` and `send` carry instructions after `ready`."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        decoder: InstructionDecoder,
        waiting: deque[Instruction],
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._decoder = decoder
        self._text = codecs.getincrementaldecoder("utf-8")()
        self._waiting = waiting
        self.connected = False

    @classmethod
    async def open(
        cls,
        host: str,
        port: int,
        *,
        vnc_port: int,
        handshake_timeout_s: float = HANDSHAKE_TIMEOUT_S,
    ) -> Self:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=handshake_timeout_s
            )
        except (OSError, TimeoutError):
            raise TunnelError("could not reach guacd") from None
        tunnel = cls(reader, writer, InstructionDecoder(), deque())
        try:
            async with asyncio.timeout(handshake_timeout_s):
                await tunnel._handshake(vnc_port)
        except TimeoutError:
            await tunnel.close()
            raise TunnelError("guacd handshake timed out") from None
        except BaseException:
            await tunnel.close()
            raise
        return tunnel

    async def receive(self) -> Instruction | None:
        """The next instruction from `guacd`, or None once it has closed the connection."""
        try:
            instruction = await self._next_instruction()
        except ConnectionError:
            return None
        if instruction is not None and instruction.opcode in DISPLAY_OPCODES:
            self.connected = True
        return instruction

    async def send(self, instruction: Instruction) -> None:
        self._writer.write(encode(instruction.opcode, *instruction.args).encode("utf-8"))
        try:
            await self._writer.drain()
        except ConnectionError:
            raise TunnelError("guacd closed the connection") from None

    async def close(self) -> None:
        self._writer.close()
        with contextlib.suppress(ConnectionError):
            await self._writer.wait_closed()

    async def _handshake(self, vnc_port: int) -> None:
        await self.send(Instruction("select", ("vnc",)))
        arguments = await self._expect("args")
        for preference in (
            Instruction("size", (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_DPI)),
            Instruction("audio", ()),
            Instruction("video", ()),
            Instruction("image", IMAGE_MIMETYPES),
            Instruction("timezone", ("UTC",)),
            connect_instruction(arguments.args, vnc_port=vnc_port),
        ):
            await self.send(preference)
        await self._expect("ready")

    async def _expect(self, opcode: str) -> Instruction:
        while True:
            instruction = await self._read_during_handshake()
            if instruction.opcode == opcode:
                return instruction
            if instruction.opcode == "error":
                message = instruction.args[0] if instruction.args else "no message"
                raise TunnelError(f"guacd refused the handshake: {message}")
            logger.debug("ignored %r while waiting for %r", instruction.opcode, opcode)

    async def _read_during_handshake(self) -> Instruction:
        try:
            instruction = await self._next_instruction()
        except ConnectionError:
            instruction = None
        if instruction is None:
            raise TunnelError("guacd closed the connection during the handshake")
        return instruction

    async def _next_instruction(self) -> Instruction | None:
        while not self._waiting:
            data = await self._reader.read(READ_SIZE)
            if not data:
                return None
            try:
                self._waiting.extend(self._decoder.feed(self._text.decode(data)))
            except (ProtocolError, UnicodeDecodeError):
                raise TunnelError("guacd did not speak the Guacamole protocol") from None
        return self._waiting.popleft()
