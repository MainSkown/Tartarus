from app.desktop.admission import CLOSE_CONFLICT, CloseRequest
from app.desktop.resolver import AnalysisResolver, VncTarget
from app.desktop.tunnel import VNC_HOST
from tests.desktop.stubs import StubLookup, StubViewer, interactive_snapshot

FIRST_ANALYSIS, SECOND_ANALYSIS = 11, 12
FIRST_TASK, SECOND_TASK = 101, 102
FIRST_GUEST, SECOND_GUEST = "lab1", "lab3"
FIRST_PORT, SECOND_PORT = 5900, 5901


def two_analyses_on_two_guests() -> tuple[StubLookup, StubViewer]:
    lookup = StubLookup(
        {
            FIRST_ANALYSIS: interactive_snapshot(cape_task_id=FIRST_TASK, guest=FIRST_GUEST),
            SECOND_ANALYSIS: interactive_snapshot(cape_task_id=SECOND_TASK, guest=SECOND_GUEST),
        }
    )
    viewer = StubViewer(
        {
            FIRST_TASK: f"interactive=1,vnc_port={FIRST_PORT}",
            SECOND_TASK: f"interactive=1,vnc_port={SECOND_PORT}",
        },
        machines={FIRST_TASK: FIRST_GUEST, SECOND_TASK: SECOND_GUEST},
    )
    return lookup, viewer


async def target_of(
    analysis_id: int, lookup: StubLookup, viewer: StubViewer
) -> VncTarget | CloseRequest:
    resolver = AnalysisResolver(lookup, viewer, analysis_id)
    return await resolver.wait_for_target(poll_interval_s=0.005, patience_s=0.15)


async def test_each_of_two_analyses_on_two_guests_resolves_to_its_own_vnc_port() -> None:
    lookup, viewer = two_analyses_on_two_guests()

    assert await target_of(FIRST_ANALYSIS, lookup, viewer) == VncTarget(VNC_HOST, FIRST_PORT)
    assert await target_of(SECOND_ANALYSIS, lookup, viewer) == VncTarget(VNC_HOST, SECOND_PORT)


async def test_an_analysis_whose_task_ran_on_the_other_guest_is_refused_not_given_that_port() -> (
    None
):
    lookup, viewer = two_analyses_on_two_guests()
    viewer.machines[FIRST_TASK] = SECOND_GUEST

    assert await target_of(FIRST_ANALYSIS, lookup, viewer) == CloseRequest(
        CLOSE_CONFLICT, "desktop_machine_mismatch"
    )
    assert await target_of(SECOND_ANALYSIS, lookup, viewer) == VncTarget(VNC_HOST, SECOND_PORT)
