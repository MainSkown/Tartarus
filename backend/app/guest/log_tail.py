from collections.abc import Sequence


def lines_after(seen: Sequence[str], fetched: Sequence[str]) -> list[str]:
    """The lines of `fetched`, a tail of the log, that come after the tail `seen` earlier.

    The control service answers with the last N lines and no offset, so what is new is found by
    the longest overlap between the end of `seen` and the start of `fetched`; this tells a repeated
    line from a new one by position. A burst longer than the tail leaves a gap that cannot be
    recovered.
    """
    for overlap in range(min(len(seen), len(fetched)), 0, -1):
        if list(seen[-overlap:]) == list(fetched[:overlap]):
            return list(fetched[overlap:])
    return list(fetched)
