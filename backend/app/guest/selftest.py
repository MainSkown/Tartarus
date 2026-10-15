"""The self-test a build job runs once the control service has built the guest.

The job only needs a verdict; how it is reached (an analysis of the bundled sample, the EICAR and
giveaway checks) is the runner's own business.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.jobs.runner import ProgressReporter


@dataclass(frozen=True)
class SelfTestVerdict:
    """`details` is stored in the guest's record as its last self-test; a failing verdict says
    what failed in `details["message"]`, which becomes the failed job's reason."""

    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


class SelfTestRunner(Protocol):
    async def run(
        self, guest_name: str, build_id: str, report_progress: ProgressReporter
    ) -> SelfTestVerdict | None:
        """Tests the guest, which is `testing`. `None` means no verdict: the guest stays `testing`.

        `report_progress` takes a step and 0..100, the self-test's own share of the job.
        """
        ...


class NoSelfTest:
    """Gives no verdict, so a built guest stays `testing` and is never offered for an analysis."""

    async def run(
        self,
        guest_name: str,  # noqa: ARG002 - the protocol's signature
        build_id: str,  # noqa: ARG002
        report_progress: ProgressReporter,  # noqa: ARG002
    ) -> SelfTestVerdict | None:
        return None
