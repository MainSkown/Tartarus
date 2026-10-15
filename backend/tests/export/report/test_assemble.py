import base64
from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.db.models.analysis import AnalysisStatus, Severity
from app.export.inputs import ExportAnnotations, ExportNote, TargetType
from app.export.report.assemble import (
    FLOW_ROWS,
    IOC_ROWS_PER_TYPE,
    IOC_SAMPLE_PER_TYPE,
    NETWORK_LIST_ROWS,
    ScreenshotFile,
    build_report_model,
)
from app.export.report.key_events import KeyEventReason
from app.export.report.model import ReportInclude
from app.schemas.views_findings import Ioc, IocsView, IocType
from tests.export.conftest import EVERY_TYPE, SAMPLE_MD5, SAMPLE_SHA1, SAMPLE_SHA256, make_ioc
from tests.export.report.fixtures import (
    JPEG_BYTES,
    PNG_BYTES,
    SAMPLE_NAME,
    at,
    facts,
    make_analysis,
    make_inputs,
    make_network,
)

EVERYTHING = ReportInclude()


def build(include: ReportInclude = EVERYTHING, **changes: object):
    return build_report_model(make_inputs(**changes), include)


def test_every_include_option_is_on_by_default() -> None:
    assert ReportInclude().model_dump() == {"notes": True, "screenshots": True, "raw_iocs": True}


def test_the_model_cannot_be_changed_once_built() -> None:
    with pytest.raises(ValidationError):
        build().header.sample_name = "other"  # type: ignore[misc]


def test_the_header_names_the_sample_and_the_run() -> None:
    header = build().header

    assert header.analysis_id == 7
    assert header.sample_name == SAMPLE_NAME
    assert header.sample_type == "PE32 executable (GUI) Intel 80386"
    assert (header.sha256, header.md5, header.sha1) == (SAMPLE_SHA256, SAMPLE_MD5, SAMPLE_SHA1)
    assert header.status is AnalysisStatus.DONE
    assert header.route == "inetsim"
    assert header.duration_s == 183
    assert (header.submitted_at, header.started_at, header.finished_at) == (
        at(0),
        at(2),
        at(185),
    )
    assert header.generated_at == at(3600)


def test_the_header_names_the_guest_the_analysis_ran_on() -> None:
    assert build().header.guest == "lab1"


def test_an_analysis_that_records_no_guest_has_none_in_its_header() -> None:
    options = {"route": "inetsim", "package": "auto", "timeout": 180}

    assert build(analysis=make_analysis(options=options)).header.guest is None


def test_a_sample_the_database_lost_leaves_the_md5_and_sha1_out() -> None:
    header = build(sample=None).header

    assert (header.md5, header.sha1) == (None, None)
    assert header.sha256 == SAMPLE_SHA256


def test_an_analysis_without_a_summary_still_builds() -> None:
    model = build(analysis=make_analysis(summary=None, score=None, max_severity=None))

    assert model.header.duration_s is None
    assert model.header.sample_type is None
    assert (model.score, model.max_severity) == (None, None)
    assert model.counts.files_written == 0


def test_score_severity_families_and_the_analysts_tags() -> None:
    model = build()

    assert (model.score, model.max_severity) == (7.5, Severity.HIGH)
    assert model.families == ("emotet",)
    assert model.tags == ("phishing", "tlp:amber")


def test_the_counts_come_from_the_views_and_the_summary() -> None:
    counts = build().counts

    assert (counts.events, counts.processes, counts.detections) == (13178, 4, 2)
    assert (counts.files_written, counts.registry_keys_written) == (4, 5)
    assert (counts.dns_queries, counts.hosts, counts.tcp_flows) == (1, 2, 3)


def test_each_technique_row_has_its_tactic_and_the_detections_that_raised_it() -> None:
    techniques = build().techniques

    assert [(t.id, t.name, t.tactic) for t in techniques] == [
        ("T1547.001", "Registry Run Keys / Startup Folder", "Persistence"),
        ("T1059", "Command and Scripting Interpreter", "Execution"),
        ("T9999", None, "Execution"),
    ]
    assert techniques[0].signatures == ("Run key written",)
    assert techniques[0].severity is Severity.HIGH
    assert techniques[2].signatures == ()


def test_the_process_tree_marks_the_sample_by_its_file_name() -> None:
    rows = build().process_tree

    sample = [row for row in rows if row.sample]
    assert [row.pid for row in sample] == [4242]
    assert [row.label for row in rows][:3] == [
        "explorer.exe (100)",
        "invoice.exe (4242)",
        "cmd.exe (4300)",
    ]
    assert next(row for row in rows if row.pid == 4300).injection_target


def test_the_sample_is_found_whatever_the_case_of_its_name() -> None:
    rows = build(analysis=make_analysis(filename="INVOICE.EXE", summary=None)).process_tree

    assert [row.pid for row in rows if row.sample] == [4242]


def test_no_process_is_marked_when_none_has_the_samples_name() -> None:
    rows = build(analysis=make_analysis(filename="other.exe", summary=None)).process_tree

    assert not any(row.sample for row in rows)


def test_key_events_gather_alerts_cited_events_and_the_pools_in_time_order() -> None:
    key_events = build().key_events

    reasons = {event.id: event.reason for event in key_events.events}
    assert reasons["det-1"] is KeyEventReason.ALERT
    assert reasons["proc-1"] is KeyEventReason.PROCESS
    assert reasons["file-1"] is KeyEventReason.FILE_OR_REGISTRY
    assert reasons["cited-0"] is KeyEventReason.CITED
    assert reasons["net-1"] is KeyEventReason.NETWORK
    times = [event.time for event in key_events.events]
    assert times == sorted(times)
    assert key_events.more_cited == {"det-1": 3}


def test_a_detection_lists_five_cited_events_and_how_many_more_it_cites() -> None:
    run_key, recon = (detection for group in build().detections for detection in group.detections)

    assert [event.id for event in run_key.cited_events] == [f"cited-{n}" for n in range(5)]
    assert run_key.more_events == 3
    assert [event.id for event in recon.cited_events] == ["cited-x"]
    assert recon.more_events == 0


def test_detections_stay_grouped_by_ruleset_in_the_views_order() -> None:
    groups = build().detections

    assert [group.ruleset for group in groups] == ["sigma", "cape"]
    assert groups[0].detections[0].techniques == ("T1547.001",)
    assert groups[0].detections[0].match == "registry.path: *\\Run\\*"


def test_the_network_section_keeps_the_views_lists_and_totals() -> None:
    network = build().network

    assert [row.query for row in network.dns.items] == ["evil.example"]
    assert network.http.items[0].url == "http://evil.example/a.php?x=1"
    assert network.hosts.items[0].host == "203.0.113.7"
    assert network.simulated


def test_flows_to_the_sandbox_gateway_are_left_out_and_the_total_counts_the_rest() -> None:
    network = build(network=make_network(flows=3, sandbox_flows=40)).network

    assert {row.destination_ip for row in network.flows.items} == {"203.0.113.7"}
    assert network.flows.total == 3


def test_the_flow_list_is_cut_but_its_total_is_kept() -> None:
    network = build(network=make_network(flows=FLOW_ROWS + 20)).network

    assert len(network.flows.items) == FLOW_ROWS
    assert network.flows.total == FLOW_ROWS + 20


def test_the_dns_list_is_cut_to_the_row_limit_with_the_views_total() -> None:
    view = make_network(dns=NETWORK_LIST_ROWS + 30)

    network = build(network=view).network

    assert len(network.dns.items) == NETWORK_LIST_ROWS
    assert network.dns.total == NETWORK_LIST_ROWS + 30


def test_iocs_are_grouped_by_type_in_the_views_order_with_their_totals() -> None:
    groups = build().iocs

    assert [(group.type, group.total) for group in groups] == [
        (IocType.HASH, 2),
        (IocType.DOMAIN, 1),
        (IocType.IP, 2),
        (IocType.URL, 1),
        (IocType.MUTEX, 1),
        (IocType.REGISTRY, 1),
        (IocType.FILE, 1),
    ]
    assert groups[0].shown[0].value == EVERY_TYPE[0].value
    assert all(group.more == 0 for group in groups)


def test_a_type_with_no_indicator_has_no_group() -> None:
    only_domains = IocsView(iocs=[make_ioc(IocType.DOMAIN, "a.example")], truncated_types=[])

    groups = build(iocs=only_domains).iocs

    assert [group.type for group in groups] == [IocType.DOMAIN]


def test_the_types_the_view_truncated_are_flagged_on_their_group() -> None:
    groups = build().iocs

    assert [group.type for group in groups if group.truncated] == [IocType.FILE]


def many(count: int) -> IocsView:
    iocs: list[Ioc] = [make_ioc(IocType.DOMAIN, f"d{n}.example") for n in range(count)]
    return IocsView(iocs=iocs, truncated_types=[])


def test_with_raw_iocs_a_type_lists_up_to_its_row_limit() -> None:
    [group] = build(iocs=many(IOC_ROWS_PER_TYPE + 30)).iocs

    assert len(group.shown) == IOC_ROWS_PER_TYPE
    assert group.total == IOC_ROWS_PER_TYPE + 30
    assert group.more == 30


def test_without_raw_iocs_a_type_shows_its_count_and_a_short_sample() -> None:
    [group] = build(ReportInclude(raw_iocs=False), iocs=many(40)).iocs

    assert [ioc.value for ioc in group.shown] == [
        f"d{n}.example" for n in range(IOC_SAMPLE_PER_TYPE)
    ]
    assert (group.total, group.more) == (40, 40 - IOC_SAMPLE_PER_TYPE)


def test_screenshots_become_data_uris_in_order_with_their_original_bytes() -> None:
    shots = build().screenshots

    assert [shot.n for shot in shots] == [1, 2]
    assert shots[0].data_uri == "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode()
    assert shots[1].data_uri.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(shots[1].data_uri.split(",", 1)[1]) == JPEG_BYTES


def test_screenshots_are_ordered_by_their_number_not_the_order_given() -> None:
    shuffled = [ScreenshotFile(2, "image/png", b"b"), ScreenshotFile(1, "image/png", b"a")]

    shots = build(screenshots=shuffled).screenshots

    assert [shot.n for shot in shots] == [1, 2]


def test_without_the_screenshots_option_none_is_embedded() -> None:
    model = build(ReportInclude(screenshots=False))

    assert model.screenshots == ()
    assert model.include.screenshots is False


def test_notes_are_grouped_by_target_the_analysis_first_then_processes_then_events() -> None:
    groups = build().notes

    assert [(group.target_type, group.title) for group in groups] == [
        (TargetType.ANALYSIS, "Analysis"),
        (TargetType.PROCESS, "Process invoice.exe (4242)"),
        (TargetType.EVENT, "Event: dns lookup evil.example"),
    ]
    assert groups[1].notes == ("Spawns the DNS lookups.", "Second note on the dropper.")
    assert groups[2].detail == "ev-dns"


def test_process_notes_are_ordered_by_pid_as_numbers_and_event_notes_by_event_time() -> None:
    annotations = ExportAnnotations(
        notes=(
            ExportNote("e-late", TargetType.EVENT, "ev-late"),
            ExportNote("p-100", TargetType.PROCESS, "100"),
            ExportNote("e-early", TargetType.EVENT, "ev-early"),
            ExportNote("p-9", TargetType.PROCESS, "9"),
        )
    )
    note_events = {
        "ev-late": facts("ev-late", 90, "api"),
        "ev-early": facts("ev-early", 10, "api"),
    }

    groups = build(annotations=annotations, note_events=note_events).notes

    assert [group.notes[0] for group in groups] == ["p-9", "p-100", "e-early", "e-late"]


def test_a_note_on_a_process_or_event_the_report_does_not_know_still_has_a_title() -> None:
    annotations = ExportAnnotations(
        notes=(
            ExportNote("gone pid", TargetType.PROCESS, "9"),
            ExportNote("gone event", TargetType.EVENT, "ev-x"),
        )
    )

    groups = build(annotations=annotations, note_events={}).notes

    assert [group.title for group in groups] == ["Process 9", "Event ev-x"]


def test_without_the_notes_option_the_notes_go_but_the_tags_stay() -> None:
    model = build(ReportInclude(notes=False))

    assert model.notes == ()
    assert model.tags == ("phishing", "tlp:amber")
    assert model.include.notes is False


def test_every_other_section_is_the_same_whatever_the_include_options() -> None:
    everything = build(EVERYTHING)
    nothing = build(ReportInclude(notes=False, screenshots=False, raw_iocs=False))

    assert nothing.header == everything.header
    assert nothing.techniques == everything.techniques
    assert nothing.process_tree == everything.process_tree
    assert nothing.key_events == everything.key_events
    assert nothing.detections == everything.detections


def test_an_analysis_with_no_events_in_any_pool_still_lists_its_alerts() -> None:
    model = build_report_model(
        replace(
            make_inputs(),
            process_events=[],
            file_and_registry_events=[],
            network_events=[],
            note_events={},
        ),
        EVERYTHING,
    )

    assert {event.reason for event in model.key_events.events} == {
        KeyEventReason.ALERT,
        KeyEventReason.CITED,
    }
