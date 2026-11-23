"""What the fake SQL Server says to a request: a few canned scalars, the text capped for the log.

The SQL text is only ever read. A statement is compared with a short list of known `SELECT`s and
answered from a table; it is never parsed into anything that could run, so `xp_cmdshell` is just
another string that gets logged.
"""

import re
import struct
from dataclasses import dataclass

from lan_session import HostSpec
from lan_sim.identity import netbios_name
from lan_sim.services.mssql_wire import SERVER_VERSION, strip_all_headers

SQL_TEXT_CAP = 4000
MATCHED_TEXT_CAP = 1000
MAX_PROCEDURE_NAME_CHARACTERS = 128
PROCEDURE_BY_ID_MARKER = 0xFFFF
PROCEDURE_NAME_LENGTH_BYTES = 2
PROCEDURE_ID_END = 4

SELECT = re.compile(
    r"select\s+(?P<expression>.+?)"
    r"(?:\s+(?:as\s+)?(?P<alias>[a-z_][a-z0-9_]{0,63}|\[[^\[\]]{1,64}\]))?\s*;?",
    re.IGNORECASE | re.DOTALL,
)
SERVER_PROPERTY = re.compile(r"serverproperty\(n?'([a-z]{1,32})'\)")
OS_BANNER = re.compile(r"(?P<name>.*?)\s*(?P<version>\d+\.\d+)\.(?P<build>\d+)")

WELL_KNOWN_PROCEDURES = {
    1: "sp_cursor",
    2: "sp_cursoropen",
    3: "sp_cursorprepare",
    4: "sp_cursorexecute",
    5: "sp_cursorprepexec",
    6: "sp_cursorunprepare",
    7: "sp_cursorfetch",
    8: "sp_cursoroption",
    9: "sp_cursorclose",
    10: "sp_executesql",
    11: "sp_prepare",
    12: "sp_execute",
    13: "sp_prepexec",
    14: "sp_prepexecrpc",
    15: "sp_unprepare",
}


@dataclass(frozen=True)
class ScalarAnswer:
    column: str
    value: str | None


def server_version_text() -> str:
    return ".".join(str(part) for part in SERVER_VERSION)


def sql_banner(host: HostSpec) -> str:
    """What `@@version` prints on a SQL Server 2019 RTM installed on `host`'s operating system."""
    matched = OS_BANNER.fullmatch(host.os_banner)
    if matched:
        system = f"{matched['name']} {matched['version']} <X64> (Build {matched['build']}: )"
    else:
        system = f"{host.os_banner} <X64>"
    return (
        f"Microsoft SQL Server 2019 (RTM) - {server_version_text()} (X64) \n"
        "\tSep 24 2019 13:48:23 \n"
        "\tCopyright (C) 2019 Microsoft Corporation\n"
        f"\tStandard Edition (64-bit) on {system} (Hypervisor)\n"
    )


def answer_for(text: str, host: HostSpec, user: str) -> ScalarAnswer | None:
    """The canned row for one of the known `SELECT`s, or None for any other statement."""
    if len(text) > MATCHED_TEXT_CAP:
        return None
    matched = SELECT.fullmatch(text.strip())
    if matched is None:
        return None
    expression = re.sub(r"\s+", "", matched["expression"]).casefold()
    columns = {
        "@@version": sql_banner(host),
        "db_name()": "master",
        "suser_name()": user,
        "@@servername": netbios_name(host),
    }
    if expression in columns:
        return ScalarAnswer(_column_name(matched["alias"]), columns[expression])
    property_name = SERVER_PROPERTY.fullmatch(expression)
    if property_name:
        value = _server_properties(host).get(property_name[1])
        return ScalarAnswer(_column_name(matched["alias"]), value)
    return None


def batch_text(payload: bytes) -> str:
    body = strip_all_headers(payload)[: 2 * SQL_TEXT_CAP + 1]
    return body[: len(body) // 2 * 2].decode("utf-16le", errors="replace")


def rpc_procedure(payload: bytes) -> str | None:
    """The procedure an RPC request calls, by name or by its well-known id; None if unreadable."""
    body = strip_all_headers(payload)
    if len(body) < PROCEDURE_NAME_LENGTH_BYTES:
        return None
    (name_length,) = struct.unpack_from("<H", body)
    if name_length == PROCEDURE_BY_ID_MARKER:
        if len(body) < PROCEDURE_ID_END:
            return None
        (procedure_id,) = struct.unpack_from("<H", body, PROCEDURE_NAME_LENGTH_BYTES)
        return WELL_KNOWN_PROCEDURES.get(procedure_id, f"procedure id {procedure_id}")
    end = PROCEDURE_NAME_LENGTH_BYTES + 2 * name_length
    if not 0 < name_length <= MAX_PROCEDURE_NAME_CHARACTERS or end > len(body):
        return None
    return body[PROCEDURE_NAME_LENGTH_BYTES:end].decode("utf-16le", errors="replace")


def _column_name(alias: str | None) -> str:
    return (alias or "").removeprefix("[").removesuffix("]")


def _server_properties(host: HostSpec) -> dict[str, str | None]:
    return {
        "productversion": server_version_text(),
        "productmajorversion": str(SERVER_VERSION[0]),
        "productlevel": "RTM",
        "edition": "Standard Edition (64-bit)",
        "machinename": netbios_name(host),
        "servername": netbios_name(host),
        "instancename": None,
        "isintegratedsecurityonly": "0",
    }
