import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from app.db.models.job import ACTIVE_JOB_STATUSES
from app.ws.messages import JobMessage


@dataclass(frozen=True)
class Subscription:
    snapshot: list[JobMessage]
    inbox: asyncio.Queue[JobMessage]


class JobFeed:
    """Fans every job change out to the connected `/ws/system` clients.

    Remembers the latest message of each active job, so a client that connects mid-job is told
    about it. Not thread-safe: publish and subscribe from the event loop.
    """

    def __init__(self) -> None:
        self._active: dict[int, JobMessage] = {}
        self._inboxes: set[asyncio.Queue[JobMessage]] = set()

    def publish(self, message: JobMessage) -> None:
        if message.job.status in ACTIVE_JOB_STATUSES:
            self._active[message.job.id] = message
        else:
            self._active.pop(message.job.id, None)
        for inbox in self._inboxes:
            inbox.put_nowait(message)

    @contextmanager
    def subscribe(self) -> Iterator[Subscription]:
        inbox: asyncio.Queue[JobMessage] = asyncio.Queue()
        self._inboxes.add(inbox)
        try:
            yield Subscription(list(self._active.values()), inbox)
        finally:
            self._inboxes.discard(inbox)
