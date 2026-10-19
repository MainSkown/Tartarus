"""Makes the symbol file (ISF) Volatility3 needs for one Windows kernel, offline once it exists.

`memory_logic` runs Volatility with `--offline`, so an analysis can only name processes of a dump
whose kernel it has symbols for. This module makes that file from the kernel's PDB, which only
Microsoft's symbol server has. The fetch is the one outbound connection of the memory pipeline: it
goes to one fixed https host and sends nothing but the GUID and age in the URL. Converting is
Volatility's own `pdbconv`, run as the unprivileged `cape` user because the PDB is the symbol
server's data, not ours.

Used by the control service (`POST /symbols`) and by `guest-symbols`, which the Windows profile's
`symbols` build step runs. The fetcher and the converter are injected, so everything here is tested
without a network or Volatility installed.
"""

import json
import lzma
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlparse

from control_http import Answer
from volatility import (
    CAPE_ENVIRONMENT,
    CAPE_USER,
    SYMBOLS_DIRECTORY,
    VOLATILITY_PYTHON,
    CommandResult,
    Runner,
    exit_message,
    run_command,
)

# https although Volatility's own constant is http: nothing here needs to be readable on the wire,
# and the GUID is the only thing sent.
SYMBOL_SERVER = "https://msdl.microsoft.com/download/symbols"
KERNEL_PDB = "ntkrnlmp.pdb"
# The kernel's PDB is 11.3 MB; a response past this is not one.
MAX_PDB_BYTES = 50 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 120.0
CONVERT_TIMEOUT_SECONDS = 300.0
# The symbol server answers with a redirect to a content-delivery host (an Azure blob store of
# Microsoft's), so a redirect is followed only to these.
REDIRECT_HOSTS = ("msdl.microsoft.com",)
REDIRECT_HOST_SUFFIXES = (".microsoft.com", ".blob.core.windows.net")
SYMBOL_FILE_MODE = 0o644
SYMBOL_DIRECTORY_MODE = 0o755
OPERATING_SYSTEM_DIRECTORY = "windows"
CONVERTER_MODULE = "volatility3.framework.symbols.windows.pdbconv"
USAGE = "usage: guest-symbols ensure GUID AGE (AGE in decimal, as the PE header prints it)"

GUID_PATTERN = re.compile(r"[0-9A-Fa-f]{32}")
HEXADECIMAL_AGE_PATTERN = re.compile(r"[0-9A-Fa-f]{1,8}")
DECIMAL_AGE_PATTERN = re.compile(r"[0-9]{1,10}")
MAX_AGE = 0xFFFFFFFF
MEGABYTE = 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
# The kernel's ISF is 0.7 MB as `.xz` and 7.6 MB as JSON; the limits are for a file that is not.
MAX_ISF_BYTES = 64 * MEGABYTE
MAX_ISF_JSON_BYTES = 256 * MEGABYTE
REASON_LIMIT = 200

type Fetcher = Callable[[str, int, float], bytes]
type Converter = Callable[[Path, Path], None]
type UrlOpener = Callable[[str, float], Any]


class SymbolsError(Exception):
    """Base of what can go wrong; the message is meant for an operator and holds no path."""


class InvalidSymbolIdError(SymbolsError):
    pass


class SymbolsUnavailableError(SymbolsError):
    """The symbol file could not be made, though the identifier was fine."""


class FetchFailedError(SymbolsUnavailableError):
    pass


class ConversionFailedError(SymbolsUnavailableError):
    pass


class SymbolsNotWrittenError(SymbolsUnavailableError):
    pass


@dataclass(frozen=True)
class SymbolId:
    """The identifier of a kernel PDB: its GUID (upper case) and its age."""

    guid: str
    age: int

    @classmethod
    def parse(cls, guid: object, age: object) -> "SymbolId":
        """Strict: only hexadecimal digits survive, so nothing else can reach a URL or a path.

        `age` is a whole number, or up to 8 hexadecimal digits as in the symbol server's path.
        """
        if not isinstance(guid, str) or not GUID_PATTERN.fullmatch(guid):
            raise InvalidSymbolIdError("guid must be 32 hexadecimal digits")
        return cls(guid.upper(), _age_of(age))

    @property
    def token(self) -> str:
        return f"{self.guid}{self.age:X}"

    @property
    def url(self) -> str:
        return f"{SYMBOL_SERVER}/{KERNEL_PDB}/{self.token}/{KERNEL_PDB}"

    @property
    def file_name(self) -> str:
        stem = KERNEL_PDB.removesuffix(".pdb")
        return f"{OPERATING_SYSTEM_DIRECTORY}/{stem}-{self.token}.json.xz"


def _age_of(age: object) -> int:
    value = None
    if isinstance(age, int) and not isinstance(age, bool):
        value = age
    elif isinstance(age, str) and HEXADECIMAL_AGE_PATTERN.fullmatch(age):
        value = int(age, 16)
    if value is None or not 1 <= value <= MAX_AGE:
        raise InvalidSymbolIdError(
            f"age must be a whole number from 1 to {MAX_AGE} or up to 8 hexadecimal digits"
        )
    return value


class Ensured(NamedTuple):
    path: Path
    created: bool
    file: str


def ensure_symbols(
    guid: object, age: object, symbols_dir: Path, fetch: Fetcher, convert: Converter
) -> Ensured:
    """The symbol file of this kernel under `symbols_dir`, made first if it is not there.

    An existing file that holds this id's symbols means no fetch. The file appears in one rename
    after it was converted and checked, and any failure leaves nothing behind.
    """
    symbol_id = SymbolId.parse(guid, age)
    target = symbols_dir / symbol_id.file_name
    existing = _read_isf(target)
    if existing is not None and _is_isf_of(existing, symbol_id):
        return Ensured(target, created=False, file=symbol_id.file_name)
    pdb = _download(symbol_id, fetch)
    with tempfile.TemporaryDirectory(prefix="tartarus-symbols-") as scratch:
        converted = _convert(pdb, Path(scratch), convert)
    if not _is_isf_of(converted, symbol_id):
        raise ConversionFailedError(f"the converted file is not the symbols of {symbol_id.token}")
    _publish(converted, target, symbols_dir)
    return Ensured(target, created=True, file=symbol_id.file_name)


def _download(symbol_id: SymbolId, fetch: Fetcher) -> bytes:
    pdb = fetch(symbol_id.url, MAX_PDB_BYTES, FETCH_TIMEOUT_SECONDS)
    if not pdb:
        raise FetchFailedError("the symbol server sent an empty file")
    if len(pdb) > MAX_PDB_BYTES:
        raise FetchFailedError(_too_large())
    return pdb


def _too_large() -> str:
    return f"the PDB is larger than {MAX_PDB_BYTES // MEGABYTE} MB"


def _convert(pdb: bytes, scratch: Path, convert: Converter) -> bytes:
    """What the converter wrote, read once: it ran as another user and is trusted once."""
    pdb_file, output = scratch / KERNEL_PDB, scratch / "isf.json.xz"
    pdb_file.write_bytes(pdb)
    pdb_file.chmod(SYMBOL_FILE_MODE)
    convert(pdb_file, output)
    converted = _read_isf(output)
    if converted is None:
        raise ConversionFailedError("the converter made no symbol file")
    return converted


def _publish(converted: bytes, target: Path, symbols_dir: Path) -> None:
    # Written next to the target first, so that the final step is a rename within one directory.
    # The `.part` name does not end in `.json.xz`, which is all Volatility reads.
    part = target.with_name(f".{target.name}.part")
    try:
        for directory in (symbols_dir, target.parent):
            _make_readable_directory(directory)
        part.write_bytes(converted)
        part.chmod(SYMBOL_FILE_MODE)
        os.replace(part, target)
    except OSError as unwritable:
        part.unlink(missing_ok=True)
        raise SymbolsNotWrittenError(
            f"the symbol file could not be written ({type(unwritable).__name__})"
        ) from unwritable


def _make_readable_directory(directory: Path) -> None:
    if not directory.is_dir():
        directory.mkdir(parents=True)
        directory.chmod(SYMBOL_DIRECTORY_MODE)


def _read_isf(file: Path) -> bytes | None:
    """The bytes of a regular file of a sane size (a link is never followed), else None."""
    try:
        if file.is_symlink() or not file.is_file():
            return None
        with file.open("rb") as handle:
            data = handle.read(MAX_ISF_BYTES + 1)
    except OSError:
        return None
    return data if 0 < len(data) <= MAX_ISF_BYTES else None


def _is_isf_of(data: bytes, symbol_id: SymbolId) -> bool:
    """Whether `data` is an ISF of exactly this kernel, by the metadata Volatility finds it by."""
    try:
        text = lzma.LZMADecompressor().decompress(data, max_length=MAX_ISF_JSON_BYTES + 1)
        if len(text) > MAX_ISF_JSON_BYTES:
            return False
        pdb = json.loads(text)["metadata"]["windows"]["pdb"]
        return (
            str(pdb["GUID"]).upper() == symbol_id.guid
            and pdb["age"] == symbol_id.age
            and pdb["database"] == KERNEL_PDB
        )
    except (EOFError, lzma.LZMAError, ValueError, KeyError, TypeError):
        return False


class RestrictedRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to https and a Microsoft host.

    The one place a URL that this module did not build is used.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913, PLR0917 - urllib's signature
        parsed = urlparse(newurl)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or parsed.username or not _is_microsoft_host(host):
            raise FetchFailedError(
                f"the symbol server redirected to {parsed.scheme}://{host}, which is not allowed"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _is_microsoft_host(host: str) -> bool:
    return host in REDIRECT_HOSTS or host.endswith(REDIRECT_HOST_SUFFIXES)


_OPENER = urllib.request.build_opener(RestrictedRedirects)


def _open_url(url: str, timeout: float) -> Any:
    return _OPENER.open(url, timeout=timeout)


def fetch_from_symbol_server(
    url: str,
    max_bytes: int,
    timeout: float,
    open_url: UrlOpener = _open_url,
    clock: Callable[[], float] = time.monotonic,
) -> bytes:
    """The body of `url`, which must be under the fixed symbol server, at most `max_bytes` long.

    `timeout` is for each wait on the socket and, added up, for the whole download.
    """
    if not url.startswith(f"{SYMBOL_SERVER}/"):
        raise FetchFailedError("refusing to fetch from anywhere but the symbol server")
    try:
        with open_url(url, timeout) as response:
            declared = response.headers.get("Content-Length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise FetchFailedError(_too_large())
            body = _read_until(response, max_bytes + 1, timeout, clock)
    except urllib.error.HTTPError as refused:
        raise FetchFailedError(_refusal_message(refused.code)) from refused
    except OSError as unreachable:
        reason = str(getattr(unreachable, "reason", unreachable))[:REASON_LIMIT]
        raise FetchFailedError(
            f"the symbol server could not be reached ({reason})"
        ) from unreachable
    if len(body) > max_bytes:
        raise FetchFailedError(_too_large())
    return body


def _read_until(response: Any, limit: int, timeout: float, clock: Callable[[], float]) -> bytes:
    """Up to `limit` bytes, or until the end of the body, but not for longer than `timeout`."""
    deadline = clock() + timeout
    body = b""
    while len(body) < limit:
        chunk = response.read(min(READ_CHUNK_BYTES, limit - len(body)))
        if not chunk:
            break
        body += chunk
        if clock() > deadline:
            raise FetchFailedError(f"the download timed out after {timeout:.0f} s")
    return body


def _refusal_message(status: int) -> str:
    if status == 404:  # noqa: PLR2004 - HTTP's own number
        return "the symbol server has no PDB for this build (HTTP 404)"
    return f"the symbol server answered HTTP {status}"


def _run_as_cape() -> Runner:
    return partial(run_command, user=CAPE_USER, environment=CAPE_ENVIRONMENT)


def _hand_to_cape(directory: Path) -> None:
    shutil.chown(directory, user=CAPE_USER, group=CAPE_USER)


def convert_with_volatility(
    pdb: Path,
    output: Path,
    *,
    run: Runner | None = None,
    hand_over: Callable[[Path], None] = _hand_to_cape,
) -> None:
    """Volatility's `pdbconv` on a local PDB, as `cape`; the extension of `output` makes it `.xz`.

    `--pattern` names the PDB in the ISF's metadata, which is what Volatility finds it by: without
    it the file says `unknown.pdb` and is never found. No `--guid`, so `pdbconv` itself never
    downloads anything.
    """
    try:
        hand_over(output.parent)
    except (OSError, LookupError) as refused:
        raise ConversionFailedError(
            f"the work folder could not be prepared for {CAPE_USER} ({type(refused).__name__})"
        ) from refused
    command = _converter_command(pdb, output)
    try:
        result = (run or _run_as_cape())(command, CONVERT_TIMEOUT_SECONDS)
    except OSError as unstartable:
        raise ConversionFailedError(
            f"volatility's converter could not be started ({type(unstartable).__name__})"
        ) from unstartable
    _require_success(result)


def _converter_command(pdb: Path, output: Path) -> Sequence[str]:
    return [
        VOLATILITY_PYTHON,
        "-m",
        CONVERTER_MODULE,
        "--file",
        str(pdb),
        "--pattern",
        KERNEL_PDB,
        "--output",
        str(output),
    ]


def _require_success(result: CommandResult) -> None:
    if result.timed_out:
        raise ConversionFailedError(
            f"the conversion timed out after {CONVERT_TIMEOUT_SECONDS:.0f} s"
        )
    if result.returncode != 0:
        raise ConversionFailedError(exit_message(result))


@dataclass(frozen=True)
class SymbolStore:
    directory: Path
    fetch: Fetcher
    convert: Converter

    def ensure(self, guid: object, age: object) -> Ensured:
        return ensure_symbols(guid, age, self.directory, self.fetch, self.convert)


def in_container() -> SymbolStore:
    return SymbolStore(SYMBOLS_DIRECTORY, fetch_from_symbol_server, convert_with_volatility)


def symbols_response(body: Mapping[str, Any], store: SymbolStore) -> Answer:
    if set(body) != {"guid", "age"}:
        return 400, {"error": "send exactly guid and age"}
    try:
        ensured = store.ensure(body["guid"], body["age"])
    except InvalidSymbolIdError as invalid:
        return 400, {"error": str(invalid)}
    except SymbolsUnavailableError as unavailable:
        return 502, {"error": str(unavailable)}
    return 200, {"file": ensured.file, "created": ensured.created}


def command_line(argv: Sequence[str], store: SymbolStore) -> tuple[int, str]:
    """`guest-symbols ensure GUID AGE`: the exit status and the line to print.

    The line is the one the build logs, so a failure reads `symbols: unavailable (reason)`.
    """
    if len(argv) != 3 or argv[0] != "ensure":  # noqa: PLR2004 - the command, the guid and the age
        return 2, USAGE
    _, guid, age_text = argv
    if not DECIMAL_AGE_PATTERN.fullmatch(age_text):
        return 2, "symbols: unavailable (the age must be a decimal number)"
    try:
        ensured = store.ensure(guid, int(age_text))
    except InvalidSymbolIdError as invalid:
        return 2, f"symbols: unavailable ({invalid})"
    except SymbolsUnavailableError as unavailable:
        return 1, f"symbols: unavailable ({unavailable})"
    state = "created" if ensured.created else "already present"
    return 0, f"symbols: ready {ensured.file} ({state})"
