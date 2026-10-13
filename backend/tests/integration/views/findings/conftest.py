import pytest

from app.api.views_findings import get_cape_storage_path
from tests.integration.views.conftest import ViewStack


@pytest.fixture
def stack(view_stack: ViewStack) -> ViewStack:
    """The view stack with the endpoints reading CAPE files from its temporary storage."""
    view_stack.app.dependency_overrides[get_cape_storage_path] = lambda: view_stack.storage_root
    return view_stack
