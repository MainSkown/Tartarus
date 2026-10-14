from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.rules.predicate import Predicate


class Validity(StrEnum):
    """`INVALID`: the rule is wrong. `UNSUPPORTED`: valid Sigma this engine cannot run."""

    VALID = "valid"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


class RuleProblem(Exception):  # noqa: N818 - carries a verdict about a rule, not a failure of ours
    """Raised inside the loading steps to say why a rule is not `VALID`; never leaves the loader."""

    def __init__(self, validity: Validity, reason: str) -> None:
        super().__init__(reason)
        self.validity = validity
        self.reason = reason


def invalid(reason: str) -> RuleProblem:
    return RuleProblem(Validity.INVALID, reason)


def unsupported(reason: str) -> RuleProblem:
    return RuleProblem(Validity.UNSUPPORTED, reason)


@dataclass(frozen=True)
class Rule:
    """One rule file as loaded. Only a `VALID` rule can match events."""

    id: str
    title: str
    description: str | None
    level: str | None
    status: str | None
    tags: tuple[str, ...]
    logsource_category: str | None
    path: Path
    content_sha256: str
    validity: Validity
    error: str | None = None
    references: tuple[str, ...] = ()
    condition: str | None = None
    predicate: Predicate | None = field(default=None, repr=False, compare=False)
