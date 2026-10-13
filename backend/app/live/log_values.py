from datetime import datetime, timedelta
from typing import Any

_POINTER_TAGS = frozenset({"p", "h"})
_WORD_MASK = 2**64 - 1
_LOW_WORD_MASK = 2**32 - 1
_FILETIME_EPOCH = datetime(1601, 1, 1)
_TICKS_PER_MICROSECOND = 10
_PLAIN_WHITESPACE = "\t\r\n"


def hex_word(value: int) -> str:
    return f"0x{value & _WORD_MASK:08x}"


def render_text(raw: bytes | str) -> str:
    text = raw if isinstance(raw, str) else _decode_bytes(raw)
    return "".join(_escaped(char) for char in text)


def render_argument(raw: Any, tag: str | None = None) -> str:
    """Render a logged argument the way CAPE's report prints it.

    Integers are unsigned 64-bit words (a negative one wraps), except pointer and handle tags,
    which print as hex padded to eight digits (a negative one keeps its low 32 bits).
    """
    if isinstance(raw, bytes | str):
        return render_text(raw)
    if isinstance(raw, list):
        return " ".join(render_argument(item) for item in raw)
    if raw is None:
        return ""
    if isinstance(raw, int):
        return _render_integer(int(raw), tag)
    return str(raw)


def render_return(raw: Any) -> str:
    if isinstance(raw, int):
        return hex_word(int(raw))
    return render_argument(raw)


def clock_text(moment: datetime) -> str:
    return f"{moment:%Y-%m-%d %H:%M:%S},{moment.microsecond // 1000:03d}"


def filetime_to_datetime(low: int, high: int) -> datetime:
    """A Windows FILETIME given as two 32-bit halves, as a timezone-less wall time."""
    ticks = (low & _LOW_WORD_MASK) | ((high & _LOW_WORD_MASK) << 32)
    return _FILETIME_EPOCH + timedelta(microseconds=ticks // _TICKS_PER_MICROSECOND)


def _render_integer(value: int, tag: str | None) -> str:
    if tag not in _POINTER_TAGS:
        return str(value & _WORD_MASK)
    return f"0x{value & _LOW_WORD_MASK:08x}" if value < 0 else f"0x{value:08x}"


def _decode_bytes(raw: bytes) -> str:
    try:
        return raw.decode()
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _escaped(char: str) -> str:
    if " " <= char <= "~" or char in _PLAIN_WHITESPACE:
        return char
    return f"\\x{ord(char):02x}"
