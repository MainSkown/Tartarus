import pytest

from app.db import analysis_repository as repository
from app.guest.selftest_evidence import read_evidence
from app.guest.selftest_verdict import DnsLookup
from tests.integration.views.conftest import ViewStack
from tests.integration.views.helpers import add_analysis_without_index

pytestmark = pytest.mark.integration


async def test_the_real_benign_analysis_shows_every_signal_in_the_index(
    view_stack: ViewStack,
) -> None:
    async with view_stack.factory() as session:
        analysis = await repository.get_analysis(session, view_stack.analysis_id)
    assert analysis is not None

    evidence = await read_evidence(view_stack.index, analysis)

    assert evidence.process_count >= 2
    assert evidence.file_events > 0
    assert evidence.registry_events > 0
    # The real analysis recorded the lookup of the sample with an empty answer list.
    assert evidence.dns is DnsLookup.UNANSWERED


async def test_an_analysis_without_an_index_has_no_evidence(view_stack: ViewStack) -> None:
    bare = await add_analysis_without_index(view_stack)
    async with view_stack.factory() as session:
        analysis = await repository.get_analysis(session, bare)
    assert analysis is not None

    evidence = await read_evidence(view_stack.index, analysis)

    assert (evidence.process_count, evidence.file_events, evidence.registry_events) == (0, 0, 0)
    assert evidence.dns is DnsLookup.ABSENT
