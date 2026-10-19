from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.ingest import windows_events
from app.ingest.windows_events import WindowsEvent, read_windows_events

FIXTURES = Path(__file__).parent.parent / "fixtures" / "windows_events"
DEFENDER = FIXTURES / "defender-eicar-sample.xml"
SYSMON_FIRST_20 = FIXTURES / "sysmon-first-20.xml"

NS = "http://schemas.microsoft.com/win/2004/08/events/event"


def write_xml(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "events.xml"
    path.write_text(body, encoding="utf-8")
    return path


def event_xml(
    event_id: str = "1",
    record_id: str = "7",
    time: str = "2026-10-18T20:46:51.5Z",
    data: str = "<Data Name='Key'>value</Data>",
) -> str:
    return (
        f"<Event xmlns='{NS}'><System><EventID>{event_id}</EventID>"
        f"<TimeCreated SystemTime='{time}'/><EventRecordID>{record_id}</EventRecordID>"
        f"</System><EventData>{data}</EventData></Event>"
    )


def wrap(*events: str) -> str:
    return "<Events>\n" + "\n".join(events) + "\n</Events>\n"


def test_missing_file_yields_nothing(tmp_path: Path) -> None:
    assert list(read_windows_events(tmp_path / "absent.xml")) == []


def test_directory_path_yields_nothing(tmp_path: Path) -> None:
    assert list(read_windows_events(tmp_path)) == []


def test_empty_events_wrapper_yields_nothing(tmp_path: Path) -> None:
    path = write_xml(tmp_path, "<Events>\n</Events>\n")

    assert list(read_windows_events(path)) == []


def test_defender_fixture_yields_every_event_in_file_order() -> None:
    event_ids = [event.event_id for event in read_windows_events(DEFENDER)]

    assert event_ids == [1116, 5007, 5007, 5007, 1116, 1117, 1117, 5007]


def test_first_defender_event_carries_system_fields_and_event_data() -> None:
    first = next(iter(read_windows_events(DEFENDER)))

    assert first.event_id == 1116
    assert first.record_id == 271
    assert first.system_time == datetime(2026, 10, 18, 21, 9, 42, 109625, tzinfo=UTC)
    assert first.data["Threat Name"] == "HackTool:Win32/PDump.A"


def test_seven_digit_fraction_is_truncated_to_microseconds() -> None:
    first = next(iter(read_windows_events(DEFENDER)))

    assert first.system_time is not None
    assert first.system_time.microsecond == 109625


def test_xml_entity_in_data_is_decoded() -> None:
    first = next(iter(read_windows_events(DEFENDER)))

    assert first.data["FWLink"] == (
        "https://go.microsoft.com/fwlink/?linkid=37020"
        "&name=HackTool:Win32/PDump.A&threatid=2147826620&enterprise=0"
    )


def test_empty_data_text_becomes_empty_string() -> None:
    first = next(iter(read_windows_events(DEFENDER)))

    assert first.data["Unused"] == ""


def test_invalid_utf8_bytes_do_not_abort_the_read() -> None:
    events = list(read_windows_events(SYSMON_FIRST_20))

    assert len(events) == 20
    assert events[0].event_id == 12
    assert events[0].record_id == 3500
    assert events[0].data["RuleName"] == "-"


def test_truncated_file_keeps_events_read_before_the_cut(tmp_path: Path) -> None:
    complete = wrap(event_xml(record_id="1"), event_xml(record_id="2"))
    path = write_xml(tmp_path, complete.removesuffix("</Events>\n") + event_xml(record_id="3")[:40])

    events = list(read_windows_events(path))

    assert [event.record_id for event in events] == [1, 2]


def test_event_without_integer_event_id_is_skipped(tmp_path: Path) -> None:
    path = write_xml(
        tmp_path,
        wrap(
            event_xml(event_id="oops", record_id="1"),
            event_xml(event_id="", record_id="2"),
            event_xml(record_id="3"),
        ),
    )

    assert [event.record_id for event in read_windows_events(path)] == [3]


def test_unnamed_data_element_is_skipped(tmp_path: Path) -> None:
    path = write_xml(
        tmp_path, wrap(event_xml(data="<Data>orphan</Data><Data Name='Kept'>yes</Data>"))
    )

    (event,) = read_windows_events(path)

    assert event.data == {"Kept": "yes"}


def test_namespace_prefix_does_not_matter(tmp_path: Path) -> None:
    body = (
        "<ns0:Events xmlns:ns0='" + NS + "'><ns0:Event><ns0:System>"
        "<ns0:EventID>4</ns0:EventID><ns0:EventRecordID>9</ns0:EventRecordID>"
        "<ns0:TimeCreated SystemTime='2026-10-18T20:46:51Z'/></ns0:System>"
        "<ns0:EventData><ns0:Data Name='A'>b</ns0:Data></ns0:EventData></ns0:Event></ns0:Events>"
    )
    path = write_xml(tmp_path, body)

    (event,) = read_windows_events(path)

    assert event == WindowsEvent(
        event_id=4,
        record_id=9,
        system_time=datetime(2026, 10, 18, 20, 46, 51, tzinfo=UTC),
        data={"A": "b"},
    )


def test_missing_or_unparsable_time_is_none(tmp_path: Path) -> None:
    path = write_xml(
        tmp_path,
        wrap(
            event_xml(time="not-a-time", record_id="1"),
            event_xml(time="", record_id="2"),
        ),
    )

    events = list(read_windows_events(path))

    assert [event.system_time for event in events] == [None, None]


def test_missing_record_id_is_none(tmp_path: Path) -> None:
    body = (
        f"<Events><Event xmlns='{NS}'><System><EventID>5</EventID>"
        "</System><EventData/></Event></Events>"
    )
    path = write_xml(tmp_path, body)

    (event,) = read_windows_events(path)

    assert event.record_id is None
    assert event.system_time is None
    assert event.data == {}


def test_read_stops_at_byte_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows_events, "MAX_READ_BYTES", 2700)

    events = list(read_windows_events(DEFENDER))

    assert [event.record_id for event in events] == [271]
