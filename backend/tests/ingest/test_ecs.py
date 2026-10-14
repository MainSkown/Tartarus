import hashlib
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.ingest.ecs import (
    EventFactory,
    EventShape,
    ProcessIdentity,
    SourceRecord,
    event_id,
    file_fields,
    format_timestamp,
    process_entity_id,
    process_fields,
    registry_fields,
    related_events,
    severity_level,
)
from app.ingest.protocol import IngestContext

NOON = datetime(2026, 10, 13, 12, 0, 0, 123000, tzinfo=UTC)
FILE_WRITTEN = EventShape(
    action="file-written",
    categories=("file",),
    types=("change",),
    lane="file",
    dataset="capemon.derived",
)


def test_event_id_is_the_sha1_of_the_identifying_tuple() -> None:
    expected = hashlib.sha1(b"6|capemon|report.json|12", usedforsecurity=False).hexdigest()
    assert event_id(6, "capemon", "report.json", 12) == expected


def test_event_id_changes_with_every_component() -> None:
    base = event_id(6, "capemon", "report.json", 12)
    assert {
        event_id(7, "capemon", "report.json", 12),
        event_id(6, "sysmon", "report.json", 12),
        event_id(6, "capemon", "other.json", 12),
        event_id(6, "capemon", "report.json", 13),
    }.isdisjoint({base})


def test_event_id_does_not_confuse_adjacent_components() -> None:
    assert event_id(1, "ab", "c", 2) != event_id(1, "a", "bc", 2)


def test_timestamp_is_utc_with_milliseconds() -> None:
    assert format_timestamp(NOON) == "2026-10-13T12:00:00.123Z"


def test_timestamp_converts_an_offset_datetime_to_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    assert format_timestamp(datetime(2026, 10, 13, 14, 0, tzinfo=plus_two)) == (
        "2026-10-13T12:00:00.000Z"
    )


def test_timestamp_refuses_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone"):
        format_timestamp(datetime(2026, 10, 13, 12, 0))


def test_process_entity_id_includes_the_start_time() -> None:
    assert process_entity_id(6, 9632, NOON) == "6:9632@2026-10-13T12:00:00.123Z"


def test_process_entity_id_without_a_start_time_is_the_pid_alone() -> None:
    assert process_entity_id(6, 9632, None) == "6:9632"


@pytest.mark.parametrize(
    ("cape_severity", "expected"),
    [(1, 1), (2, 2), (3, 3), (4, 4), (9, 4), (0, 0), (-1, 0), (None, 0), ("x", 0), (True, 0)],
)
def test_severity_level_maps_cape_scale_to_event_severity(
    cape_severity: object, expected: int
) -> None:
    assert severity_level(cape_severity) == expected


def test_related_events_lists_the_ids() -> None:
    assert related_events("a", "b") == {"events": ["a", "b"]}


def test_file_fields_split_a_windows_path() -> None:
    assert file_fields("C:\\Users\\Analyst\\Temp\\Dropper.EXE") == {
        "path": "C:\\Users\\Analyst\\Temp\\Dropper.EXE",
        "name": "Dropper.EXE",
        "extension": "exe",
    }


def test_file_fields_without_extension_omit_it() -> None:
    assert "extension" not in file_fields("C:\\Windows\\hosts")
    assert "extension" not in file_fields("C:\\Windows\\trailing.")


def test_file_fields_carry_the_target_path_of_a_move() -> None:
    assert file_fields("C:\\a.txt", target_path="C:\\b.txt")["target_path"] == "C:\\b.txt"


def test_registry_fields_split_hive_key_and_value() -> None:
    fields = registry_fields(
        "HKEY_CURRENT_USER\\Software\\Tartarus\\SelfTest",
        value_name="SelfTest",
        data_type="REG_SZ",
        data="benign",
    )
    assert fields == {
        "path": "HKEY_CURRENT_USER\\Software\\Tartarus\\SelfTest",
        "hive": "HKCU",
        "key": "Software\\Tartarus",
        "value": "SelfTest",
        "data": {"type": "REG_SZ", "strings": ["benign"]},
    }


def test_registry_fields_for_a_key_have_no_value() -> None:
    fields = registry_fields("HKEY_LOCAL_MACHINE\\SOFTWARE\\Run")
    assert fields == {
        "path": "HKEY_LOCAL_MACHINE\\SOFTWARE\\Run",
        "hive": "HKLM",
        "key": "SOFTWARE\\Run",
    }


def test_registry_fields_keep_an_unknown_hive_as_given() -> None:
    fields = registry_fields("HKEY_ODD\\Key")
    assert (fields["hive"], fields["key"]) == ("HKEY_ODD", "Key")


def test_process_fields_describe_the_process_and_its_parent() -> None:
    identity = ProcessIdentity(
        pid=9632,
        parent_pid=10116,
        name="cmd.exe",
        executable="C:\\Windows\\System32\\cmd.exe",
        command_line="cmd.exe /c ver",
        start=NOON,
        parent_name="benign.exe",
    )
    assert process_fields(identity, analysis_id=6, thread_id=9616) == {
        "pid": 9632,
        "name": "cmd.exe",
        "executable": "C:\\Windows\\System32\\cmd.exe",
        "command_line": "cmd.exe /c ver",
        "entity_id": "6:9632@2026-10-13T12:00:00.123Z",
        "start": "2026-10-13T12:00:00.123Z",
        "parent": {"pid": 10116, "name": "benign.exe"},
        "thread": {"id": 9616},
    }


def test_process_fields_give_the_parent_its_path_and_command_line() -> None:
    identity = ProcessIdentity(
        pid=9632,
        parent_pid=10116,
        parent_name="benign.exe",
        parent_executable="C:\\Temp\\benign.exe",
        parent_command_line="benign.exe --go",
    )
    assert process_fields(identity, analysis_id=6)["parent"] == {
        "pid": 10116,
        "name": "benign.exe",
        "executable": "C:\\Temp\\benign.exe",
        "command_line": "benign.exe --go",
    }


def test_process_fields_omit_what_is_unknown() -> None:
    assert process_fields(ProcessIdentity(pid=7), analysis_id=6) == {
        "pid": 7,
        "entity_id": "6:7",
    }


@pytest.fixture
def factory() -> EventFactory:
    context = IngestContext(analysis_id=6, started_at=NOON)
    return EventFactory(context, source="capemon", source_file="report.json", module="capemon")


def build(factory: EventFactory, index: int = 0, **sections: object) -> dict[str, object]:
    record = SourceRecord(index=index, timestamp=NOON, raw={"api": "NtWriteFile"})
    return factory.build(FILE_WRITTEN, record, "cmd.exe wrote a.txt", **sections)


def test_factory_fills_the_common_fields(factory: EventFactory) -> None:
    event = build(factory, 5)
    assert event == {
        "@timestamp": "2026-10-13T12:00:00.123Z",
        "event": {
            "id": event_id(6, "capemon", "report.json", 5),
            "sequence": 0,
            "kind": "event",
            "category": ["file"],
            "type": ["change"],
            "action": "file-written",
            "module": "capemon",
            "dataset": "capemon.derived",
            "severity": 0,
        },
        "tartarus": {
            "analysis_id": 6,
            "lane": "file",
            "phase": "final",
            "summary": "cmd.exe wrote a.txt",
            "raw": {"api": "NtWriteFile"},
        },
    }


def test_a_live_factory_marks_its_events_live() -> None:
    context = IngestContext(analysis_id=6, started_at=NOON)
    live = EventFactory(
        context, source="capemon", source_file="report.json", module="capemon", phase="live"
    )
    assert build(live)["tartarus"]["phase"] == "live"  # type: ignore[index]


def test_a_record_can_come_from_another_file_of_the_same_source(factory: EventFactory) -> None:
    same = factory.build(FILE_WRITTEN, SourceRecord(1, NOON, {}), "a")
    other = factory.build(FILE_WRITTEN, SourceRecord(1, NOON, {}, source_file="derived"), "a")
    assert other["event"]["id"] == event_id(6, "capemon", "derived", 1)
    assert other["event"]["id"] != same["event"]["id"]


def test_factory_numbers_events_in_the_order_they_are_built(factory: EventFactory) -> None:
    sequences = [build(factory, index)["event"]["sequence"] for index in range(3)]  # type: ignore[index]
    assert sequences == [0, 1, 2]


def test_factory_adds_sections_beside_the_common_fields(factory: EventFactory) -> None:
    event = build(factory, file={"path": "C:\\a.txt"})
    assert event["file"] == {"path": "C:\\a.txt"}


def test_factory_does_not_let_a_section_overwrite_the_common_fields(factory: EventFactory) -> None:
    with pytest.raises(ValueError, match="event"):
        build(factory, event={"id": "forged"})


def test_factory_merges_extra_tartarus_fields_beside_the_common_ones(
    factory: EventFactory,
) -> None:
    record = SourceRecord(index=0, timestamp=NOON, raw={})
    event = factory.build(FILE_WRITTEN, record, "x", tartarus={"inject": {"target_pid": 4242}})
    assert event["tartarus"]["inject"] == {"target_pid": 4242}  # type: ignore[index]
    assert event["tartarus"]["lane"] == "file"  # type: ignore[index]


@pytest.mark.parametrize("common", ["analysis_id", "lane", "phase", "summary", "raw"])
def test_extra_tartarus_fields_cannot_overwrite_a_common_one(
    factory: EventFactory, common: str
) -> None:
    record = SourceRecord(index=0, timestamp=NOON, raw={})
    with pytest.raises(ValueError, match=common):
        factory.build(FILE_WRITTEN, record, "x", tartarus={common: "forged"})


def test_factory_alerts_carry_kind_and_severity(factory: EventFactory) -> None:
    alert = EventShape(
        action="signature-hit",
        categories=("malware",),
        types=("indicator",),
        lane="process",
        dataset="cape.signature",
        kind="alert",
    )
    record = SourceRecord(index=1, timestamp=NOON, raw={})
    event = factory.build(alert, record, "hit", severity=3)
    assert (event["event"]["kind"], event["event"]["severity"]) == ("alert", 3)  # type: ignore[index]


def test_event_shape_refuses_an_unknown_lane() -> None:
    with pytest.raises(ValueError, match="lane"):
        EventShape(
            action="x", categories=("file",), types=("info",), lane="disk", dataset="capemon.x"
        )
