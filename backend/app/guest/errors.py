class GuestControlError(Exception):
    """Base of every failure of a call to the guest control service.

    Messages name the call and the kind of failure, never the URL or the token.
    """

    def __init__(self, call: str, detail: str) -> None:
        super().__init__(f"guest control {call}: {detail}")
        self.call = call


class GuestControlUnreachable(GuestControlError):
    """The service did not answer, answered with a server error, or refused the token."""

    def __init__(self, call: str, reason: str) -> None:
        super().__init__(call, f"unreachable ({reason})")


class GuestControlNotConfigured(GuestControlUnreachable):
    def __init__(self, call: str) -> None:
        super().__init__(call, "GUEST_CONTROL_TOKEN is not set")


class GuestControlRejected(GuestControlError):
    """The service understood the request and said no, with its own message.

    `fields` maps a parameter to what is wrong with it; it is filled for a 422.
    """

    def __init__(
        self, call: str, status: int, message: str, fields: dict[str, str] | None = None
    ) -> None:
        super().__init__(call, f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.fields = fields or {}


class GuestControlBadResponse(GuestControlError):
    """The service answered, but not in a shape this client understands."""

    def __init__(self, call: str, reason: str) -> None:
        super().__init__(call, f"unexpected response ({reason})")
