import asyncio
from typing import Self

from app.desktop.guacamole import Instruction, InstructionDecoder, encode

OBSERVED_ARGS = (
    "VERSION_1_5_0",
    "hostname",
    "port",
    "read-only",
    "disable-display-resize",
    "encodings",
    "username",
    "password",
    "swap-red-blue",
    "color-depth",
    "cursor",
    "autoretry",
    "clipboard-encoding",
    "dest-host",
    "dest-port",
    "reverse-connect",
    "listen-timeout",
    "recording-path",
    "recording-name",
    "recording-exclude-output",
    "recording-exclude-mouse",
    "recording-include-keys",
    "create-recording-path",
    "recording-write-existing",
    "disable-copy",
    "disable-paste",
    "disable-server-input",
    "wol-send-packet",
    "wol-mac-addr",
    "wol-broadcast-addr",
    "wol-udp-port",
    "wol-wait-time",
    "force-lossless",
    "compress-level",
    "quality-level",
)

# What the D1 investigation saw `guacd` 1.6.0 send after `connect` when the guest was up.
SCREEN_UP = (encode("size", "-2", "5", "5"), encode("size", "0", "1280", "800"))
# And when the guest was off: `ready` is still answered, then the upstream error.
GUEST_OFF = (encode("error", "Aborted. See logs.", "519"), encode("nop"))


class FakeGuacd:
    """A stand-in for `guacd` that speaks the handshake of the D1 transcript.

    `after_ready` is sent in the same write as `ready`, as the real one does for the guest-off
    `ready` + `error` pair. `byte_chunk` cuts what it sends into pieces that size, to put
    TCP boundaries in the middle of instructions and of multi-byte characters.
    """

    def __init__(  # noqa: PLR0913 - one switch per behaviour a test can ask for
        self,
        *,
        args: tuple[str, ...] = OBSERVED_ARGS,
        after_ready: tuple[str, ...] = SCREEN_UP,
        answer_select: str | None = None,
        byte_chunk: int | None = None,
        answer_connect: bool = True,
        hang_up_on: str | None = None,
    ) -> None:
        self.received: list[Instruction] = []
        self.connections = 0
        self.disconnects = 0
        self._args = args
        self._after_ready = after_ready
        self._answer_select = answer_select
        self._byte_chunk = byte_chunk
        self._answer_connect = answer_connect
        self._hang_up_on = hang_up_on
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self._got_instruction = asyncio.Event()
        self._disconnected = asyncio.Event()

    async def __aenter__(self) -> Self:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *_: object) -> None:
        assert self._server is not None
        self._server.close()
        for writer in self._writers:
            writer.close()
        await self._server.wait_closed()

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.sockets[0].getsockname()[1])

    @property
    def opcodes(self) -> list[str]:
        return [instruction.opcode for instruction in self.received]

    async def push(self, *instructions: str) -> None:
        await self._write(self._writers[-1], "".join(instructions))

    def hang_up(self) -> None:
        self._writers[-1].close()

    async def wait_for_disconnect(self, *, timeout_s: float = 2.0) -> None:
        async with asyncio.timeout(timeout_s):
            await self._disconnected.wait()

    async def wait_for_opcode(self, opcode: str, *, timeout_s: float = 2.0) -> Instruction:
        async with asyncio.timeout(timeout_s):
            while True:
                for instruction in self.received:
                    if instruction.opcode == opcode:
                        return instruction
                self._got_instruction.clear()
                await self._got_instruction.wait()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._writers.append(writer)
        decoder = InstructionDecoder()
        try:
            while data := await reader.read(65536):
                for instruction in decoder.feed(data.decode("utf-8")):
                    self.received.append(instruction)
                    self._got_instruction.set()
                    await self._react(writer, instruction)
        except ConnectionError:
            pass
        finally:
            self.disconnects += 1
            self._disconnected.set()
            writer.close()

    async def _react(self, writer: asyncio.StreamWriter, instruction: Instruction) -> None:
        if instruction.opcode == self._hang_up_on:
            writer.close()
        elif instruction.opcode == "select":
            await self._write(writer, self._answer_select or encode("args", *self._args))
        elif instruction.opcode == "connect" and self._answer_connect:
            await self._write(writer, encode("ready", "$conn-1") + "".join(self._after_ready))

    async def _write(self, writer: asyncio.StreamWriter, text: str) -> None:
        data = text.encode("utf-8")
        step = self._byte_chunk or len(data) or 1
        for start in range(0, len(data), step):
            writer.write(data[start : start + step])
            await writer.drain()
            if self._byte_chunk:
                await asyncio.sleep(0)
