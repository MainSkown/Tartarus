"""What the control service (`bin/guest-control`) needs from the guest engine.

The control service only translates HTTP to these calls and the engine's exceptions to status
codes (`GuestNotFound` 404, `InvalidParameters` 422, `Conflict` 409; the self-test's
`SampleBuildFailed` and `ChecksFailed`, in `guest_engine.selftest`, 500 and 502). Every value
crossing this boundary is JSON-serialisable (dicts, lists, strings, numbers, booleans, None), so
the service does no conversion.
"""

from typing import Any, Protocol

type Json = dict[str, Any]


class GuestEngine(Protocol):
    def profiles(self) -> list[Json]:
        """Every installed guest profile: id, name, family, option schema, name rules, badges."""
        ...

    def media(self) -> list[Json]:
        """Installation media under `/data/iso`, each tagged with the profile that recognised it."""
        ...

    def guests(self) -> list[Json]:
        """Every guest's record: name, profile, media, options, resources, ip, state, self-test."""
        ...

    def guest(self, name: str) -> Json: ...

    def guest_address(self, name: str) -> Json:
        """`{ip, agent_port, finish_dir}`: where `guest-control` reaches this guest's agent."""
        ...

    def delete_guest(self, name: str) -> None: ...

    def start_build(self, params: Json) -> str:
        """Validate `params` (decision 3), start a build and return its build id."""
        ...

    def start_clone(self, source: str, params: Json) -> str: ...

    def build(self, build_id: str) -> Json:
        """`{id, guest, kind, status, step, steps, percent, message, pause}`; `status` is one of
        `running`, `paused`, `failed`, `succeeded`; `pause` is `{instructions}` or None."""
        ...

    def build_log(self, build_id: str, tail: int) -> list[str]: ...

    def resume(self, build_id: str) -> None: ...

    def restart(self, build_id: str) -> None: ...

    def cancel(self, build_id: str) -> None:
        """End a running or paused build as failed ("cancelled"), once its step process is gone.
        Its guest becomes `failed` like any failed build's and can be deleted."""
        ...

    def continue_after_pause(self, build_id: str) -> None: ...

    def complete_build(self, build_id: str, passed: bool, selftest: Json) -> None:
        """The backend's self-test verdict: a passed guest becomes `ready`, a failed one `failed`
        and is unregistered; the verdict is stored in the guest's record."""
        ...

    def check(self, name: str) -> Json:
        """Run the guest's health checks now: `{name, checks: [{id, ok, message}]}`."""
        ...

    def selftest_sample(self, name: str) -> Json:
        """`{path, filename}`: the built benign sample of the guest's profile, ready to serve."""
        ...

    def selftest_checks(self, name: str) -> Json:
        """Run the guest-side self-test checks: `{facts, giveaways, proofs, log}`. Takes minutes."""
        ...

    def display(self, name: str) -> Json | None:
        """`{host, port}` of the guest's VNC display inside the container while it runs, or None."""
        ...

    def shutdown(self) -> None:
        """Stop the step a build is running and leave that build failed, to be resumed after a
        restart. Called once when the service is told to stop; safe when idle and when repeated."""
        ...
