class GuestNotFound(LookupError):
    """No guest, build or profile of that name."""


class InvalidParameters(ValueError):
    """A value is not acceptable; `fields` maps each parameter to why."""

    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__(", ".join(f"{name}: {reason}" for name, reason in fields.items()))
        self.fields = fields


class Conflict(RuntimeError):
    """The current state refuses the request; the message is shown to the analyst."""
