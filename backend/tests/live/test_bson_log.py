import random
import struct
from bisect import bisect_right
from typing import Any

import pytest

from app.live.bson_log import (
    MAX_MESSAGE_SIZE,
    BsonLogParser,
    CallRecord,
    EnvironRecord,
    LogFormatError,
    LogRecord,
    ProcessRecord,
    ThreadRecord,
    UnknownRecord,
)
from tests.live.bson_encode import Binary, encode_document
from tests.live.conftest import PIDS


def parse_whole(data: bytes) -> list[LogRecord]:
    return BsonLogParser().feed(data)


def calls_in(records: list[LogRecord]) -> list[CallRecord]:
    return [record for record in records if isinstance(record, CallRecord)]


def record_boundaries(data: bytes) -> list[int]:
    offsets, position = [0], 0
    while position < len(data):
        position += struct.unpack_from("<I", data, position)[0]
        offsets.append(position)
    return offsets


@pytest.mark.parametrize("pid", PIDS)
def test_calls_equal_the_ones_cape_reported(
    pid: int, log_bytes: dict[int, bytes], report_processes: dict[int, dict[str, Any]]
) -> None:
    calls = calls_in(parse_whole(log_bytes[pid]))
    expected = report_processes[pid]["calls"]

    assert len(calls) == len(expected)
    for call, reported in zip(calls, expected, strict=True):
        assert call.index == reported["id"]
        assert call.api == reported["api"]
        assert call.category == reported["category"]
        assert call.status == reported["status"]
        assert call.return_value == reported["return"]
        assert call.repeated == reported["repeated"]
        assert str(call.thread_id) == reported["thread_id"]
        assert call.caller == reported["caller"]
        assert call.parent_caller == reported["parentcaller"]
        assert call.timestamp_text == reported["timestamp"]
        assert [(a.name, a.value) for a in call.arguments] == [
            (a["name"], a["value"]) for a in reported["arguments"]
        ]


@pytest.mark.parametrize("pid", PIDS)
def test_process_record_equals_the_reported_process(
    pid: int, log_bytes: dict[int, bytes], report_processes: dict[int, dict[str, Any]]
) -> None:
    processes = [r for r in parse_whole(log_bytes[pid]) if isinstance(r, ProcessRecord)]
    reported = report_processes[pid]

    assert len(processes) == 1
    assert processes[0].pid == reported["process_id"]
    assert processes[0].name == reported["process_name"]
    assert processes[0].module_path == reported["module_path"]
    assert processes[0].parent_pid == reported["parent_id"]
    assert processes[0].first_seen_text == reported["first_seen"]


@pytest.mark.parametrize("pid", PIDS)
def test_timestamps_are_wall_times_with_the_calls_offset_from_the_process_start(
    pid: int, log_bytes: dict[int, bytes], report_processes: dict[int, dict[str, Any]]
) -> None:
    records = parse_whole(log_bytes[pid])
    process = next(r for r in records if isinstance(r, ProcessRecord))
    first_call = calls_in(records)[0]

    assert process.first_seen.tzinfo is None
    assert first_call.timestamp.tzinfo is None
    assert first_call.timestamp >= process.first_seen
    assert (
        first_call.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        == (report_processes[pid]["calls"][0]["timestamp"][:19])
    )


@pytest.mark.parametrize("pid", PIDS)
def test_thread_and_environment_records_come_through(pid: int, log_bytes: dict[int, bytes]) -> None:
    records = parse_whole(log_bytes[pid])
    threads = [r for r in records if isinstance(r, ThreadRecord)]
    environments = [r for r in records if isinstance(r, EnvironRecord)]

    assert [t.pid for t in threads] == [pid]
    assert len(environments) == 1
    assert "CommandLine" in environments[0].values


@pytest.mark.parametrize("pid", PIDS)
def test_no_message_of_the_real_logs_is_unknown(pid: int, log_bytes: dict[int, bytes]) -> None:
    assert not [r for r in parse_whole(log_bytes[pid]) if isinstance(r, UnknownRecord)]


@pytest.mark.parametrize("pid", PIDS)
def test_one_byte_chunks_give_the_same_records(pid: int, log_bytes: dict[int, bytes]) -> None:
    data = log_bytes[pid]
    parser = BsonLogParser()
    records: list[LogRecord] = []
    for i in range(len(data)):
        records.extend(parser.feed(data[i : i + 1]))

    assert records == parse_whole(data)
    assert parser.pending_bytes == 0


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("pid", PIDS)
def test_random_chunk_sizes_give_the_same_records(
    pid: int, seed: int, log_bytes: dict[int, bytes]
) -> None:
    data = log_bytes[pid]
    chooser = random.Random(seed)  # noqa: S311
    parser = BsonLogParser()
    records: list[LogRecord] = []
    position = 0
    while position < len(data):
        size = chooser.choice([1, 2, 3, 5, 17, 100, 1000, 8192])
        records.extend(parser.feed(data[position : position + size]))
        position += size

    assert records == parse_whole(data)


@pytest.mark.parametrize("pid", PIDS)
def test_chunks_splitting_inside_a_length_prefix_give_the_same_records(
    pid: int, log_bytes: dict[int, bytes]
) -> None:
    data = log_bytes[pid]
    expected = parse_whole(data)
    for boundary in record_boundaries(data)[:-1][:40]:
        for inside in (1, 2, 3):
            parser = BsonLogParser()
            records = parser.feed(data[: boundary + inside]) + parser.feed(
                data[boundary + inside :]
            )
            assert records == expected


@pytest.mark.parametrize("pid", PIDS)
def test_stopping_at_every_offset_never_raises_and_yields_a_prefix(
    pid: int, log_bytes: dict[int, bytes]
) -> None:
    data = log_bytes[pid]
    full = parse_whole(data)
    boundaries = record_boundaries(data)
    parser = BsonLogParser()
    seen: list[LogRecord] = []
    for cut in range(1, len(data) + 1):
        arrived = parser.feed(data[cut - 1 : cut])
        assert arrived == full[len(seen) : len(seen) + len(arrived)]
        seen.extend(arrived)
        assert parser.pending_bytes == cut - boundaries[bisect_right(boundaries, cut) - 1]
    assert seen == full


@pytest.mark.parametrize("pid", PIDS)
def test_a_fresh_parser_at_sampled_cuts_waits_then_completes(
    pid: int, log_bytes: dict[int, bytes]
) -> None:
    data = log_bytes[pid]
    full = parse_whole(data)
    cuts = random.Random(7).sample(range(len(data) + 1), 150)  # noqa: S311

    for cut in cuts:
        parser = BsonLogParser()
        head = parser.feed(data[:cut])
        assert head == full[: len(head)]
        assert head + parser.feed(data[cut:]) == full


def test_empty_input_yields_nothing() -> None:
    parser = BsonLogParser()

    assert parser.feed(b"") == []
    assert parser.pending_bytes == 0


def test_info_messages_alone_yield_no_calls(log_bytes: dict[int, bytes]) -> None:
    data = log_bytes[9708]
    boundaries = record_boundaries(data)
    parser = BsonLogParser()

    records = parser.feed(data[: boundaries[1]])

    assert calls_in(records) == []
    assert parser.pending_bytes == 0


def test_a_partial_record_is_held_back(log_bytes: dict[int, bytes]) -> None:
    data = log_bytes[9708]
    parser = BsonLogParser()

    assert parser.feed(data[:3]) == []
    assert parser.pending_bytes == 3
    assert parser.feed(data[3:50]) == []
    assert parser.pending_bytes == 50


def make_info(index: int, name: str, args: list[Any], category: str | None = "misc") -> bytes:
    document: dict[str, Any] = {"I": index, "name": name, "type": "info", "args": args}
    if category is not None:
        document["category"] = category
    return encode_document(document)


def make_call(index: int, args: list[Any], **fields: Any) -> bytes:
    defaults: dict[str, Any] = {"I": index, "T": 100, "t": 0, "R": 0, "P": 0, "r": 0, "args": args}
    return encode_document(defaults | fields)


def process_record_bytes(first_low: int = 1375613491, first_high: int = 31283992) -> bytes:
    return make_info(
        0,
        "__process__",
        [
            "is_success",
            "retval",
            "TimeLow",
            "TimeHigh",
            "ProcessIdentifier",
            "ParentProcessIdentifier",
            "ModulePath",
        ],
        "__notification__",
    ) + make_call(0, [1, 0, first_low, first_high, 4242, 1, Binary(b"C:\\Temp\\a.exe")])


def test_unknown_message_type_becomes_an_unknown_record_and_parsing_continues() -> None:
    debug = encode_document({"type": "debug", "msg": "hello"})
    data = (
        process_record_bytes()
        + make_info(5, "Api", ["is_success", "retval"])
        + debug
        + make_call(5, [1, 0])
    )

    records = parse_whole(data)

    unknown = [r for r in records if isinstance(r, UnknownRecord)]
    assert [(u.kind, u.document["msg"]) for u in unknown] == [("debug", "hello")]
    assert len(calls_in(records)) == 1


def test_call_with_unexplained_index_becomes_an_unknown_record() -> None:
    records = parse_whole(process_record_bytes() + make_call(77, [1, 0]))

    unknown = [r for r in records if isinstance(r, UnknownRecord)]
    assert len(unknown) == 1
    assert "77" in unknown[0].reason


def test_call_with_wrong_argument_count_becomes_an_unknown_record() -> None:
    data = process_record_bytes() + make_info(5, "Api", ["is_success", "retval", "A"])

    records = parse_whole(data + make_call(5, [1, 0]))

    assert [type(r) for r in records if isinstance(r, UnknownRecord)] == [UnknownRecord]
    assert calls_in(records) == []


def test_call_before_any_process_record_becomes_an_unknown_record() -> None:
    records = parse_whole(make_info(5, "Api", ["is_success", "retval"]) + make_call(5, [1, 0]))

    assert calls_in(records) == []
    assert len([r for r in records if isinstance(r, UnknownRecord)]) == 1


def test_status_return_and_typed_arguments_follow_the_reports_rules() -> None:
    data = process_record_bytes() + make_info(
        5,
        "NtOpenKey",
        ["is_success", "retval", ["KeyHandle", "p"], ["Access", "h"], "Name", "N"],
        "registry",
    )
    data += make_call(
        5,
        [0, -1073741772, 0x22C, 1, Binary(b"\\Registry\\a\x00"), -1],
        T=77,
        t=329,
        R=0x7FFD9FE38838,
        P=3,
        r=2,
    )

    call = calls_in(parse_whole(data))[0]

    assert call.status is False
    assert call.return_value == "0xffffffffc0000034"
    assert call.category == "registry"
    assert call.thread_id == 77
    assert call.caller == "0x7ffd9fe38838"
    assert call.parent_caller == "0x00000003"
    assert call.repeated == 2
    assert [(a.name, a.value, a.tag) for a in call.arguments] == [
        ("KeyHandle", "0x0000022c", "p"),
        ("Access", "0x00000001", "h"),
        ("Name", "\\Registry\\a\\x00", None),
        ("N", "18446744073709551615", None),
    ]
    assert call.timestamp_text.endswith(",722")
    assert call.index == 0


def test_call_indices_count_calls_only_not_special_messages() -> None:
    data = process_record_bytes() + make_info(5, "Api", ["is_success", "retval"])
    data += make_call(5, [1, 0]) + make_call(5, [1, 0]) + make_call(5, [1, 0])

    assert [c.index for c in calls_in(parse_whole(data))] == [0, 1, 2]


def test_missing_category_is_unknown_and_a_second_info_replaces_the_first() -> None:
    data = process_record_bytes() + make_info(5, "First", ["is_success", "retval"], None)
    data += make_call(5, [1, 0]) + make_info(5, "Second", ["is_success", "retval"], "network")
    data += make_call(5, [1, 0])

    first, second = calls_in(parse_whole(data))

    assert (first.api, first.category) == ("First", "unknown")
    assert (second.api, second.category) == ("Second", "network")


def test_auxiliary_values_follow_the_arguments() -> None:
    data = process_record_bytes() + make_info(5, "Api", ["is_success", "retval", "A"])
    data += make_call(5, [1, 0, 9], aux={"Extra": Binary(b"x")})

    call = calls_in(parse_whole(data))[0]

    assert [(a.name, a.value) for a in call.arguments] == [("A", "9"), ("Extra", "x")]


def test_a_second_process_record_moves_the_clock_base() -> None:
    data = process_record_bytes() + make_info(5, "Api", ["is_success", "retval"])
    data += (
        make_call(5, [1, 0], t=1000)
        + process_record_bytes(1375613491 + 20_000_000)
        + make_call(5, [1, 0], t=0)
    )

    first, second = calls_in(parse_whole(data))

    assert (second.timestamp - first.timestamp).total_seconds() == pytest.approx(1.0)


def test_bad_length_after_a_valid_prefix_raises_with_the_offset() -> None:
    prefix = process_record_bytes()
    parser = BsonLogParser()

    with pytest.raises(LogFormatError) as caught:
        parser.feed(prefix + struct.pack("<I", 3) + b"\x00" * 10)

    assert caught.value.offset == len(prefix)
    assert [type(r) for r in caught.value.parsed][:1] == [ProcessRecord]


def test_garbage_after_a_valid_prefix_raises_with_the_offset() -> None:
    prefix = process_record_bytes()
    garbage = struct.pack("<I", 20) + b"\x7fnot-bson-at-all"

    with pytest.raises(LogFormatError) as caught:
        BsonLogParser().feed(prefix + garbage)

    assert caught.value.offset == len(prefix)


def test_text_where_a_length_belongs_is_reported_as_oversize() -> None:
    with pytest.raises(LogFormatError) as caught:
        BsonLogParser().feed(b"this is not a bson log at all")

    assert caught.value.offset == 0


def test_oversize_length_is_rejected_as_soon_as_the_prefix_arrives() -> None:
    with pytest.raises(LogFormatError) as caught:
        BsonLogParser().feed(struct.pack("<I", MAX_MESSAGE_SIZE + 1))

    assert caught.value.offset == 0


def test_a_message_of_exactly_the_maximum_size_is_waited_for() -> None:
    parser = BsonLogParser()

    assert parser.feed(struct.pack("<I", MAX_MESSAGE_SIZE)) == []
    assert parser.pending_bytes == 4


def test_the_offset_counts_bytes_across_feeds() -> None:
    prefix = process_record_bytes()
    parser = BsonLogParser()
    parser.feed(prefix)

    with pytest.raises(LogFormatError) as caught:
        parser.feed(struct.pack("<I", 2))

    assert caught.value.offset == len(prefix)


def test_the_parser_is_unusable_after_an_error() -> None:
    parser = BsonLogParser()
    with pytest.raises(LogFormatError) as first:
        parser.feed(struct.pack("<I", 2))

    with pytest.raises(LogFormatError) as again:
        parser.feed(process_record_bytes())
    with pytest.raises(LogFormatError):
        parser.feed(b"")

    assert again.value is first.value


def test_a_message_that_is_not_valid_bson_inside_its_length_raises() -> None:
    element = b"\x7fx\x00"
    broken = struct.pack("<I", len(element) + 5) + element + b"\x00"

    with pytest.raises(LogFormatError) as caught:
        BsonLogParser().feed(broken)

    assert caught.value.offset == 0
