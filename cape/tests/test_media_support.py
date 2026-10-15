"""Helpers shared by the media tests: a scripted command runner."""

from collections.abc import Callable, Sequence

from guest_engine.media.commands import CommandResult

type Response = CommandResult | BaseException | Callable[[list[str]], CommandResult]


def ok(stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(0, stdout, stderr)


def failed(returncode: int, stderr: str = "", stdout: str = "") -> CommandResult:
    return CommandResult(returncode, stdout, stderr)


class ScriptedRunner:
    """Answers each command by the first rule whose words are a prefix of it; exit 0 otherwise."""

    def __init__(self, *rules: tuple[Sequence[str], Response]) -> None:
        self.rules = [(list(prefix), response) for prefix, response in rules]
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str], timeout: float | None = None) -> CommandResult:
        command = list(args)
        self.calls.append(command)
        for prefix, response in self.rules:
            if command[: len(prefix)] == prefix:
                if isinstance(response, BaseException):
                    raise response
                return response(command) if callable(response) else response
        return ok()

    def commands_named(self, program: str) -> list[list[str]]:
        return [call for call in self.calls if call[0] == program]
