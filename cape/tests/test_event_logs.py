"""The host-side auxiliary that exports Windows event logs, against a fake guest."""

import base64
import configparser
import dataclasses
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest
from fixtures.event_log_guest import EVENT_NAMESPACE, FakeClock, FakeGuest

from auxiliary import event_logs

SYSMON = "Microsoft-Windows-Sysmon/Operational"
DEFENDER = "Microsoft-Windows-Windows Defender/Operational"
REPO = Path(__file__).resolve().parents[2]
EMPTY_EVENTS = b"<Events>\n</Events>\n"


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def guest(clock):
    fake = FakeGuest(clock)
    fake.add_log(SYSMON)
    fake.add_log(DEFENDER)
    return fake


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "analysis"


@pytest.fixture
def sysmon_config(tmp_path):
    path = tmp_path / "sysmon-config.xml"
    path.write_text("<Sysmon schemaversion='4.90'/>")
    return path


def channels_with_config(source: Path):
    sysmon = dataclasses.replace(
        event_logs.SYSMON, config=dataclasses.replace(event_logs.SYSMON.config, source=source)
    )
    return (sysmon, event_logs.DEFENDER)


@pytest.fixture
def collector(guest, clock, sysmon_config):
    return event_logs.EventLogCollector(guest, clock, channels_with_config(sysmon_config))


def parsed(path: Path) -> ET.Element:
    return ET.fromstring(path.read_bytes())  # noqa: S314 - an XML file this test wrote


def record_ids(path: Path) -> list[int]:
    return [int(node.text) for node in parsed(path).iter(f"{{{EVENT_NAMESPACE}}}EventRecordID")]


def export_commands(guest: FakeGuest) -> list[str]:
    return [
        command
        for command in guest.commands
        if "/e:Events" in command or "Get-WinEvent" in base64_script(command)
    ]


def run(collector, folder):
    collector.start()
    collector.export_to(folder)


class TestChannelTable:
    def test_sysmon_goes_to_its_own_folder_in_the_guests_ansi_code_page(self):
        assert event_logs.SYSMON.name == SYSMON
        assert event_logs.SYSMON.target == "sysmon/sysmon.xml"
        assert event_logs.SYSMON.guest_encoding == "ansi"

    def test_defender_goes_to_aux_in_utf8_and_waits_for_its_detections_to_close(self):
        assert event_logs.DEFENDER.name == DEFENDER
        assert event_logs.DEFENDER.target == "aux/defender.xml"
        assert event_logs.DEFENDER.guest_encoding == "utf-8"
        assert event_logs.DEFENDER.is_settled is event_logs.every_detection_closed

    def test_the_table_lists_exactly_those_two(self):
        assert [channel.name for channel in event_logs.CHANNELS] == [SYSMON, DEFENDER]

    def test_a_channel_is_added_with_one_table_line(self, guest, clock, folder):
        guest.add_event("Application", message="old")
        extra = event_logs.Channel("Application", "aux/application.xml", "utf-8")
        collector = event_logs.EventLogCollector(guest, clock, (extra,))
        collector.start()
        guest.add_event("Application", message="new")
        collector.export_to(folder)
        assert record_ids(folder / "aux/application.xml") == [2]


class TestBaseline:
    def test_only_records_written_after_start_are_exported(self, guest, collector, folder):
        for _ in range(3):
            guest.add_event(SYSMON, event_id=1)
        collector.start()
        later = [guest.add_event(SYSMON, event_id=3), guest.add_event(SYSMON, event_id=11)]
        collector.export_to(folder)
        assert record_ids(folder / "sysmon/sysmon.xml") == later

    def test_the_old_records_are_not_in_the_export(self, guest, collector, folder):
        old = [guest.add_event(DEFENDER, event_id=5007) for _ in range(4)]
        collector.start()
        new = guest.add_event(DEFENDER, event_id=5007)
        collector.export_to(folder)
        ids = record_ids(folder / "aux/defender.xml")
        assert ids == [new]
        assert not set(old) & set(ids)

    def test_nothing_is_ever_cleared_because_that_would_erase_the_samples_own_detection(
        self, guest, collector, folder
    ):
        guest.add_event(DEFENDER, event_id=1116, Detection_ID="{A}")
        run(collector, folder)
        assert not [
            command
            for command in guest.commands
            if re.search(r"\bcl\b|clear-log|Clear-EventLog", command)
        ]

    def test_a_log_with_no_records_has_the_baseline_zero(self, guest, collector, folder):
        collector.start()
        first = guest.add_event(DEFENDER, event_id=1116, Detection_ID="{A}")
        guest.add_event(DEFENDER, event_id=1117, Detection_ID="{A}")
        collector.export_to(folder)
        assert record_ids(folder / "aux/defender.xml")[0] == first

    def test_a_baseline_that_cannot_be_read_skips_that_export_instead_of_widening_it(
        self, guest, collector, folder
    ):
        guest.add_event(SYSMON)
        guest.broken_commands['query-events "Microsoft-Windows-Sysmon/Operational" /c:1'] = (
            ConnectionError("agent")
        )
        guest.add_event(DEFENDER, event_id=5007)
        run(collector, folder)
        assert not (folder / "sysmon/sysmon.xml").exists()
        assert (folder / "aux/defender.xml").exists()
        assert export_commands(guest) == [
            c for c in export_commands(guest) if DEFENDER in base64_script(c)
        ]

    def test_a_newest_record_that_cannot_be_parsed_skips_the_export(self, guest, collector, folder):
        guest.add_event(SYSMON)
        original = guest._answer
        guest._answer = lambda command: b"garbage" if "/rd:true" in command else original(command)
        run(collector, folder)
        assert not (folder / "sysmon/sysmon.xml").exists()

    def test_a_code_page_that_cannot_be_read_skips_the_ansi_channels_only(
        self, guest, collector, folder
    ):
        guest.add_event(SYSMON)
        guest.broken_commands["reg.exe"] = ConnectionError("agent")
        run(collector, folder)
        assert not (folder / "sysmon/sysmon.xml").exists()
        assert (folder / "aux/defender.xml").exists()

    def test_an_unknown_code_page_counts_as_unreadable(self, guest, collector, folder):
        guest.add_event(SYSMON)
        original = guest._answer
        guest._answer = lambda command: (
            b"ACP    REG_SZ    99999999\r\n" if "reg.exe" in command else original(command)
        )
        run(collector, folder)
        assert not (folder / "sysmon/sysmon.xml").exists()


class TestExportEncoding:
    def test_sysmon_is_decoded_with_the_guests_ansi_code_page_into_utf8(
        self, guest, collector, folder
    ):
        collector.start()
        guest.add_event(SYSMON, event_id=1, Image="C:\\Użytkownicy\\żółć.exe")
        collector.export_to(folder)
        assert "C:\\Użytkownicy\\żółć.exe" in (folder / "sysmon/sysmon.xml").read_text(
            encoding="utf-8"
        )

    def test_another_code_page_is_honoured(self, guest, clock, sysmon_config, folder):
        guest.code_page = "1252"
        collector = event_logs.EventLogCollector(guest, clock, channels_with_config(sysmon_config))
        collector.start()
        guest.add_event(SYSMON, event_id=1, Image="C:\\café.exe")
        collector.export_to(folder)
        assert "café" in (folder / "sysmon/sysmon.xml").read_text(encoding="utf-8")

    def test_defender_goes_through_powershell_as_utf8(self, guest, collector, folder):
        collector.start()
        guest.add_event(DEFENDER, event_id=5007, Value="日本語 żółć")
        collector.export_to(folder)
        assert "日本語 żółć" in (folder / "aux/defender.xml").read_text(encoding="utf-8")
        powershell = [command for command in guest.commands if "powershell.exe" in command]
        assert powershell
        assert all("-NoProfile -EncodedCommand " in command for command in powershell)

    def test_the_agent_gets_forward_slash_paths_because_it_splits_commands_posix_style(
        self, guest, collector, folder
    ):
        run(collector, folder)
        executables = {command.split(" ", 1)[0] for command in guest.commands}
        assert all("\\" not in executable for executable in executables)
        assert executables <= {
            "C:/Windows/System32/wevtutil.exe",
            "C:/Windows/System32/reg.exe",
            "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            "C:/Windows/Sysmon64.exe",
        }


class TestOutputFile:
    @pytest.mark.parametrize("wevtutil_prints_a_wrapper", [False, True])
    def test_a_file_is_written_even_when_there_are_no_events(
        self, guest, collector, folder, wevtutil_prints_a_wrapper
    ):
        guest.empty_wevtutil_prints_wrapper = wevtutil_prints_a_wrapper
        run(collector, folder)
        for relative in ("sysmon/sysmon.xml", "aux/defender.xml"):
            root = parsed(folder / relative)
            assert root.tag == "Events"
            assert len(root) == 0

    def test_the_empty_file_is_the_events_wrapper_alone(self, guest, collector, folder):
        run(collector, folder)
        assert (folder / "aux/defender.xml").read_bytes().split() == EMPTY_EVENTS.split()

    def test_the_file_is_utf8_xml_inside_the_events_wrapper(self, guest, collector, folder):
        collector.start()
        guest.add_event(SYSMON, event_id=1, Image="żółć")
        guest.add_event(DEFENDER, event_id=5007)
        collector.export_to(folder)
        for relative in ("sysmon/sysmon.xml", "aux/defender.xml"):
            data = (folder / relative).read_bytes()
            data.decode("utf-8")
            assert parsed(folder / relative).tag == "Events"

    def test_control_characters_that_xml_forbids_are_dropped_not_the_whole_export(
        self, guest, collector, folder
    ):
        collector.start()
        guest.add_event(DEFENDER, event_id=5007, Value="a\x01b\x1fc")
        collector.export_to(folder)
        assert parsed(folder / "aux/defender.xml")[0].find(".//*[@Name='Value']") is not None
        assert b"\x01" not in (folder / "aux/defender.xml").read_bytes()

    def test_output_that_is_not_an_events_document_is_not_written(self, guest, collector, folder):
        collector.start()
        guest.add_event(SYSMON, event_id=1)
        original = guest._answer
        guest._answer = lambda command: (
            b"The system cannot find the file" if "/e:Events" in command else original(command)
        )
        collector.export_to(folder)
        assert not (folder / "sysmon/sysmon.xml").exists()

    def test_truncated_xml_is_not_written(self, guest, collector, folder):
        collector.start()
        guest.add_event(SYSMON, event_id=1)
        original = guest._answer
        guest._answer = lambda command: (
            b"<Events><Event>" if "/e:Events" in command else original(command)
        )
        collector.export_to(folder)
        assert not (folder / "sysmon/sysmon.xml").exists()

    def test_a_byte_order_mark_and_stray_console_lines_before_the_wrapper_are_dropped(
        self, guest, collector, folder
    ):
        collector.start()
        guest.add_event(DEFENDER, event_id=5007)
        original = guest._answer
        guest._answer = lambda command: (
            b"\xef\xbb\xbfWARNING: slow\r\n" + original(command)
            if "EncodedCommand" in command and "OutputEncoding" in base64_script(command)
            else original(command)
        )
        collector.export_to(folder)
        assert (folder / "aux/defender.xml").read_bytes().startswith(b"<Events>")

    def test_a_doctype_from_the_guest_is_refused_because_the_sample_controls_that_text(
        self, guest, collector, folder
    ):
        collector.start()
        guest.add_event(SYSMON, event_id=1)
        original = guest._answer
        bomb = b'<!DOCTYPE x [<!ENTITY a "aaaa">]><Events><Event>&a;</Event></Events>'
        guest._answer = lambda command: bomb if "/e:Events" in command else original(command)
        collector.export_to(folder)
        assert not (folder / "sysmon/sysmon.xml").exists()


class TestSysmonIsOptional:
    def test_a_guest_without_sysmon_gets_no_sysmon_file_and_no_error(
        self, guest, collector, folder, caplog
    ):
        del guest.logs[SYSMON]
        guest.add_event(DEFENDER, event_id=5007)
        with caplog.at_level(logging.WARNING):
            run(collector, folder)
        assert not (folder / "sysmon").exists()
        assert (folder / "aux/defender.xml").exists()
        assert not [record for record in caplog.records if record.levelno >= logging.ERROR]

    def test_the_sysmon_config_is_not_pushed_to_a_guest_that_has_no_sysmon(
        self, guest, collector, folder
    ):
        del guest.logs[SYSMON]
        run(collector, folder)
        assert guest.stored == {}
        assert not [command for command in guest.commands if "Sysmon64.exe" in command]
        assert not [
            command for command in guest.commands if SYSMON in command and "query-events" in command
        ]

    def test_the_code_page_is_not_even_read_when_no_channel_needs_it(self, guest, clock, folder):
        del guest.logs[SYSMON]
        collector = event_logs.EventLogCollector(guest, clock, (event_logs.DEFENDER,))
        run(collector, folder)
        assert not [command for command in guest.commands if "reg.exe" in command]


class TestSysmonConfig:
    def test_the_config_is_pushed_applied_with_c_and_removed_before_the_baseline(
        self, guest, collector, sysmon_config
    ):
        collector.start()
        assert guest.sysmon_applied_config == sysmon_config.read_bytes()
        apply = next(command for command in guest.commands if "Sysmon64.exe" in command)
        assert apply.startswith("C:/Windows/Sysmon64.exe -accepteula -c ")
        guest_path = apply.rsplit(" ", 1)[1]
        assert guest_path in guest.stored
        assert guest.removed == [guest_path]

    def test_the_config_changed_event_sysmon_writes_is_before_the_baseline_so_it_is_not_exported(
        self, guest, collector, folder
    ):
        run(collector, folder)
        assert record_ids(folder / "sysmon/sysmon.xml") == []

    def test_the_config_is_applied_before_the_newest_record_is_read(self, guest, collector):
        collector.start()
        commands = guest.commands
        apply = next(i for i, command in enumerate(commands) if "Sysmon64.exe" in command)
        newest = next(
            i for i, command in enumerate(commands) if "/rd:true" in command and SYSMON in command
        )
        assert apply < newest

    def test_a_config_file_missing_on_the_host_is_logged_and_the_run_continues(
        self, guest, clock, tmp_path, folder, caplog
    ):
        collector = event_logs.EventLogCollector(
            guest, clock, channels_with_config(tmp_path / "gone.xml")
        )
        with caplog.at_level(logging.WARNING):
            run(collector, folder)
        assert "gone.xml" in caplog.text
        assert (folder / "sysmon/sysmon.xml").exists()

    def test_a_failed_push_is_logged_and_the_baseline_is_still_taken(
        self, guest, collector, folder, caplog
    ):
        guest.store_failure = ConnectionError("agent")
        with caplog.at_level(logging.WARNING):
            run(collector, folder)
        assert not [command for command in guest.commands if "Sysmon64.exe" in command]
        assert (folder / "sysmon/sysmon.xml").exists()

    def test_a_failed_apply_still_removes_the_pushed_file(self, guest, collector, folder):
        guest.broken_commands["Sysmon64.exe"] = RuntimeError("500")
        run(collector, folder)
        assert guest.removed
        assert (folder / "sysmon/sysmon.xml").exists()

    def test_only_a_channel_with_a_config_pushes_one(self, guest, clock, folder):
        collector = event_logs.EventLogCollector(guest, clock, (event_logs.DEFENDER,))
        run(collector, folder)
        assert guest.stored == {}

    def test_the_shipped_config_path_is_the_one_the_image_copies_the_profile_to(self):
        assert event_logs.SYSMON.config.source == Path(
            "/usr/local/lib/tartarus/profiles/windows/sysmon-config.xml"
        )
        assert (REPO / "guest/profiles/windows/sysmon-config.xml").is_file()


def detection(guest, detection_id, event_id=1116, delay=0.0):
    return guest.add_event(DEFENDER, event_id=event_id, delay=delay, Detection_ID=detection_id)


class TestDefenderSettle:
    def test_no_detection_means_no_waiting(self, guest, collector, folder, clock):
        guest.add_event(DEFENDER, event_id=5007)
        collector.start()
        before = clock.now()
        collector.export_to(folder)
        assert clock.now() - before < 10
        assert len([c for c in guest.commands if "powershell.exe" in c]) == 1

    def test_it_waits_until_the_detection_has_its_closing_event(
        self, guest, collector, folder, clock
    ):
        collector.start()
        detection(guest, "{A}", 1116)
        detection(guest, "{A}", 1117, delay=14)
        before = clock.now()
        collector.export_to(folder)
        text = (folder / "aux/defender.xml").read_text(encoding="utf-8")
        assert "<EventID>1117</EventID>" in text
        assert 10 <= clock.now() - before < event_logs.SETTLE_CAP_S

    @pytest.mark.parametrize("closing", [1117, 1118, 1119])
    def test_each_closing_event_id_ends_the_wait(self, guest, collector, folder, clock, closing):
        collector.start()
        detection(guest, "{A}", 1116)
        detection(guest, "{A}", closing, delay=5)
        collector.export_to(folder)
        assert f"<EventID>{closing}</EventID>" in (folder / "aux/defender.xml").read_text(
            encoding="utf-8"
        )

    def test_a_closing_event_of_another_detection_does_not_count(
        self, guest, collector, folder, clock
    ):
        collector.start()
        detection(guest, "{A}", 1116)
        detection(guest, "{B}", 1117)
        before = clock.now()
        collector.export_to(folder)
        assert clock.now() - before >= event_logs.SETTLE_CAP_S

    def test_every_detection_needs_a_closing_event(self, guest, collector, folder):
        collector.start()
        detection(guest, "{A}", 1116)
        detection(guest, "{B}", 1116)
        detection(guest, "{A}", 1117)
        detection(guest, "{B}", 1117, delay=20)
        collector.export_to(folder)
        assert (folder / "aux/defender.xml").read_text(encoding="utf-8").count(
            "<EventID>1117</EventID>"
        ) == 2

    def test_it_gives_up_after_the_cap_and_writes_what_it_has(
        self, guest, collector, folder, clock, caplog
    ):
        collector.start()
        detection(guest, "{A}", 1116)
        before = clock.now()
        with caplog.at_level(logging.WARNING):
            collector.export_to(folder)
        waited = clock.now() - before
        assert event_logs.SETTLE_CAP_S <= waited < event_logs.SETTLE_CAP_S + 20
        assert "<EventID>1116</EventID>" in (folder / "aux/defender.xml").read_text(
            encoding="utf-8"
        )
        assert "still open" in caplog.text

    def test_sysmon_never_waits(self, guest, clock, sysmon_config, folder):
        collector = event_logs.EventLogCollector(
            guest, clock, (channels_with_config(sysmon_config)[0],)
        )
        collector.start()
        guest.add_event(SYSMON, event_id=1)
        before = clock.now()
        collector.export_to(folder)
        assert clock.now() - before < 5

    def test_the_predicate_reads_events_not_neighbouring_text(self):
        events = (
            b"<Events><Event xmlns='x'><System><EventID>1116</EventID></System><EventData>"
            b"<Data Name='Other'>1</Data></EventData></Event>"
            b"<Event xmlns='x'><System><EventID>1117</EventID></System><EventData>"
            b"<Data Name='Detection ID'>{A}</Data></EventData></Event></Events>"
        )
        assert event_logs.every_detection_closed(events)

    def test_an_empty_export_is_settled(self):
        assert event_logs.every_detection_closed(EMPTY_EVENTS)


class TestNeverRaises:
    def test_an_unreachable_agent_makes_start_and_export_no_ops(
        self, guest, collector, folder, caplog
    ):
        guest.broken_commands[""] = ConnectionError("no route")
        guest.store_failure = ConnectionError("no route")
        with caplog.at_level(logging.WARNING):
            run(collector, folder)
        assert not folder.exists()
        assert "no route" in caplog.text
        assert export_commands(guest) == []

    def test_one_failing_export_does_not_stop_the_other_channel(self, guest, collector, folder):
        collector.start()
        guest.add_event(DEFENDER, event_id=5007)
        guest.broken_commands["/e:Events"] = TimeoutError("read timed out")
        collector.export_to(folder)
        assert not (folder / "sysmon/sysmon.xml").exists()
        assert (folder / "aux/defender.xml").exists()

    def test_an_unwritable_destination_is_logged_not_raised(
        self, guest, collector, tmp_path, caplog
    ):
        blocker = tmp_path / "blocker"
        blocker.write_text("a file where the folder should be")
        with caplog.at_level(logging.WARNING):
            run(collector, blocker)
        assert "Sysmon" in caplog.text

    def test_exporting_without_a_successful_start_exports_nothing(self, guest, collector, folder):
        collector.export_to(folder)
        assert guest.commands == []
        assert not folder.exists()


class TestTimeBudget:
    def test_every_call_while_starting_has_a_short_timeout(self, guest, collector):
        collector.start()
        assert guest.timeouts
        assert max(guest.timeouts) <= event_logs.BASELINE_TIMEOUT_S

    def test_each_export_call_is_bounded_by_its_channels_read_timeout(
        self, guest, collector, folder
    ):
        collector.start()
        guest.timeouts.clear()
        collector.export_to(folder)
        assert guest.timeouts == [
            event_logs.SYSMON.read_timeout_s,
            event_logs.DEFENDER.read_timeout_s,
        ]

    def test_only_the_sysmon_export_may_read_for_as_long_as_two_minutes(self):
        assert event_logs.SYSMON.read_timeout_s == 120
        assert event_logs.DEFENDER.read_timeout_s <= 30

    def test_a_slow_agent_cannot_hold_the_machine_past_the_cap(
        self, guest, collector, folder, clock
    ):
        collector.start()
        guest.add_event(SYSMON)
        guest.add_event(DEFENDER)
        guest.call_cost = 100
        before = clock.now()
        collector.export_to(folder)
        assert clock.now() - before <= event_logs.STOP_BUDGET_S + guest.call_cost
        assert len(export_commands(guest)) <= 2

    def test_no_call_is_allowed_to_run_past_what_is_left_of_the_budget(
        self, guest, collector, folder
    ):
        collector.start()
        guest.call_cost = event_logs.STOP_BUDGET_S - 10
        guest.timeouts.clear()
        collector.export_to(folder)
        assert guest.timeouts[-1] <= 10

    def test_an_exhausted_budget_skips_the_remaining_channels_and_says_so(
        self, guest, collector, folder, caplog
    ):
        collector.start()
        guest.call_cost = event_logs.STOP_BUDGET_S + 1
        with caplog.at_level(logging.WARNING):
            collector.export_to(folder)
        assert (folder / "sysmon/sysmon.xml").exists()
        assert not (folder / "aux/defender.xml").exists()
        assert "budget" in caplog.text


def base64_script(command: str) -> str:
    if "-EncodedCommand" not in command:
        return ""
    return base64.b64decode(command.rsplit(" ", 1)[1]).decode("utf-16-le")


class TestGuestAgent:
    class Http:
        def __init__(self):
            self.calls = []
            self.status_error = None

        def post(self, url, data=None, files=None, timeout=None):
            self.calls.append(SimpleNamespace(url=url, data=data, files=files, timeout=timeout))
            outer = self

            class Answer:
                def raise_for_status(self):
                    if outer.status_error:
                        raise outer.status_error

                def json(self):
                    return {"stdout": base64.b64encode(b"out").decode()}

            return Answer()

    def test_execute_posts_the_command_base64_encoded_and_decodes_stdout(self):
        http = self.Http()
        agent = event_logs.GuestAgent("192.168.150.10", http)
        assert agent.execute("C:/Windows/System32/reg.exe query", 12) == b"out"
        call = http.calls[0]
        assert call.url == "http://192.168.150.10:8000/execute"
        assert call.data == {"command": "C:/Windows/System32/reg.exe query", "encoding": "base64"}
        assert call.timeout == (event_logs.CONNECT_TIMEOUT_S, 12)

    def test_an_error_status_raises(self):
        http = self.Http()
        http.status_error = RuntimeError("500")
        with pytest.raises(RuntimeError):
            event_logs.GuestAgent("192.168.150.10", http).execute("x", 5)

    def test_store_uploads_the_file_to_the_given_guest_path(self):
        http = self.Http()
        event_logs.GuestAgent("192.168.150.10", http).store("C:\\Windows\\Temp\\c.xml", b"<x/>", 15)
        call = http.calls[0]
        assert call.url == "http://192.168.150.10:8000/store"
        assert call.data == {"filepath": "C:\\Windows\\Temp\\c.xml"}
        assert call.files["file"][1] == b"<x/>"
        assert call.timeout == (event_logs.CONNECT_TIMEOUT_S, 15)

    def test_remove_asks_the_agent_to_delete_the_path(self):
        http = self.Http()
        event_logs.GuestAgent("192.168.150.10", http).remove("C:\\Windows\\Temp\\c.xml", 15)
        assert http.calls[0].url == "http://192.168.150.10:8000/remove"
        assert http.calls[0].data == {"path": "C:\\Windows\\Temp\\c.xml"}


class TestAuxiliary:
    @pytest.fixture
    def auxiliary(self, guest, clock, monkeypatch, tmp_path, sysmon_config):
        monkeypatch.setattr(event_logs, "CUCKOO_ROOT", str(tmp_path / "cape"))
        monkeypatch.setattr(event_logs, "GuestAgent", lambda _ip: guest)
        monkeypatch.setattr(event_logs, "SystemClock", lambda: clock)
        monkeypatch.setattr(event_logs, "CHANNELS", channels_with_config(sysmon_config))
        module = event_logs.EventLogs()
        module.machine = SimpleNamespace(ip="192.168.150.10")
        module.task = SimpleNamespace(id=42)
        return module

    def test_it_is_a_cape_auxiliary(self):
        from lib.cuckoo.common.abstracts import Auxiliary  # noqa: PLC0415

        assert issubclass(event_logs.EventLogs, Auxiliary)

    def test_the_exports_land_in_the_analysis_folder_of_the_task(self, auxiliary, guest, tmp_path):
        auxiliary.start()
        guest.add_event(SYSMON, event_id=1)
        guest.add_event(DEFENDER, event_id=5007)
        auxiliary.stop()
        folder = tmp_path / "cape/storage/analyses/42"
        assert record_ids(folder / "sysmon/sysmon.xml") == [2]
        assert record_ids(folder / "aux/defender.xml") == [1]

    def test_start_and_stop_never_raise_because_cape_would_abort_the_task(
        self, auxiliary, monkeypatch
    ):
        def explode(self):
            raise RuntimeError("boom")

        monkeypatch.setattr(event_logs.EventLogCollector, "start", explode)
        monkeypatch.setattr(
            event_logs.EventLogCollector, "export_to", lambda self, _folder: explode(self)
        )
        auxiliary.start()
        auxiliary.stop()

    def test_stop_after_a_start_that_never_got_going_is_a_no_op(self, auxiliary, monkeypatch):
        monkeypatch.setattr(
            event_logs, "GuestAgent", lambda _ip: (_ for _ in ()).throw(RuntimeError("no ip"))
        )
        auxiliary.start()
        auxiliary.stop()

    def test_stop_without_start_is_a_no_op(self, auxiliary):
        auxiliary.stop()


class TestShipping:
    def test_the_dockerfile_copies_the_module_where_cape_loads_auxiliaries_owned_like_cape_files(
        self,
    ):
        dockerfile = (REPO / "cape/Dockerfile").read_text()
        module = "cape/auxiliary/event_logs.py"
        assert (
            f"COPY --chown=cape:cape {module} /opt/CAPEv2/modules/auxiliary/event_logs.py"
            in dockerfile
        )

    def test_the_dockerfile_copies_the_guest_profiles_the_module_reads_the_sysmon_config_from(self):
        dockerfile = (REPO / "cape/Dockerfile").read_text()
        assert "COPY guest/profiles/ /usr/local/lib/tartarus/profiles/" in dockerfile

    def test_the_module_is_enabled_in_the_custom_auxiliary_conf(self):
        conf = configparser.ConfigParser()
        conf.read(REPO / "cape/conf/auxiliary.conf")
        assert conf["event_logs"]["enabled"] == "yes"

    def test_the_guest_side_module_list_is_left_alone(self):
        conf = configparser.ConfigParser()
        conf.read(REPO / "cape/conf/auxiliary.conf")
        assert "auxiliary_modules" not in conf.sections()
        assert "sysmon_windows" not in conf["event_logs"]
