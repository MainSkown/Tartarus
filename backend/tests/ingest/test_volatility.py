import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.ingest import volatility
from app.ingest.capemon import CapemonNormalizer
from app.ingest.ecs import event_id
from app.ingest.volatility import VolatilityNormalizer
from tests.ingest.contract import check_normalizer_contract, check_tolerates_junk
from tests.ingest.reports import report_of
from tests.ingest.volatility_cases import (
    ANALYSIS_ID,
    CAPEMON_PAGES,
    CMDLINE,
    DEFENDER_PID,
    HOLLOWED_ADDRESS,
    HOLLOWED_PID,
    HOLLOWPROCESSES,
    INJECTED_ADDRESS,
    INJECTED_PID,
    MALFIND,
    PSLIST,
    SAMPLE_PID,
    SAMPLE_PIDS,
    context_of,
    copy_fixture_file,
    hexdump_of,
    malfind_row,
    read_fixture,
    rows_of_pids,
    sample_report,
    write_fixture_memory,
    write_memory,
)

CONTEXT_PLUGINS = (PSLIST, CMDLINE)
ALL_PLUGINS = (MALFIND, HOLLOWPROCESSES, *CONTEXT_PLUGINS)


def normalise(
    root: Path | None, report: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]], VolatilityNormalizer]:
    normalizer = VolatilityNormalizer()
    events = list(
        normalizer.normalise(sample_report() if report is None else report, context_of(root))
    )
    return events, normalizer


def real_run(root: Path) -> list[dict[str, Any]]:
    """The sample's analysis as the producer writes it: malfind narrowed to the run's pids."""
    write_fixture_memory(root, *ALL_PLUGINS, malfind_pids=SAMPLE_PIDS)
    return normalise(root)[0]


def findings(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event["event"]["kind"] == "event"]


def alerts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event["event"]["kind"] == "alert"]


def finding_at(events: list[dict[str, Any]], pid: int, address: str) -> dict[str, Any]:
    (match,) = (
        event
        for event in findings(events)
        if event["process"]["pid"] == pid and event["tartarus"]["memory"].get("address") == address
    )
    return match


def alert_of(events: list[dict[str, Any]], finding: dict[str, Any]) -> dict[str, Any]:
    (match,) = (
        alert for alert in alerts(events) if alert["related"]["events"] == [finding["event"]["id"]]
    )
    return match


def test_no_analysis_folder_is_no_events_and_no_error() -> None:
    events, normalizer = normalise(None)

    assert events == []
    assert normalizer.dropped == Counter()


def test_a_folder_without_memory_or_run_json_is_no_events(tmp_path: Path) -> None:
    assert normalise(tmp_path)[0] == []

    (tmp_path / "memory").mkdir()
    copy_fixture_file(tmp_path, MALFIND)
    assert normalise(tmp_path)[0] == []


def test_a_real_run_yields_the_two_real_regions_and_the_hollowing(tmp_path: Path) -> None:
    events = real_run(tmp_path)

    assert Counter(
        (event["process"]["pid"], event["tartarus"]["memory"]["plugin"])
        for event in findings(events)
    ) == {
        (INJECTED_PID, MALFIND): 1,
        (HOLLOWED_PID, MALFIND): 1,
        (HOLLOWED_PID, HOLLOWPROCESSES): 1,
    }
    assert len(alerts(events)) == 3


def test_the_context_plugins_alone_yield_no_events(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, PSLIST, CMDLINE)

    assert normalise(tmp_path)[0] == []


def test_malfind_finding_describes_the_region(tmp_path: Path) -> None:
    finding = finding_at(real_run(tmp_path), INJECTED_PID, INJECTED_ADDRESS)

    assert finding["event"]["module"] == "volatility"
    assert finding["event"]["dataset"] == "volatility.malfind"
    assert finding["event"]["action"] == "memory-finding"
    assert finding["event"]["kind"] == "event"
    assert finding["event"]["category"] == ["malware", "process"]
    assert finding["tartarus"]["lane"] == "memory"
    assert finding["tartarus"]["memory"] == {
        "plugin": MALFIND,
        "address": INJECTED_ADDRESS,
        "protection": "PAGE_EXECUTE_READWRITE",
        "note": "MZ header",
    }
    assert "dump_ref" not in finding["tartarus"]["memory"]


def test_summary_reads_as_a_sentence(tmp_path: Path) -> None:
    finding = finding_at(real_run(tmp_path), INJECTED_PID, INJECTED_ADDRESS)

    assert finding["tartarus"]["summary"] == (
        "malfind found an executable private region in PING.EXE (pid 1384) "
        "at 0x1bccc4e0000, RWX, MZ header"
    )


def test_summary_without_a_known_protection_or_note_keeps_what_the_row_says(
    tmp_path: Path,
) -> None:
    row = malfind_row(SAMPLE_PID, 0x1000, hexdump_of(b"\x90"), Protection="PAGE_EXECUTE_WRITECOPY")
    write_memory(tmp_path, {MALFIND: [row]})

    (finding, _) = normalise(tmp_path)[0]

    assert finding["tartarus"]["summary"] == (
        "malfind found an executable private region in memtest3.exe (pid 1936) at 0x1000, "
        "PAGE_EXECUTE_WRITECOPY"
    )


def test_raw_keeps_the_row_with_its_hex_preview(tmp_path: Path) -> None:
    finding = finding_at(real_run(tmp_path), INJECTED_PID, INJECTED_ADDRESS)

    assert finding["tartarus"]["raw"]["Hexdump"].startswith("4d 5a 00 00")
    assert finding["tartarus"]["raw"]["Start VPN"] == 0x1BCCC4E0000


def test_process_context_comes_from_pslist_and_cmdline(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, MALFIND, PSLIST, CMDLINE, malfind_pids=[DEFENDER_PID])
    report = report_of()

    events, _ = normalise(tmp_path, report)

    process_section = events[0]["process"]
    assert process_section["pid"] == DEFENDER_PID
    assert process_section["name"] == "MsMpEng.exe"
    assert process_section["command_line"] == r'"C:\Program Files\Windows Defender\MsMpEng.exe"'
    assert process_section["entity_id"] == f"{ANALYSIS_ID}:{DEFENDER_PID}"


def test_a_pid_nobody_listed_keeps_the_name_the_plugin_gave(tmp_path: Path) -> None:
    row = malfind_row(99, 0x5000, hexdump_of(b"\x90"), Process="odd.exe")
    write_memory(tmp_path, {MALFIND: [row]})

    (finding, _) = normalise(tmp_path, report_of())[0]

    assert finding["process"]["name"] == "odd.exe"
    assert "command_line" not in finding["process"]


def test_entity_id_is_the_one_capemon_gives_its_own_events(tmp_path: Path) -> None:
    report = sample_report()
    capemon = next(
        event
        for event in CapemonNormalizer().normalise(report, context_of(tmp_path))
        if event["process"]["pid"] == INJECTED_PID
    )
    finding = finding_at(real_run(tmp_path), INJECTED_PID, INJECTED_ADDRESS)

    assert finding["process"]["entity_id"] == capemon["process"]["entity_id"]
    assert "@" in finding["process"]["entity_id"]
    assert finding["process"]["name"] == "PING.EXE"
    assert finding["process"]["command_line"] == capemon["process"]["command_line"]


def test_finding_takes_the_analysis_end_else_the_start(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, MALFIND, malfind_pids=[INJECTED_PID])

    ended = normalise(tmp_path, sample_report())[0]
    unended = normalise(tmp_path, sample_report(ended=None))[0]

    assert {event["@timestamp"] for event in ended} == {"2026-10-18T22:16:10.000Z"}
    assert {event["@timestamp"] for event in unended} == {"2026-10-18T22:15:00.000Z"}


def test_event_id_follows_the_rows_position_in_the_file(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, MALFIND)
    position = next(
        index
        for index, row in enumerate(read_fixture(MALFIND))
        if row["PID"] == INJECTED_PID and row["Start VPN"] == 0x1BCCC4E0000
    )

    finding = finding_at(normalise(tmp_path)[0], INJECTED_PID, INJECTED_ADDRESS)

    assert finding["event"]["id"] == event_id(
        ANALYSIS_ID, "volatility", f"memory/{MALFIND}", position
    )


def test_malfind_with_an_mz_header_is_a_high_severity_alert(tmp_path: Path) -> None:
    events = real_run(tmp_path)
    finding = finding_at(events, INJECTED_PID, INJECTED_ADDRESS)

    alert = alert_of(events, finding)

    assert alert["event"]["kind"] == "alert"
    assert alert["event"]["severity"] == 3
    assert alert["event"]["module"] == "volatility"
    assert alert["event"]["dataset"] == "volatility.malfind"
    assert alert["event"]["category"] == ["malware", "process"]
    assert alert["event"]["type"] == ["info", "indicator"]
    assert alert["tartarus"]["lane"] == "memory"
    assert alert["rule"] == {
        "id": "volatility.malfind",
        "name": "Executable private memory region",
        "description": (
            "A private memory region of the process is executable and holds code or a PE "
            "image, which is how injected code looks"
        ),
        "ruleset": "volatility",
    }
    assert alert["threat"] == {"technique": {"id": ["T1055"], "name": "Process Injection"}}
    assert alert["process"] == finding["process"]
    assert alert["event"]["id"] != finding["event"]["id"]
    assert finding["event"]["severity"] == 0


def test_a_bare_rwx_region_is_a_medium_alert(tmp_path: Path) -> None:
    row = malfind_row(SAMPLE_PID, 0x2000_0000, hexdump_of(b"\x90\x90\xc3"))
    write_memory(tmp_path, {MALFIND: [row]})

    events, _ = normalise(tmp_path)

    assert [alert["event"]["severity"] for alert in alerts(events)] == [2]


def test_detection_match_names_the_note_protection_and_address(tmp_path: Path) -> None:
    events = real_run(tmp_path)
    alert = alert_of(events, finding_at(events, INJECTED_PID, INJECTED_ADDRESS))

    assert alert["tartarus"]["detection"]["match"] == (
        "address: 0x1bccc4e0000; protection: PAGE_EXECUTE_READWRITE; note: MZ header"
    )
    assert alert["tartarus"]["summary"] == (
        "Executable private memory region: PING.EXE (pid 1384) at 0x1bccc4e0000"
    )


def test_hollowprocesses_is_one_finding_per_pid_with_both_notes_in_order(
    tmp_path: Path,
) -> None:
    events = real_run(tmp_path)
    hollowed = [
        event
        for event in findings(events)
        if event["tartarus"]["memory"]["plugin"] == HOLLOWPROCESSES
    ]
    (finding,) = hollowed
    peb_note, vad_note = (row["Notes"] for row in read_fixture(HOLLOWPROCESSES))

    assert finding["tartarus"]["memory"]["address"] == HOLLOWED_ADDRESS
    assert finding["tartarus"]["memory"]["note"] == f"{peb_note}; {vad_note}"
    assert "protection" not in finding["tartarus"]["memory"]
    assert finding["tartarus"]["summary"] == (
        "hollowprocesses found 2 problems in PING.EXE (pid 6304) at 0x140000000: "
        f"{peb_note}; {vad_note}"
    )
    assert finding["tartarus"]["raw"]["Notes"] == peb_note


def test_hollowprocesses_rows_of_one_pid_join_their_notes_without_repeats(
    tmp_path: Path,
) -> None:
    rows = [
        {"PID": SAMPLE_PID, "Process": "memtest3.exe", "Notes": "first problem"},
        {"PID": SAMPLE_PID, "Process": "memtest3.exe", "Notes": "second problem"},
        {"PID": SAMPLE_PID, "Process": "memtest3.exe", "Notes": "first problem"},
    ]
    write_memory(tmp_path, {HOLLOWPROCESSES: rows})

    events, _ = normalise(tmp_path)

    (finding,) = findings(events)
    assert finding["tartarus"]["memory"]["note"] == "first problem; second problem"
    assert finding["tartarus"]["summary"] == (
        "hollowprocesses found 3 problems in memtest3.exe (pid 1936): first problem; second problem"
    )
    assert len(alerts(events)) == 1


def test_hollowprocesses_finding_id_follows_the_first_row_of_its_pid(tmp_path: Path) -> None:
    rows = [
        {"PID": SAMPLE_PID, "Process": "memtest3.exe", "Notes": "one"},
        {"PID": INJECTED_PID, "Process": "PING.EXE", "Notes": "two"},
        {"PID": SAMPLE_PID, "Process": "memtest3.exe", "Notes": "three"},
    ]
    write_memory(tmp_path, {HOLLOWPROCESSES: rows})

    events, _ = normalise(tmp_path)

    ids_by_pid = {event["process"]["pid"]: event["event"]["id"] for event in findings(events)}
    assert ids_by_pid == {
        SAMPLE_PID: event_id(ANALYSIS_ID, "volatility", f"memory/{HOLLOWPROCESSES}", 0),
        INJECTED_PID: event_id(ANALYSIS_ID, "volatility", f"memory/{HOLLOWPROCESSES}", 1),
    }


def test_malfind_regions_of_one_pid_stay_separate_findings(tmp_path: Path) -> None:
    rows = [
        malfind_row(SAMPLE_PID, 0x1000, hexdump_of(b"\x90")),
        malfind_row(SAMPLE_PID, 0x2000, hexdump_of(b"\x90")),
    ]
    write_memory(tmp_path, {MALFIND: rows})

    events, _ = normalise(tmp_path)

    assert [event["tartarus"]["memory"]["address"] for event in findings(events)] == [
        "0x1000",
        "0x2000",
    ]
    assert len(alerts(events)) == 2


def test_hollowprocesses_detection_is_high_and_names_process_hollowing(tmp_path: Path) -> None:
    events = real_run(tmp_path)
    finding = next(
        event
        for event in findings(events)
        if event["tartarus"]["memory"]["plugin"] == HOLLOWPROCESSES
    )

    alert = alert_of(events, finding)

    assert alert["event"]["severity"] == 3
    assert alert["event"]["dataset"] == "volatility.hollowprocesses"
    assert alert["rule"]["id"] == "volatility.hollowprocesses"
    assert alert["rule"]["ruleset"] == "volatility"
    assert alert["threat"]["technique"] == {"id": ["T1055.012"], "name": "Process Hollowing"}


def test_a_hollowprocesses_note_without_an_address_still_yields_the_finding(
    tmp_path: Path,
) -> None:
    rows = [{"PID": SAMPLE_PID, "Process": "memtest3.exe", "Notes": "Something odd"}]
    write_memory(tmp_path, {HOLLOWPROCESSES: rows})

    (finding, _) = normalise(tmp_path)[0]

    assert "address" not in finding["tartarus"]["memory"]


def test_the_monitors_own_pages_are_dropped_by_their_content(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, MALFIND, malfind_pids=SAMPLE_PIDS)

    events, normalizer = normalise(tmp_path)

    assert {event["tartarus"]["memory"]["address"] for event in findings(events)} == {
        INJECTED_ADDRESS,
        HOLLOWED_ADDRESS,
    }
    assert normalizer.dropped == {"monitor-page": 8}


def test_noise_rule_does_not_look_at_addresses(tmp_path: Path) -> None:
    pages = [
        malfind_row(
            SAMPLE_PID,
            start,
            hexdump_of(start.to_bytes(8, "little")),
            Notes=None,
        )
        for start in (0x1111_0000_0000, 0x2222_0000_0000)
    ]
    write_memory(tmp_path, {MALFIND: pages})

    events, normalizer = normalise(tmp_path)

    assert events == []
    assert normalizer.dropped == {"monitor-page": 2}


def test_a_known_monitor_address_alone_does_not_drop_a_row(tmp_path: Path) -> None:
    address = int(CAPEMON_PAGES[0], 16)
    shellcode = malfind_row(SAMPLE_PID, address, hexdump_of(b"\xfc\x48\x83\xe4"))
    write_memory(tmp_path, {MALFIND: [shellcode]})

    events, normalizer = normalise(tmp_path)

    assert len(findings(events)) == 1
    assert normalizer.dropped == Counter()


def test_the_whole_dump_keeps_every_row_that_is_not_the_monitors(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, MALFIND)

    events, normalizer = normalise(tmp_path)

    assert len(findings(events)) == 14
    assert normalizer.dropped == {"monitor-page": 8}
    assert {event["process"]["pid"] for event in findings(events)} >= {DEFENDER_PID, 8724}


def test_dropped_is_reset_for_every_run(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, MALFIND, malfind_pids=SAMPLE_PIDS)
    normalizer = VolatilityNormalizer()
    for _ in range(2):
        list(normalizer.normalise(sample_report(), context_of(tmp_path)))

    assert normalizer.dropped == {"monitor-page": 8}


def test_a_plugin_that_failed_is_skipped_and_the_others_are_used(tmp_path: Path) -> None:
    write_memory(
        tmp_path,
        {
            MALFIND: rows_of_pids(MALFIND, [INJECTED_PID])[:1],
            HOLLOWPROCESSES: [{"PID": 1, "Notes": "x"}],
        },
        entries={
            MALFIND: {"rows": 1, "seconds": 0.8, "error": None},
            HOLLOWPROCESSES: {"rows": 0, "seconds": 0.1, "error": "timeout"},
        },
    )

    events, _ = normalise(tmp_path)

    assert {event["tartarus"]["memory"]["plugin"] for event in events} == {MALFIND}


def test_a_missing_plugin_file_is_skipped(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, MALFIND, malfind_pids=SAMPLE_PIDS)
    (tmp_path / "memory" / "run.json").write_text(
        json.dumps(
            {
                "plugins": {
                    MALFIND: {"rows": 10, "seconds": 1.0, "error": None},
                    HOLLOWPROCESSES: {"rows": 2, "seconds": 1.0, "error": None},
                }
            }
        )
    )

    events, _ = normalise(tmp_path)

    assert len(findings(events)) == 2


@pytest.mark.parametrize(
    "content",
    ["", "{", '{"not": "an array"}', "[1, 2", "null", '"text"', '[1, null, "x", []]'],
)
def test_a_plugin_file_that_is_not_a_usable_array_is_skipped(tmp_path: Path, content: str) -> None:
    write_fixture_memory(tmp_path, HOLLOWPROCESSES)
    (tmp_path / "memory" / f"{MALFIND}.json").write_text(content)

    events, _ = normalise(tmp_path)

    assert {event["tartarus"]["memory"]["plugin"] for event in events} == {HOLLOWPROCESSES}


def test_a_truncated_run_json_does_not_stop_the_plugin_files(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, MALFIND, malfind_pids=SAMPLE_PIDS)
    (tmp_path / "memory" / "run.json").write_text('{"volatility": "2.28')

    assert len(findings(normalise(tmp_path)[0])) == 2


@pytest.mark.parametrize(
    "row",
    [
        {},
        {"PID": "x"},
        {"PID": None, "Start VPN": 5},
        {"PID": True},
        {"Process": "a.exe", "Start VPN": 5},
    ],
)
def test_a_row_without_a_usable_pid_is_skipped(tmp_path: Path, row: dict[str, Any]) -> None:
    good = malfind_row(SAMPLE_PID, 0x4000, hexdump_of(b"\x90"))
    write_memory(tmp_path, {MALFIND: [row, good]})

    events, normalizer = normalise(tmp_path)

    assert [event["tartarus"]["memory"]["address"] for event in findings(events)] == ["0x4000"]
    assert normalizer.dropped == {"malformed-row": 1}


def test_a_row_with_odd_column_types_keeps_what_it_can(tmp_path: Path) -> None:
    row = {
        "PID": "1936",
        "Process": 5,
        "Start VPN": "0x4000",
        "Protection": ["x"],
        "Notes": 7,
        "Hexdump": None,
    }
    write_memory(tmp_path, {MALFIND: [row]})

    (finding, _) = normalise(tmp_path)[0]

    assert finding["process"]["pid"] == SAMPLE_PID
    assert finding["tartarus"]["memory"] == {"plugin": MALFIND, "address": "0x4000"}


def test_rows_beyond_the_cap_are_counted_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(volatility, "ROW_CAP", 3)
    rows = [
        malfind_row(SAMPLE_PID, 0x1000 * (index + 1), hexdump_of(b"\x90")) for index in range(5)
    ]
    write_memory(tmp_path, {MALFIND: rows})

    events, normalizer = normalise(tmp_path)

    assert len(findings(events)) == 3
    assert normalizer.dropped == {"row-cap": 2}


def test_it_does_not_raise_on_junk_reports(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, *ALL_PLUGINS, malfind_pids=SAMPLE_PIDS)

    check_tolerates_junk(VolatilityNormalizer(), context_of(tmp_path))


def test_it_keeps_the_contract_on_a_real_run(tmp_path: Path) -> None:
    write_fixture_memory(tmp_path, *ALL_PLUGINS, malfind_pids=SAMPLE_PIDS)

    events = check_normalizer_contract(
        VolatilityNormalizer(), sample_report(), context_of(tmp_path)
    )

    assert len(events) == 6
