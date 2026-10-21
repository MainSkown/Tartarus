import pytest

from app.search.index import analysis_id_of_index, index_name


def test_the_analysis_id_is_read_back_from_its_index_name() -> None:
    assert analysis_id_of_index(index_name(42)) == 42


@pytest.mark.parametrize("name", ["other-index", "tartarus-events-", "tartarus-events-x1"])
def test_a_name_that_is_not_an_event_index_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="not an event index"):
        analysis_id_of_index(name)
