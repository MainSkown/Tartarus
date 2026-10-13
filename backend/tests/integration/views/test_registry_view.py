import pytest

from tests.integration.views.conftest import ViewStack
from tests.integration.views.fixture_events import BENIGN_PID
from tests.integration.views.helpers import add_analysis_without_index, get_view

pytestmark = pytest.mark.integration


async def test_the_created_key_and_the_value_set_under_it_form_one_group(
    view_stack: ViewStack,
) -> None:
    registry = await get_view(view_stack, "registry")

    assert registry["total"] == 2
    [group] = registry["keys"]
    assert (group["hive"], group["key"]) == ("HKCU", r"Software\Tartarus")
    created, value_set = group["changes"]
    assert created["action"] == "reg-key-created"
    assert created["value_name"] is None
    assert created["data"] == []
    assert value_set["action"] == "reg-value-set"
    assert value_set["value_name"] == "SelfTest"
    assert value_set["data_type"] == "REG_SZ"
    assert value_set["data"] == ["benign"]
    assert value_set["process"] == {"pid": BENIGN_PID, "name": "benign.exe"}
    assert created["time"] <= value_set["time"]


async def test_an_unknown_analysis_is_a_404(view_stack: ViewStack) -> None:
    response = await view_stack.client.get("/api/analyses/99999/registry")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_an_analysis_without_an_index_has_no_registry_changes(
    view_stack: ViewStack,
) -> None:
    bare = await add_analysis_without_index(view_stack)

    assert await get_view(view_stack, "registry", bare) == {"keys": [], "total": 0}
