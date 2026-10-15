import json
import re
import stat
from datetime import UTC, datetime

import pytest
from fixtures.profile_samples import sample_profile

from guest_engine.builds import BuildRecord, BuildStore, StepState, timestamp
from guest_engine.errors import GuestNotFound
from guest_engine.profile import PipelineStep

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def entry(step, weight=1, timeout_s=60, desktop=False):
    return PipelineStep(step=step, desktop=desktop, timeout_s=timeout_s, weight=weight)


@pytest.fixture
def store(tmp_path):
    return BuildStore(tmp_path / "guests")


def new_build(store, guest="alpha", pipeline=None):
    pipeline = pipeline or [entry("one"), entry("two", weight=3, desktop=True)]
    (store.root / guest).mkdir(parents=True, exist_ok=True)
    return store.create(guest, "build", pipeline, now=NOW)


# --- the record --------------------------------------------------------------------------


def test_a_new_build_is_running_at_its_first_step_with_every_step_pending(store):
    build = new_build(store)

    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", build.id)
    assert (build.guest, build.kind, build.status, build.step) == ("alpha", "build", "running", 0)
    assert [(s.name, s.status, s.weight, s.desktop) for s in build.steps] == [
        ("one", "pending", 1, False),
        ("two", "pending", 3, True),
    ]
    assert build.created == build.updated == "2026-10-15T12:00:00Z"
    assert (build.message, build.pause) == ("", None)


def test_the_pipeline_is_frozen_into_the_record(store):
    pipeline = [entry("slow", timeout_s=900, weight=7)]

    build = new_build(store, pipeline=pipeline)

    assert (build.steps[0].timeout_s, build.steps[0].weight) == (900, 7)


def test_the_record_round_trips_through_the_disk(store):
    build = new_build(store)
    build.steps[0].status = "succeeded"
    build.pause = {"instructions": "click"}
    store.save(build, now=NOW)

    assert store.load(build.id) == build


def test_the_stored_json_has_the_fields_the_engine_protocol_promises(store):
    build = new_build(store)

    data = json.loads((store.directory(build) / "build.json").read_text())

    assert {"id", "guest", "kind", "status", "step", "steps", "percent", "message", "pause"} <= set(
        data
    )
    assert set(data["steps"][0]) >= {"name", "status", "started", "finished", "exit_code"}


def test_saving_stamps_the_update_time(store):
    build = new_build(store)
    later = datetime(2026, 10, 15, 12, 5, tzinfo=UTC)

    store.save(build, now=later)

    assert store.load(build.id).updated == "2026-10-15T12:05:00Z"


def test_the_record_is_private_to_the_service_and_replaced_atomically(store):
    build = new_build(store)

    mode = stat.S_IMODE((store.directory(build) / "build.json").stat().st_mode)

    assert mode == 0o600
    assert not list(store.directory(build).glob(".*.tmp"))


# --- percent -----------------------------------------------------------------------------


def record_with(*states):
    return BuildRecord(
        id="b",
        guest="g",
        kind="build",
        status="running",
        step=0,
        steps=list(states),
        created="t",
        updated="t",
    )


def step_state(status="pending", weight=1, progress=0):
    return StepState(name="s", status=status, weight=weight, timeout_s=1, progress=progress)


def test_percent_is_the_weight_done_of_the_total_weight():
    build = record_with(step_state("succeeded", 1), step_state("pending", 3))

    assert build.percent == 25


def test_the_running_step_counts_by_its_own_progress():
    build = record_with(step_state("succeeded", 1), step_state("running", 3, progress=50))

    assert build.percent == 62  # (1 + 1.5) / 4


def test_a_paused_step_counts_by_its_progress_too():
    build = record_with(step_state("paused", 4, progress=25))

    assert build.percent == 25


def test_a_failed_step_adds_nothing():
    assert (
        record_with(step_state("succeeded", 1), step_state("failed", 1, progress=90)).percent == 50
    )


def test_a_succeeded_build_is_one_hundred_percent():
    build = record_with(step_state("succeeded", 2), step_state("succeeded", 3))
    build.status = "succeeded"

    assert build.percent == 100


def test_percent_is_never_over_one_hundred_or_below_zero():
    assert record_with(step_state("running", 1, progress=100)).percent == 100
    assert record_with(step_state("pending", 1)).percent == 0


# --- finding builds ----------------------------------------------------------------------


def test_a_build_is_found_by_its_id_wherever_its_guest_is(store):
    first = new_build(store, "alpha")
    second = new_build(store, "bravo")

    assert store.load(second.id).guest == "bravo"
    assert store.load(first.id).guest == "alpha"


def test_two_builds_never_share_an_id(store):
    assert len({new_build(store).id for _ in range(50)}) == 50


@pytest.mark.parametrize("build_id", ["nope", "../alpha", "a/b", "", "x" * 65, ".."])
def test_an_unknown_or_malformed_id_is_not_found(store, build_id):
    new_build(store)

    with pytest.raises(GuestNotFound):
        store.load(build_id)


def test_all_lists_every_build_and_those_of_one_guest(store):
    a = new_build(store, "alpha")
    b = new_build(store, "bravo")

    assert {build.id for build in store.all()} == {a.id, b.id}
    assert [build.id for build in store.of_guest("bravo")] == [b.id]


def test_an_unreadable_build_file_is_skipped_not_fatal(store):
    good = new_build(store, "alpha")
    bad = new_build(store, "bravo")
    (store.directory(bad) / "build.json").write_text("{broken")

    assert [build.id for build in store.all()] == [good.id]


def test_the_active_build_is_the_one_running_or_paused(store):
    finished = new_build(store, "alpha")
    finished.status = "succeeded"
    store.save(finished, now=NOW)
    failed = new_build(store, "bravo")
    failed.status = "failed"
    store.save(failed, now=NOW)
    assert store.active() is None

    paused = new_build(store, "charlie")
    paused.status = "paused"
    store.save(paused, now=NOW)
    assert store.active().id == paused.id


# --- the log -----------------------------------------------------------------------------


def test_the_log_is_appended_and_read_back_by_tail(store):
    build = new_build(store)
    for number in range(10):
        store.append_log(build, f"line {number}")

    assert store.tail(build.id, 3) == ["line 7", "line 8", "line 9"]
    assert len(store.tail(build.id, 100)) == 10


def test_a_build_without_a_log_yet_has_an_empty_tail(store):
    assert store.tail(new_build(store).id, 5) == []


def test_a_log_line_with_a_newline_cannot_forge_a_second_line(store):
    build = new_build(store)

    store.append_log(build, "first\nsecond")

    assert store.tail(build.id, 10) == ["first second"]


def test_the_timestamp_format_is_the_registrys():
    assert timestamp(NOW) == "2026-10-15T12:00:00Z"
    assert timestamp(None).endswith("Z")


def test_a_conditional_pipeline_is_frozen_as_resolved_for_the_options_asked(store):
    profile = sample_profile("windows")
    off = profile.build_pipeline("installer", {"defender": False})
    on = profile.build_pipeline("installer", {"defender": True})

    assert "tamper-off" in [s.name for s in new_build(store, "alpha", off).steps]
    assert "tamper-off" not in [s.name for s in new_build(store, "bravo", on).steps]


# --- the step's process -------------------------------------------------------------------


def test_a_new_build_has_no_step_process(store):
    build = new_build(store)

    assert (build.step_pid, build.step_path) == (None, None)


def test_the_step_process_round_trips_through_the_disk(store):
    build = new_build(store)
    build.step_pid, build.step_path = 4242, "/steps/define"
    store.save(build, now=NOW)

    loaded = store.load(build.id)

    assert (loaded.step_pid, loaded.step_path) == (4242, "/steps/define")
    assert json.loads((store.directory(build) / "build.json").read_text())["step_pid"] == 4242


def test_a_record_written_before_the_step_process_was_kept_still_loads(store):
    build = new_build(store)
    file = store.directory(build) / "build.json"
    data = json.loads(file.read_text())
    del data["step_pid"], data["step_path"]
    file.write_text(json.dumps(data))

    loaded = store.load(build.id)

    assert (loaded.step_pid, loaded.step_path) == (None, None)
