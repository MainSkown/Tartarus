"""What outlives one SMB connection: a host's files and services, per lan session.

A real file server keeps a dropped file for the next connection, and a malware that writes to ADMIN$
on one connection and creates its service on another expects that. The state is memory only, bound
by one `Budget` per session, and `forget` frees it when the daemon says the session is closed.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from lan_sim.services.smb_services import ServiceTable
from lan_sim.services.smb_store import Budget, VirtualShare, new_share


@dataclass
class HostState:
    budget: Budget
    shares: dict[str, VirtualShare] = field(default_factory=dict)
    services: ServiceTable = field(default_factory=ServiceTable)

    def share(self, name: str, now: int) -> VirtualShare:
        key = name.upper()
        if key not in self.shares:
            self.shares[key] = new_share(name, self.budget, now=now)
        return self.shares[key]


@dataclass
class _SessionState:
    budget: Budget
    hosts: dict[str, HostState] = field(default_factory=dict)


class SmbStates:
    def __init__(self, budget_factory: Callable[[], Budget] = Budget) -> None:
        self._budget_factory = budget_factory
        self._sessions: dict[str, _SessionState] = {}

    def host(self, session_key: str, fqdn: str) -> HostState:
        session = self._sessions.get(session_key)
        if session is None:
            session = self._sessions[session_key] = _SessionState(self._budget_factory())
        return session.hosts.setdefault(fqdn, HostState(session.budget))

    def forget(self, session_key: str) -> None:
        self._sessions.pop(session_key, None)

    def has_session(self, session_key: str) -> bool:
        return session_key in self._sessions
