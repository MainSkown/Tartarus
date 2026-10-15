import pytest
from fixtures.leaks import has_child_processes, kill, processes_running_under

from guest_engine.sequencer import Sequencer


@pytest.fixture(autouse=True)
def nothing_outlives_its_test(tmp_path, monkeypatch):
    """Stop every build a test left active, then fail the test if a process of its folder lives.

    A step runs in a session of its own, so it outlives the test that started it (and pytest)
    unless the build is stopped: stub steps once sat in the process table for hours.
    """
    sequencers: list[Sequencer] = []
    original_init = Sequencer.__init__

    def recording_init(self, *arguments, **options):
        original_init(self, *arguments, **options)
        sequencers.append(self)

    monkeypatch.setattr(Sequencer, "__init__", recording_init)
    yield
    for sequencer in sequencers:
        sequencer.shutdown()
    leaked = processes_running_under(tmp_path) if has_child_processes() else {}
    if leaked:
        kill(list(leaked))
        pytest.fail("the test left processes running: " + "; ".join(leaked.values()))
