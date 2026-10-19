"""Tests of `bin/symbols_logic.py`: making the Windows kernel's symbol file (ISF) for Volatility3.

The symbol server and the converter are injected fakes, so nothing here touches the network or needs
Volatility3 installed. The identifier is the S3 guest's (docs/plans/m8-spikes/S3-findings.md).
"""

import io
import json
import lzma
import os
import stat
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fixtures.volatility_output import BANNER  # noqa: F401 - puts bin/ on sys.path
from symbols_logic import (
    FETCH_TIMEOUT_SECONDS,
    MAX_PDB_BYTES,
    ConversionFailedError,
    FetchFailedError,
    InvalidSymbolIdError,
    RestrictedRedirects,
    SymbolId,
    SymbolsNotWrittenError,
    SymbolStore,
    command_line,
    convert_with_volatility,
    ensure_symbols,
    fetch_from_symbol_server,
    symbols_response,
)
from volatility import VOLATILITY_PYTHON, CommandResult

GUID = "24DE61DB3A27C5B383DFF181CB51F7E1"
URL = f"https://msdl.microsoft.com/download/symbols/ntkrnlmp.pdb/{GUID}1/ntkrnlmp.pdb"
FILE_NAME = f"windows/ntkrnlmp-{GUID}1.json.xz"
PDB_BYTES = b"Microsoft C/C++ MSF 7.00" + b"\0" * 100


def isf_bytes(guid: str = GUID, age: int = 1, database: str = "ntkrnlmp.pdb") -> bytes:
    metadata = {"windows": {"pdb": {"GUID": guid, "age": age, "database": database}}}
    return lzma.compress(json.dumps({"metadata": metadata, "symbols": {}}).encode())


class FakeFetch:
    def __init__(self, body: bytes | Exception = PDB_BYTES) -> None:
        self.body = body
        self.calls: list[tuple[str, int, float]] = []

    def __call__(self, url: str, max_bytes: int, timeout: float) -> bytes:
        self.calls.append((url, max_bytes, timeout))
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeConvert:
    def __init__(self, output: bytes | Exception | None = None) -> None:
        self.output = isf_bytes() if output is None else output
        self.calls: list[tuple[bytes, Path]] = []

    def __call__(self, pdb: Path, output: Path) -> None:
        self.calls.append((pdb.read_bytes(), output))
        if isinstance(self.output, Exception):
            raise self.output
        output.write_bytes(self.output)


@pytest.fixture
def scratch(tmp_path, monkeypatch) -> Path:
    """Where the temporary files of a run go, so a test can see that none is left."""
    directory = tmp_path / "scratch"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    return directory


@pytest.fixture
def symbols_dir(tmp_path) -> Path:
    return tmp_path / "symbols"


def assert_nothing_left(symbols_dir: Path, scratch: Path) -> None:
    assert files_under(symbols_dir) == []
    assert files_under(scratch) == []


def files_under(directory: Path) -> list[str]:
    return sorted(
        str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()
    )


# identifier


def test_the_identifier_of_the_s3_guest_gives_its_url_and_file_name():
    symbol_id = SymbolId.parse(GUID, 1)

    assert symbol_id.url == URL
    assert symbol_id.file_name == FILE_NAME


def test_the_guid_is_upper_cased_whatever_case_it_came_in():
    assert SymbolId.parse(GUID.lower(), 1).guid == GUID
    assert SymbolId.parse(GUID.lower(), 1).url == URL


def test_the_age_is_hexadecimal_in_the_url_and_the_file_name_as_on_the_symbol_server():
    symbol_id = SymbolId.parse(GUID, 26)

    assert symbol_id.url.endswith(f"/{GUID}1A/ntkrnlmp.pdb")
    assert symbol_id.file_name == f"windows/ntkrnlmp-{GUID}1A.json.xz"


@pytest.mark.parametrize(("age", "value"), [(1, 1), ("1", 1), ("a", 10), ("0000000F", 15)])
def test_an_age_is_a_whole_number_or_hexadecimal_text(age, value):
    assert SymbolId.parse(GUID, age).age == value


@pytest.mark.parametrize(
    "guid",
    [
        GUID[:-1],
        GUID + "0",
        "G" * 32,
        "../" * 10 + "ab",
        f"{GUID[:8]}-{GUID[8:12]}-{GUID[12:16]}-{GUID[16:20]}-{GUID[20:]}",
        f"{{{GUID}}}",
        GUID + "\n",
        " " + GUID,
        f"{GUID[:30]}/.",
        "",
        None,
        123,
    ],
)
def test_a_guid_that_is_not_32_hexadecimal_digits_is_refused(guid):
    with pytest.raises(InvalidSymbolIdError, match="guid"):
        SymbolId.parse(guid, 1)


@pytest.mark.parametrize(
    "age",
    [0, -1, 0x1_0000_0000, "", "123456789", "xyz", "1/../", "1\n", " 1", True, 1.0, None, [1]],
)
def test_an_age_that_is_not_a_positive_32_bit_number_is_refused(age):
    with pytest.raises(InvalidSymbolIdError, match="age"):
        SymbolId.parse(GUID, age)


def test_nothing_of_the_input_but_hexadecimal_digits_can_reach_the_url_or_the_file_name():
    symbol_id = SymbolId.parse(GUID.lower(), "ff")

    assert symbol_id.url == (
        f"https://msdl.microsoft.com/download/symbols/ntkrnlmp.pdb/{GUID}FF/ntkrnlmp.pdb"
    )
    assert Path(symbol_id.file_name).parent == Path("windows")


# ensure_symbols


def test_a_missing_file_is_fetched_converted_and_written_where_volatility_looks(
    symbols_dir, scratch
):
    fetch, convert = FakeFetch(), FakeConvert()

    ensured = ensure_symbols(GUID, 1, symbols_dir, fetch, convert)

    assert ensured.created is True
    assert ensured.path == symbols_dir / FILE_NAME
    assert lzma.decompress(ensured.path.read_bytes()) == lzma.decompress(isf_bytes())
    assert fetch.calls == [(URL, MAX_PDB_BYTES, FETCH_TIMEOUT_SECONDS)]
    assert [pdb for pdb, _ in convert.calls] == [PDB_BYTES]


def test_the_symbol_file_is_readable_by_every_user_and_writable_only_by_its_owner(
    symbols_dir, scratch
):
    ensured = ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), FakeConvert())

    assert stat.S_IMODE(ensured.path.stat().st_mode) == 0o644
    assert stat.S_IMODE(ensured.path.parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(symbols_dir.stat().st_mode) == 0o755


def test_the_size_cap_is_fifty_megabytes():
    assert MAX_PDB_BYTES == 50 * 1024 * 1024


def test_a_valid_file_that_is_already_there_is_kept_and_nothing_is_fetched(symbols_dir, scratch):
    ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), FakeConvert())
    fetch, convert = FakeFetch(), FakeConvert()

    again = ensure_symbols(GUID.lower(), "1", symbols_dir, fetch, convert)

    assert again.created is False
    assert fetch.calls == []
    assert convert.calls == []


@pytest.mark.parametrize(
    "bad_content",
    [b"", b"not xz at all", lzma.compress(b"not json"), isf_bytes("F" * 32, 1), isf_bytes(age=2)],
    ids=["empty", "not-xz", "not-json", "other-guid", "other-age"],
)
def test_a_file_that_is_not_the_symbols_of_this_id_is_made_again(symbols_dir, scratch, bad_content):
    target = symbols_dir / FILE_NAME
    target.parent.mkdir(parents=True)
    target.write_bytes(bad_content)
    fetch = FakeFetch()

    ensured = ensure_symbols(GUID, 1, symbols_dir, fetch, FakeConvert())

    assert ensured.created is True
    assert len(fetch.calls) == 1
    assert lzma.decompress(target.read_bytes()) == lzma.decompress(isf_bytes())


def test_a_body_larger_than_the_cap_is_refused_even_if_the_fetcher_let_it_through(
    symbols_dir, scratch
):
    fetch = FakeFetch(b"x" * (MAX_PDB_BYTES + 1))
    convert = FakeConvert()

    with pytest.raises(FetchFailedError, match="larger than 50 MB"):
        ensure_symbols(GUID, 1, symbols_dir, fetch, convert)

    assert convert.calls == []
    assert_nothing_left(symbols_dir, scratch)


def test_an_empty_download_is_refused(symbols_dir, scratch):
    with pytest.raises(FetchFailedError, match="empty"):
        ensure_symbols(GUID, 1, symbols_dir, FakeFetch(b""), FakeConvert())


def test_a_failed_fetch_leaves_nothing_behind_and_says_why(symbols_dir, scratch):
    failure = FetchFailedError("the symbol server did not answer")
    convert = FakeConvert()

    with pytest.raises(FetchFailedError, match="did not answer"):
        ensure_symbols(GUID, 1, symbols_dir, FakeFetch(failure), convert)

    assert convert.calls == []
    assert_nothing_left(symbols_dir, scratch)


def test_a_failed_conversion_leaves_nothing_behind_and_says_why(symbols_dir, scratch):
    convert = FakeConvert(ConversionFailedError("volatility exited with status 1: boom"))

    with pytest.raises(ConversionFailedError, match="boom"):
        ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), convert)

    assert_nothing_left(symbols_dir, scratch)


def test_a_conversion_that_writes_nothing_is_a_failure(symbols_dir, scratch):
    class WritesNothing:
        def __call__(self, pdb: Path, output: Path) -> None:
            return None

    with pytest.raises(ConversionFailedError, match="no symbol file"):
        ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), WritesNothing())

    assert_nothing_left(symbols_dir, scratch)


@pytest.mark.parametrize(
    "wrong",
    [b"garbage", isf_bytes("0" * 32, 1), isf_bytes(age=7), isf_bytes(database="unknown.pdb")],
    ids=["garbage", "guid", "age", "database"],
)
def test_a_conversion_of_some_other_pdb_is_never_published(symbols_dir, scratch, wrong):
    with pytest.raises(ConversionFailedError, match="not the symbols of"):
        ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), FakeConvert(wrong))

    assert_nothing_left(symbols_dir, scratch)


def test_a_converter_that_leaves_a_link_to_another_file_is_never_followed(
    symbols_dir, scratch, tmp_path
):
    secret = tmp_path / "secret"
    secret.write_bytes(isf_bytes())

    class LeavesALink:
        def __call__(self, pdb: Path, output: Path) -> None:
            output.symlink_to(secret)

    with pytest.raises(ConversionFailedError, match="no symbol file"):
        ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), LeavesALink())

    assert_nothing_left(symbols_dir, scratch)


def test_a_conversion_that_expands_past_the_limit_is_refused_unread(
    symbols_dir, scratch, monkeypatch
):
    monkeypatch.setattr("symbols_logic.MAX_ISF_JSON_BYTES", 100)
    bomb = lzma.compress(b"0" * 10_000)

    with pytest.raises(ConversionFailedError, match="not the symbols of"):
        ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), FakeConvert(bomb))

    assert_nothing_left(symbols_dir, scratch)


def test_a_conversion_larger_than_the_file_limit_is_refused(symbols_dir, scratch, monkeypatch):
    monkeypatch.setattr("symbols_logic.MAX_ISF_BYTES", 10)

    with pytest.raises(ConversionFailedError, match="no symbol file"):
        ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), FakeConvert())

    assert_nothing_left(symbols_dir, scratch)


def test_the_file_appears_in_one_rename_after_the_conversion_finished(
    symbols_dir, scratch, monkeypatch
):
    seen: dict[str, object] = {}
    real_replace = os.replace

    def watching_replace(source, destination):
        seen["target_before"] = Path(destination).exists()
        seen["source_complete"] = lzma.decompress(Path(source).read_bytes()) is not None
        seen["same_directory"] = Path(source).parent == Path(destination).parent
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", watching_replace)

    ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), FakeConvert())

    assert seen == {"target_before": False, "source_complete": True, "same_directory": True}
    assert files_under(symbols_dir) == [FILE_NAME]


def test_a_conversion_in_progress_is_not_visible_under_the_name_volatility_reads(
    symbols_dir, scratch
):
    class LooksAround:
        def __call__(self, pdb: Path, output: Path) -> None:
            assert files_under(symbols_dir) == []
            output.write_bytes(isf_bytes())

    ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), LooksAround())


def test_a_rename_that_fails_leaves_nothing_and_is_a_typed_error(symbols_dir, scratch, monkeypatch):
    def refusing_replace(_source, _destination):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", refusing_replace)

    with pytest.raises(SymbolsNotWrittenError, match="could not be written"):
        ensure_symbols(GUID, 1, symbols_dir, FakeFetch(), FakeConvert())

    assert_nothing_left(symbols_dir, scratch)


def test_a_bad_id_is_refused_before_anything_is_fetched(symbols_dir):
    fetch = FakeFetch()

    with pytest.raises(InvalidSymbolIdError):
        ensure_symbols("../../etc/passwd", 1, symbols_dir, fetch, FakeConvert())

    assert fetch.calls == []
    assert not symbols_dir.exists()


# fetch_from_symbol_server


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_exception):
        self.read_up_to = self.tell()
        self.close()


class FakeOpener:
    def __init__(self, answer: FakeResponse | Exception) -> None:
        self.answer = answer
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout: float):
        self.calls.append((url, timeout))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_the_download_is_the_body_the_server_sent_asked_for_with_the_timeout():
    opener = FakeOpener(FakeResponse(PDB_BYTES))

    body = fetch_from_symbol_server(URL, 1000, 7.5, open_url=opener)

    assert body == PDB_BYTES
    assert opener.calls == [(URL, 7.5)]


@pytest.mark.parametrize(
    "url",
    [
        "http://msdl.microsoft.com/download/symbols/ntkrnlmp.pdb/X/ntkrnlmp.pdb",
        "https://evil.example.com/download/symbols/ntkrnlmp.pdb/X/ntkrnlmp.pdb",
        "https://msdl.microsoft.com.evil.example.com/download/symbols/x",
        "https://msdl.microsoft.com/other/path",
        "file:///etc/passwd",
        "ftp://msdl.microsoft.com/download/symbols/x",
    ],
)
def test_a_url_that_is_not_under_the_fixed_symbol_server_is_never_opened(url):
    opener = FakeOpener(FakeResponse(b"x"))

    with pytest.raises(FetchFailedError, match="symbol server"):
        fetch_from_symbol_server(url, 1000, 5, open_url=opener)

    assert opener.calls == []


def test_a_body_over_the_cap_is_refused_after_reading_one_byte_more_than_the_cap():
    response = FakeResponse(b"x" * 11)

    with pytest.raises(FetchFailedError, match="larger than"):
        fetch_from_symbol_server(URL, 10, 5, open_url=FakeOpener(response))

    assert response.read_up_to == 11


def test_a_body_of_exactly_the_cap_is_accepted():
    body = fetch_from_symbol_server(URL, 10, 5, open_url=FakeOpener(FakeResponse(b"x" * 10)))

    assert body == b"x" * 10


def test_a_declared_length_over_the_cap_is_refused_without_reading():
    response = FakeResponse(b"x", {"Content-Length": str(MAX_PDB_BYTES + 1)})

    with pytest.raises(FetchFailedError, match="larger than"):
        fetch_from_symbol_server(URL, MAX_PDB_BYTES, 5, open_url=FakeOpener(response))

    assert response.read_up_to == 0


def test_a_download_that_trickles_in_past_the_deadline_is_a_timeout():
    class Trickle(FakeResponse):
        def read(self, size=-1):
            return b"x"

    now = iter(range(0, 1000, 10))

    with pytest.raises(FetchFailedError, match=r"timed out after 25 s"):
        fetch_from_symbol_server(
            URL, MAX_PDB_BYTES, 25, open_url=FakeOpener(Trickle(b"")), clock=lambda: next(now)
        )


def test_the_server_not_having_the_pdb_says_so():
    error = urllib.error.HTTPError(URL, 404, "Not Found", {}, None)

    with pytest.raises(FetchFailedError, match=r"no PDB for this build.*404"):
        fetch_from_symbol_server(URL, 1000, 5, open_url=FakeOpener(error))


@pytest.mark.parametrize(
    "problem",
    [
        urllib.error.URLError("Temporary failure in name resolution"),
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
    ],
)
def test_a_network_failure_is_a_fetch_failure_naming_the_reason(problem):
    with pytest.raises(FetchFailedError, match="could not be reached"):
        fetch_from_symbol_server(URL, 1000, 5, open_url=FakeOpener(problem))


def test_a_download_cut_short_is_a_fetch_failure():
    class Cut(FakeResponse):
        def read(self, size=-1):
            raise ConnectionResetError("reset")

    with pytest.raises(FetchFailedError, match="could not be reached"):
        fetch_from_symbol_server(URL, 1000, 5, open_url=FakeOpener(Cut(b"x")))


# the redirect policy of the real opener


def redirect(location: str):
    request = urllib.request.Request(URL)
    return RestrictedRedirects().redirect_request(request, None, 302, "Found", {}, location)


@pytest.mark.parametrize(
    "location",
    [
        "https://vsblobprodscussu5shard12.blob.core.windows.net/b-1234/abcd.blob?sv=2020&sig=x",
        "https://msdl.microsoft.com/download/symbols/ntkrnlmp.pdb/X/ntkrnlmp.pdb",
        "https://symbols.microsoft.com/x",
    ],
)
def test_a_redirect_within_microsofts_hosts_is_followed(location):
    assert redirect(location).full_url == location


@pytest.mark.parametrize(
    "location",
    [
        "http://msdl.microsoft.com/x",
        "https://evil.example.com/x",
        "https://microsoft.com.evil.example.com/x",
        "https://evilblob.core.windows.net.example.com/x",
        "https://notmicrosoft.com/x",
        "https://user@evil.example.com/x",
        "file:///etc/passwd",
        "ftp://msdl.microsoft.com/x",
    ],
)
def test_a_redirect_anywhere_else_is_refused_with_the_host_named(location):
    with pytest.raises(FetchFailedError, match="redirected"):
        redirect(location)


# the real converter


class FakeRunner:
    def __init__(self, result: CommandResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, command, timeout):
        self.calls.append((list(command), timeout))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def convert(tmp_path, runner, hand_over=None):
    handed: list[Path] = []
    hand = handed.append if hand_over is None else hand_over
    pdb, output = tmp_path / "ntkrnlmp.pdb", tmp_path / "isf.json.xz"
    pdb.write_bytes(PDB_BYTES)
    convert_with_volatility(pdb, output, run=runner, hand_over=hand)
    return pdb, output, handed


def test_volatilitys_own_converter_runs_on_the_local_pdb_and_names_it_ntkrnlmp(tmp_path):
    runner = FakeRunner(CommandResult(0, "", ""))

    pdb, output, handed = convert(tmp_path, runner)

    command, timeout = runner.calls[0]
    assert command == [
        VOLATILITY_PYTHON,
        "-m",
        "volatility3.framework.symbols.windows.pdbconv",
        "--file",
        str(pdb),
        "--pattern",
        "ntkrnlmp.pdb",
        "--output",
        str(output),
    ]
    assert timeout > 0
    # So `cape`, which runs it, can read the PDB and write the result.
    assert handed == [tmp_path]


def test_the_converter_never_asks_volatility_to_download_anything(tmp_path):
    runner = FakeRunner(CommandResult(0, "", ""))

    convert(tmp_path, runner)

    command = runner.calls[0][0]
    assert "--guid" not in command
    assert "-g" not in command


def test_a_converter_that_exits_with_an_error_names_its_last_line(tmp_path):
    runner = FakeRunner(
        CommandResult(1, "", "Traceback\nValueError: No PDB Info Stream available\n")
    )

    with pytest.raises(ConversionFailedError, match=r"status 1.*No PDB Info Stream available"):
        convert(tmp_path, runner)


def test_a_converter_that_runs_too_long_is_a_timeout(tmp_path):
    runner = FakeRunner(CommandResult(-9, "", "", timed_out=True))

    with pytest.raises(ConversionFailedError, match="timed out"):
        convert(tmp_path, runner)


def test_a_converter_that_cannot_be_started_is_a_conversion_failure(tmp_path):
    runner = FakeRunner(FileNotFoundError(2, "No such file"))

    with pytest.raises(ConversionFailedError, match="could not be started"):
        convert(tmp_path, runner)


def test_a_work_folder_that_cannot_be_handed_over_is_a_conversion_failure(tmp_path):
    def cannot(_path):
        raise PermissionError(1, "Operation not permitted")

    with pytest.raises(ConversionFailedError, match="could not be prepared"):
        convert(tmp_path, FakeRunner(CommandResult(0, "", "")), hand_over=cannot)


# the store and the route's answer


@pytest.fixture
def store(symbols_dir, scratch) -> SymbolStore:
    return SymbolStore(symbols_dir, FakeFetch(), FakeConvert())


def test_a_request_for_a_new_id_answers_200_with_the_file_and_created(store):
    assert symbols_response({"guid": GUID, "age": 1}, store) == (
        200,
        {"file": FILE_NAME, "created": True},
    )


def test_the_same_request_again_answers_created_false(store):
    symbols_response({"guid": GUID, "age": 1}, store)

    assert symbols_response({"guid": GUID, "age": 1}, store) == (
        200,
        {"file": FILE_NAME, "created": False},
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"guid": GUID},
        {"age": 1},
        {"guid": "../x", "age": 1},
        {"guid": GUID, "age": "zz"},
        {"guid": GUID, "age": 1, "url": "https://evil.example.com/x"},
    ],
)
def test_a_body_that_is_not_exactly_a_valid_id_answers_400(store, body):
    status, answer = symbols_response(body, store)

    assert status == 400
    assert answer["error"]
    assert store.fetch.calls == []


def test_a_fetch_that_fails_answers_502_with_its_message(symbols_dir, scratch):
    store = SymbolStore(symbols_dir, FakeFetch(FetchFailedError("no network")), FakeConvert())

    assert symbols_response({"guid": GUID, "age": 1}, store) == (502, {"error": "no network"})


def test_a_conversion_that_fails_answers_502_with_its_message(symbols_dir, scratch):
    store = SymbolStore(symbols_dir, FakeFetch(), FakeConvert(ConversionFailedError("boom")))

    assert symbols_response({"guid": GUID, "age": 1}, store) == (502, {"error": "boom"})


# the command line the build step runs


def test_the_command_line_says_what_it_made_and_exits_zero(store):
    assert command_line(["ensure", GUID, "1"], store) == (
        0,
        f"symbols: ready {FILE_NAME} (created)",
    )


def test_the_command_line_says_when_the_file_was_already_there(store):
    command_line(["ensure", GUID, "1"], store)

    assert command_line(["ensure", GUID.lower(), "1"], store) == (
        0,
        f"symbols: ready {FILE_NAME} (already present)",
    )


def test_the_age_on_the_command_line_is_decimal_as_the_pe_header_and_volatility_print_it(
    symbols_dir, scratch
):
    store = SymbolStore(symbols_dir, FakeFetch(), FakeConvert(isf_bytes(age=10)))

    status, line = command_line(["ensure", GUID, "10"], store)

    assert status == 0
    assert f"ntkrnlmp-{GUID}A.json.xz" in line


def test_a_failure_is_the_line_the_build_logs_and_a_nonzero_exit(symbols_dir, scratch):
    store = SymbolStore(symbols_dir, FakeFetch(FetchFailedError("no network")), FakeConvert())

    assert command_line(["ensure", GUID, "1"], store) == (1, "symbols: unavailable (no network)")


@pytest.mark.parametrize(
    "argv",
    [[], ["ensure"], ["ensure", GUID], ["ensure", GUID, "1", "2"], ["fetch", GUID, "1"]],
)
def test_a_command_line_of_the_wrong_shape_exits_two_with_the_usage(store, argv):
    status, line = command_line(argv, store)

    assert status == 2
    assert "usage: guest-symbols ensure GUID AGE" in line


@pytest.mark.parametrize("guid_and_age", [("../x", "1"), (GUID, "0"), (GUID, "abc"), (GUID, "-1")])
def test_a_bad_id_on_the_command_line_exits_two_and_fetches_nothing(store, guid_and_age):
    status, line = command_line(["ensure", *guid_and_age], store)

    assert status == 2
    assert line.startswith("symbols: unavailable (")
    assert store.fetch.calls == []
