from dataclasses import dataclass
from typing import Any

import re2

from app.rules.rule import invalid


@dataclass(frozen=True)
class RegexLimits:
    """What a rule's regular expressions may cost; see decision 10 of the M4 plan.

    RE2 runs in time linear in the input, so the input cap bounds the time per match and the
    other two bound the cost of compiling.
    """

    max_pattern_length: int = 4096
    max_program_bytes: int = 1 << 20
    max_input_length: int = 32768


DEFAULT_LIMITS = RegexLimits()


def compile_regex(pattern: str, limits: RegexLimits) -> Any:
    if len(pattern) > limits.max_pattern_length:
        raise invalid(
            f"regular expression pattern has {len(pattern)} characters, "
            f"over the limit of {limits.max_pattern_length}"
        )
    options = re2.Options()
    options.max_mem = limits.max_program_bytes
    options.log_errors = False
    try:
        return re2.compile(pattern, options)
    except re2.error as error:
        raise invalid(f"regular expression cannot be compiled: {_message(error)}") from error


def _message(error: Exception) -> str:
    detail = error.args[0] if error.args else error
    return detail.decode(errors="replace") if isinstance(detail, bytes) else str(detail)
