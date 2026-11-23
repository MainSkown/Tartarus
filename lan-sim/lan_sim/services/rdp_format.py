"""What the RDP wire parsers share: the error for malformed input and the stream-reading type."""

from collections.abc import Awaitable, Callable

ReadExactly = Callable[[int], Awaitable[bytes]]


class RdpFormatError(ValueError):
    """The bytes are not an RDP message this server accepts; the text never carries client bytes."""
