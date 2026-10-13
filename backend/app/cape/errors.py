class CapeError(Exception):
    """Base of every failure of a CAPE call. Messages name the call, never the token or the URL."""

    def __init__(self, call: str, detail: str) -> None:
        super().__init__(f"CAPE {call}: {detail}")
        self.call = call


class CapeNotConfigured(CapeError):
    def __init__(self) -> None:
        super().__init__("request", "CAPE_API_TOKEN is not set")


class CapeUnreachable(CapeError):
    """CAPE did not answer, or answered with a server error: worth retrying later."""

    def __init__(self, call: str, reason: str) -> None:
        super().__init__(call, f"unreachable ({reason})")


class CapeAuthError(CapeError):
    def __init__(self, call: str) -> None:
        super().__init__(call, "the API token was refused")


class CapeBadResponse(CapeError):
    """CAPE answered, but not in a shape this client understands."""

    def __init__(self, call: str, reason: str) -> None:
        super().__init__(call, f"unexpected response ({reason})")


class CapeRejected(CapeError):
    """CAPE understood the request and said no, with its own message."""

    def __init__(self, call: str, message: str) -> None:
        super().__init__(call, message)
        self.message = message


class CapeTaskNotFound(CapeRejected):
    def __init__(self, call: str, task_id: int, message: str) -> None:
        super().__init__(call, message)
        self.task_id = task_id
