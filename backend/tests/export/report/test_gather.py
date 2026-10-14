import pytest

from app.annotations.validation import Target
from app.db import annotation_repository as repository
from app.db.models.annotation import TargetType
from app.export.report import gather
from app.export.report.key_events import KeyEventReason
from app.export.report.model import ReportInclude
from app.views.network import MAX_LIST_LIMIT
from tests.export.report.conftest import GENERATED_AT, Gathering


async def test_the_model_is_built_from_the_existing_views(gathering: Gathering) -> None:
    model = await gathering.run()

    assert model.header.analysis_id == gathering.analysis.id
    assert model.header.sample_name == "invoice.exe"
    assert model.header.md5 == "d" * 32
    assert model.header.generated_at == GENERATED_AT
    assert [group.ruleset for group in model.detections] == ["sigma", "cape"]
    assert [row.label for row in model.process_tree][:2] == [
        "explorer.exe (100)",
        "invoice.exe (4242)",
    ]
    assert model.techniques[0].id == "T1547.001"
    assert model.network.dns.items[0].query == "evil.example"
    assert {group.type.value for group in model.iocs} >= {"hash", "domain"}
    for name in ("tree", "detections", "attack"):
        assert gathering.calls[name] == [gathering.analysis.id]


async def test_the_files_are_read_from_the_storage_root_of_the_cape_task(
    gathering: Gathering,
) -> None:
    gathering.analysis.cape_task_id = 31

    await gathering.run()

    assert gathering.calls["files"] == [(gathering.storage_root, 31)]
    assert gathering.calls["iocs"][0].catalog.screenshots


async def test_the_network_view_is_asked_for_its_longest_lists_and_told_when_inetsim_routed(
    gathering: Gathering,
) -> None:
    await gathering.run()

    assert gathering.calls["network"] == [(gathering.analysis.id, True, MAX_LIST_LIMIT)]


async def test_a_run_not_routed_through_inetsim_is_not_simulated(gathering: Gathering) -> None:
    gathering.analysis.options = {**gathering.analysis.options, "route": "internet"}

    await gathering.run()

    assert gathering.calls["network"][0][1] is False


async def test_key_events_are_pooled_from_the_index_by_lane(gathering: Gathering) -> None:
    model = await gathering.run()

    reasons = {event.id: event.reason for event in model.key_events.events}
    assert reasons["proc-1"] is KeyEventReason.PROCESS
    assert reasons["file-1"] is KeyEventReason.FILE_OR_REGISTRY
    assert reasons["reg-1"] is KeyEventReason.FILE_OR_REGISTRY
    assert reasons["net-1"] is KeyEventReason.NETWORK
    assert "net-2" not in reasons
    assert "api-1" not in reasons
    lanes = [
        body["query"]["bool"]["filter"][0]["terms"]["tartarus.lane"]
        for body in gathering.index.lane_queries()
    ]
    assert sorted(lanes) == [["file", "registry"], ["network"], ["process"]]


async def test_the_lane_searches_are_time_ordered_and_bounded(gathering: Gathering) -> None:
    await gathering.run()

    for body in gathering.index.lane_queries():
        assert body["sort"][0] == {"@timestamp": "asc"}
        assert 0 < body["size"] <= gather.NETWORK_EVENT_POOL


async def test_network_events_inside_the_sandbox_network_are_left_out_of_the_search(
    gathering: Gathering,
) -> None:
    await gathering.run()

    network = next(
        body
        for body in gathering.index.lane_queries()
        if body["query"]["bool"]["filter"][0]["terms"]["tartarus.lane"] == ["network"]
    )
    assert {"term": {"destination.ip": "192.168.150.0/24"}} in network["query"]["bool"]["must_not"]


async def test_screenshots_are_read_in_order_with_their_media_types(gathering: Gathering) -> None:
    model = await gathering.run()

    assert [shot.n for shot in model.screenshots] == [1, 2]
    assert [shot.data_uri.split(";")[0] for shot in model.screenshots] == [
        "data:image/png",
        "data:image/jpeg",
    ]


async def test_a_screenshot_that_vanished_is_skipped_and_the_rest_keep_their_numbers(
    gathering: Gathering,
) -> None:
    gathering.screenshots[0].unlink()

    model = await gathering.run()

    assert [shot.n for shot in model.screenshots] == [2]


async def test_without_the_screenshots_option_no_file_is_read(
    gathering: Gathering, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(paths: object) -> list[object]:
        raise AssertionError("a screenshot was read")

    monkeypatch.setattr(gather, "read_screenshots", refuse)

    model = await gathering.run(ReportInclude(screenshots=False))

    assert model.screenshots == ()


async def annotate(gathering: Gathering) -> None:
    session, analysis_id = gathering.session, gathering.analysis.id
    await repository.add_tag(session, analysis_id, Target(TargetType.ANALYSIS), "phishing")
    await repository.add_tag(session, analysis_id, Target(TargetType.PROCESS, "4242"), "dropper")
    for target, body in [
        (Target(TargetType.ANALYSIS), "Looks like Emotet."),
        (Target(TargetType.PROCESS, "4242"), "The dropper."),
        (Target(TargetType.EVENT, "ev-dns"), "The beacon."),
        (Target(TargetType.EVENT, "ev-gone"), "Orphaned note."),
        (Target(TargetType.PROCESS, "999"), "Orphaned process."),
    ]:
        await repository.add_note(session, analysis_id, target, body)


def event_lookups(gathering: Gathering) -> list[list[str]]:
    """The ids of every id search that fetched event fields (the orphan check fetches none)."""
    return [
        body["query"]["ids"]["values"]
        for body in gathering.index.id_queries()
        if body["_source"] is not False
    ]


async def test_the_analysts_tags_and_notes_are_read_and_orphaned_notes_are_left_out(
    gathering: Gathering,
) -> None:
    await annotate(gathering)

    model = await gathering.run()

    assert model.tags == ("phishing",)
    assert [(group.title, group.notes) for group in model.notes] == [
        ("Analysis", ("Looks like Emotet.",)),
        ("Process invoice.exe (4242)", ("The dropper.",)),
        ("Event: dns lookup evil.example", ("The beacon.",)),
    ]


async def test_the_events_the_notes_are_about_are_fetched_once_and_orphans_are_not(
    gathering: Gathering,
) -> None:
    await annotate(gathering)

    await gathering.run()

    assert event_lookups(gathering) == [["ev-dns"]]


async def test_without_the_notes_option_the_tags_are_kept_and_no_note_event_is_looked_up(
    gathering: Gathering,
) -> None:
    await annotate(gathering)

    model = await gathering.run(ReportInclude(notes=False))

    assert model.tags == ("phishing",)
    assert model.notes == ()
    assert event_lookups(gathering) == []


async def test_progress_is_reported_in_steps_that_only_go_forward(gathering: Gathering) -> None:
    reported: list[tuple[str, int]] = []

    await gathering.run(progress=lambda step, percent: reported.append((step, percent)))

    percents = [percent for _, percent in reported]
    assert len(reported) >= 6
    assert percents == sorted(percents)
    assert len(set(percents)) == len(percents)
    assert percents[0] > 0
    assert percents[-1] < 100
    assert all(step for step, _ in reported)


async def test_a_failing_view_stops_the_gathering_with_its_error(
    gathering: Gathering, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(index: object, analysis_id: int) -> object:
        raise RuntimeError("the event store is down")

    monkeypatch.setattr(gather, "list_detections", broken)

    with pytest.raises(RuntimeError, match="event store is down"):
        await gathering.run()
