"""What the MSSQL tests share: a hand-written TDS client and a connection to feed the service."""

import asyncio
import json
import struct
from dataclasses import replace

from support import FakeClock, ListSink

from lan_session import HostSpec, ServiceSpec, SessionSpec
from lan_sim.events import Endpoint
from lan_sim.limits import Limits
from lan_sim.service import Connection
from lan_sim.session_log import SessionLog

HOST = HostSpec(
    "fs01.corp.local",
    "192.168.150.201",
    "Windows Server 2019 Standard 10.0.17763",
    (("sa", "Passw0rd"), ("Administrator", "Welcome1")),
    (ServiceSpec("mssql", 1433),),
)
SESSION = SessionSpec("task-1", "192.168.150.10", "small-office", (HOST,))
SOURCE = Endpoint("192.168.150.10", 50000)
DESTINATION = Endpoint("192.168.150.201", 1433)

TDS_71 = 0x71000001
TDS_72 = 0x72090002
TDS_73 = 0x730B0003
TDS_74 = 0x74000004

SQL_BATCH, RPC, REPLY, ATTENTION, LOGIN7, SSPI, PRELOGIN = 1, 3, 4, 6, 0x10, 0x11, 0x12


class RecordingWriter:
    def __init__(self):
        self.written = b""
        self.closing = False

    def write(self, data):
        self.written += data

    async def drain(self):
        return None

    def is_closing(self):
        return self.closing

    def close(self):
        self.closing = True

    def get_extra_info(self, name):
        return None


class Rig:
    """A connection fed with `data`, plus the sink its log writes to and what was written back."""

    def __init__(self, data=b"", *, host=HOST, **limits):
        self.sink = ListSink()
        self.writer = RecordingWriter()
        reader = asyncio.StreamReader()
        reader.feed_data(data)
        reader.feed_eof()
        clock = FakeClock()
        limit_values = replace(Limits(), idle_timeout_seconds=0.2, **limits)
        log = SessionLog("task-1", self.sink, clock, limit_values)
        self.connection = Connection(
            reader=reader,
            writer=self.writer,
            host=host,
            service=host.services[0],
            session=SESSION,
            source=SOURCE,
            destination=DESTINATION,
            log=log.connection_log(host.fqdn, "mssql", SOURCE, DESTINATION),
            clock=clock,
            limits=limit_values,
        )

    def events(self, event_type):
        records = [json.loads(line) for line in self.sink.lines]
        return [record for record in records if record["type"] == event_type]


def packet(packet_type, payload=b"", *, status=1, packet_id=1):
    return struct.pack(">BBHHBB", packet_type, status, 8 + len(payload), 0, packet_id, 0) + payload


def prelogin_request():
    options = [(0, b"\x08\x00\x01\x55\x00\x00"), (1, b"\x00"), (3, b"\x01\x02\x03\x04")]
    table_bytes = 5 * len(options) + 1
    table, values = b"", b""
    for token, value in options:
        table += struct.pack(">BHH", token, table_bytes + len(values), len(value))
        values += value
    return packet(PRELOGIN, table + b"\xff" + values)


def obfuscated(password):
    raw = password.encode("utf-16le")
    return bytes((((byte & 0x0F) << 4) | (byte >> 4)) ^ 0xA5 for byte in raw)


def login7_payload(  # noqa: PLR0913
    *,
    version=TDS_74,
    host="WS01",
    user="sa",
    password="Passw0rd",
    app="tests",
    server="fs01",
    language="",
    database="",
    sspi=b"",
    integrated=False,
    long_sspi=False,
):
    """A Login7 record in the 7.2+ layout (94 fixed bytes, SSPILong), or the 86-byte 7.1 one."""
    fixed_bytes = 94 if version >= TDS_72 else 86
    values = [
        host.encode("utf-16le"),
        user.encode("utf-16le"),
        obfuscated(password),
        app.encode("utf-16le"),
        server.encode("utf-16le"),
        b"",
        app.encode("utf-16le"),
        language.encode("utf-16le"),
        database.encode("utf-16le"),
    ]
    table, body = b"", b""
    for value in values:
        table += struct.pack("<HH", fixed_bytes + len(body) if value else 0, len(value) // 2)
        body += value
    sspi_offset = fixed_bytes + len(body)
    sspi_length = 0xFFFF if long_sspi else len(sspi)
    body += sspi
    flags_2 = 0x80 if integrated else 0
    head = struct.pack("<6I4B2I", 0, version, 4096, 7, 1234, 0, 0xE0, flags_2, 0, 0, 0, 0x409)
    record = head + table + b"\x01\x02\x03\x04\x05\x06"
    record += struct.pack("<HH", sspi_offset if sspi else 0, sspi_length)
    record += struct.pack("<HH", 0, 0)
    if fixed_bytes == 94:
        record += struct.pack("<HHI", 0, 0, len(sspi) if long_sspi else 0)
    record += body
    return struct.pack("<I", len(record)) + record[4:]


def login7_packet(**fields):
    return packet(LOGIN7, login7_payload(**fields))


def all_headers():
    return struct.pack("<IIHQI", 22, 18, 2, 0, 1)


def batch_packet(text, *, headers=True):
    prefix = all_headers() if headers else b""
    return packet(SQL_BATCH, prefix + text.encode("utf-16le"))


def split_packets(data):
    packets = []
    while data:
        length = struct.unpack(">H", data[2:4])[0]
        packets.append((data[0], data[1], data[8:length]))
        data = data[length:]
    return packets


def reply_stream(data):
    """The joined payload of the reply packets in `data`, with a check that they are well framed."""
    packets = split_packets(data)
    assert all(kind == REPLY for kind, _, _ in packets)
    assert [status & 1 for _, status, _ in packets] == [0] * (len(packets) - 1) + [1]
    return b"".join(payload for _, _, payload in packets)


def run_rig(data, body, **limits):
    """Runs `await body(rig)` on a fresh `Rig` in its own loop; returns its result and the rig."""

    async def main():
        rig = Rig(data, **limits)
        return await body(rig), rig

    return asyncio.run(main())


def messages(data):
    """The reply messages in `data`: the packets joined up to each end-of-message bit."""
    joined, current = [], b""
    for kind, status, payload in split_packets(data):
        assert kind == REPLY
        current += payload
        if status & 1:
            joined.append(current)
            current = b""
    assert current == b""
    return joined
