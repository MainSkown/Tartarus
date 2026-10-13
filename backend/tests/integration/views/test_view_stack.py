import pytest

from tests.integration.views.conftest import ViewStack

pytestmark = pytest.mark.integration


async def test_the_view_stack_has_a_done_analysis_with_events(view_stack: ViewStack) -> None:
    response = await view_stack.index.search(view_stack.analysis_id, {"size": 0})

    assert response["hits"]["total"]["value"] > 400
