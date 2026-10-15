"""A guest's health checks (the cape-integration spec's "Guest health") and their probes.

VM defined, snapshot present and CAPE registration come from libvirt and from CAPE's own machine
list. The agent check restores the snapshot, which is slow and disturbs the guest, so it runs on
demand only and is an injected callable like the machine list probe.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from guest_engine.config import AgentCheck, MachinesProbe
from guest_engine.host import Host, HostError
from guest_engine.profile import Profile
from guest_engine.registry import Guest

HTTP_TIMEOUT_S = 10
AGENT_TIMEOUT_S = 120
AGENT_POLL_S = 5
AGENT_STATUS_PATH = "/status"
HTTP_OK = 200

type Fetch = Callable[[str, Mapping[str, str], float], bytes]
type Check = dict[str, Any]


def labels_from_machines_list(payload: object) -> list[str]:
    """The machine labels in CAPE's `apiv2/machines/list/` answer; another shape lists none."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    return [
        machine["label"]
        for machine in data
        if isinstance(machine, dict) and isinstance(machine.get("label"), str)
    ]


def _http_get(url: str, headers: Mapping[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, headers=dict(headers))  # noqa: S310 - CAPE's own http URL
    with urllib.request.urlopen(request, timeout=timeout) as answer:  # noqa: S310
        return answer.read()


class CapeMachinesProbe:
    """The labels CAPE lists. The token goes in a header, never on a command line."""

    def __init__(self, api_url: str, token: str, fetch: Fetch = _http_get) -> None:
        self._url = f"{api_url.rstrip('/')}/apiv2/machines/list/"
        self._headers = {"Authorization": f"Token {token}"}
        self._fetch = fetch

    def __call__(self) -> list[str]:
        body = self._fetch(self._url, self._headers, HTTP_TIMEOUT_S)
        try:
            return labels_from_machines_list(json.loads(body))
        except json.JSONDecodeError as error:
            raise ValueError(f"CAPE's machine list is not JSON ({error})") from None


def _http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as answer:  # noqa: S310 - the guest agent
            return answer.status
    except (urllib.error.URLError, OSError):
        return None


class SnapshotAgentCheck:
    """Restores the guest's snapshot, waits for the agent to answer, and stops the guest again."""

    def __init__(
        self,
        host: Host,
        status_of: Callable[[str], int | None] = _http_status,
        sleep: Callable[[float], None] = lambda _seconds: None,
        timeout_s: float = AGENT_TIMEOUT_S,
        poll_s: float = AGENT_POLL_S,
    ) -> None:
        self._host = host
        self._status_of = status_of
        self._sleep = sleep
        self._timeout_s = timeout_s
        self._poll_s = poll_s

    def __call__(self, guest: Guest, profile: Profile) -> tuple[bool, str]:
        try:
            self._host.revert(guest.name, guest.snapshot)
        except HostError as error:
            return False, str(error)
        try:
            return self._wait_for_agent(f"http://{guest.ip}:{profile.agent.port}")
        finally:
            self._host.destroy(guest.name)

    def _wait_for_agent(self, base_url: str) -> tuple[bool, str]:
        attempts = int(self._timeout_s // self._poll_s)
        for attempt in range(attempts):
            if self._status_of(base_url + AGENT_STATUS_PATH) == HTTP_OK:
                return True, f"the agent at {base_url} answered after the snapshot was restored"
            if attempt < attempts - 1:
                self._sleep(self._poll_s)
        return False, f"the agent at {base_url} did not answer within {self._timeout_s:g} s"


def _check(check_id: str, ok: bool, message: str) -> Check:
    return {"id": check_id, "ok": ok, "message": message}


def _registration_check(guest: Guest, probe: MachinesProbe) -> Check:
    try:
        labels: Sequence[str] = probe()
    except Exception as error:  # noqa: BLE001 - CAPE being down is a result of the check
        return _check("registration", False, f"CAPE's machine list could not be read: {error}")
    if guest.name in labels:
        return _check("registration", True, f"CAPE lists {guest.name}")
    return _check("registration", False, f"CAPE does not list {guest.name} ({guest.state})")


def run_checks(
    guest: Guest, profile: Profile, host: Host, probe: MachinesProbe, agent_check: AgentCheck
) -> dict[str, Any]:
    domain = host.domain_exists(guest.name)
    snapshot = domain and guest.snapshot in host.snapshot_names(guest.name)
    checks = [
        _check(
            "domain",
            domain,
            "the VM is defined" if domain else f"libvirt has no VM called {guest.name}",
        ),
        _check(
            "snapshot",
            snapshot,
            f"the snapshot {guest.snapshot} exists"
            if snapshot
            else f"the snapshot {guest.snapshot} does not exist",
        ),
        _registration_check(guest, probe),
        _agent_check(guest, profile, agent_check, ready=snapshot),
    ]
    return {"name": guest.name, "checks": checks}


def _agent_check(guest: Guest, profile: Profile, agent_check: AgentCheck, *, ready: bool) -> Check:
    if not ready:
        return _check("agent", False, "skipped: it needs the VM and its snapshot")
    ok, message = agent_check(guest, profile)
    return _check("agent", ok, message)
