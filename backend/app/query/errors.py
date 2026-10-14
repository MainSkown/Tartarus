from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QueryError:
    """A problem in the query text; `start` and `end` are character offsets, `end` exclusive."""

    start: int
    end: int
    message: str
    suggestion: str | None = None


class QuerySyntaxError(Exception):
    def __init__(self, error: QueryError) -> None:
        super().__init__(error.message)
        self.error = error
