"""When an interactive run ends, as far as the analyst's clock is concerned.

CAPE cannot change a running task's timeout, so the backend ends an interactive run itself at
the deadline. CAPE's own timeout (`MAX_RUN_S`) counts from the sample's execution in the guest,
which is 20 to 25 s after `started_at`: measured, its timer fired no earlier than
`started_at + 1222 s`. Capping the deadline at `started_at + MAX_RUN_S` keeps the backend
ahead of it.
"""

from datetime import datetime, timedelta

MAX_RUN_S = 1200


def latest_deadline(started_at: datetime) -> datetime:
    return started_at + timedelta(seconds=MAX_RUN_S)


def initial_deadline(monitor_seen_at: datetime, started_at: datetime, timeout_s: int) -> datetime:
    return min(monitor_seen_at + timedelta(seconds=timeout_s), latest_deadline(started_at))


def extended_deadline(current: datetime, started_at: datetime, seconds: int) -> datetime:
    return min(current + timedelta(seconds=seconds), latest_deadline(started_at))


def at_the_latest(current: datetime, started_at: datetime) -> bool:
    return current >= latest_deadline(started_at)
