"""Every number that bounds what a client can make the daemon do, in one place.

The values come from the flood measurements of the fake LAN spike (`docs/history/fake-lan-notes/
step0-notes.md`, case 5). Tests build a `Limits` with small values instead of patching constants.
"""

from dataclasses import dataclass

KIB = 1024
MIB = 1024 * KIB


@dataclass(frozen=True)
class Limits:
    # What reaches the log
    max_events_per_second: int = 200
    full_events_per_service: int = 200
    max_events_per_session: int = 20_000
    max_log_bytes_per_session: int = 8 * MIB
    max_aggregate_usernames: int = 50
    max_aggregate_secrets: int = 5
    max_aggregate_username_length: int = 64
    max_aggregate_secret_length: int = 1024

    # How long a logged string may be
    max_identity_length: int = 256
    max_path_length: int = 1024
    max_secret_length: int = 4096

    # What one connection may do
    max_bytes_read_per_connection: int = 64 * KIB
    idle_timeout_seconds: float = 30.0
    max_connection_seconds: float = 300.0

    # How many connections may be open
    max_connections_per_source_service: int = 32
    max_connections_per_session: int = 512
