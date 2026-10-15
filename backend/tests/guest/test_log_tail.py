import pytest

from app.guest.log_tail import lines_after


@pytest.mark.parametrize(
    ("seen", "fetched", "expected"),
    [
        ([], ["a", "b"], ["a", "b"]),
        (["a", "b"], ["a", "b"], []),
        (["a", "b"], ["a", "b", "c"], ["c"]),
        (["a", "b", "c"], ["b", "c", "d", "e"], ["d", "e"]),
        (["a", "b"], [], []),
        (["a", "b"], ["x", "y"], ["x", "y"]),
        (["a", "a"], ["a", "a", "a"], ["a"]),
        (["a", "b", "a"], ["b", "a", "a"], ["a"]),
    ],
    ids=[
        "first fetch",
        "nothing new",
        "one appended",
        "window slid past the oldest",
        "empty fetch",
        "everything is new after a burst longer than the window",
        "a repeated line is told apart by position",
        "overlap is the longest suffix of the old window",
    ],
)
def test_lines_after_the_ones_already_seen(
    seen: list[str], fetched: list[str], expected: list[str]
) -> None:
    assert lines_after(seen, fetched) == expected
