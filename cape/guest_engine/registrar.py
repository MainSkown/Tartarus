"""Keeps CAPE's registration true to the registry: write `guests.conf`, restart `cape`, verify.

The order is fixed by S0b: the VM must exist before it is registered (a registered machine libvirt
does not know leaves `cape` "running" with every task pending), a guest is unregistered before it is
undefined, and success means CAPE's own machine list shows exactly the registered guests, never
what `supervisorctl status` says.
"""

import math
from collections.abc import Collection, Mapping

from guest_engine.config import EngineConfig, MachinesProbe
from guest_engine.errors import Conflict, GuestNotFound
from guest_engine.host import Host, HostError
from guest_engine.profile import Profile
from guest_engine.registration import (
    REGISTERED_STATES,
    REGISTRATION_FILE,
    apply_registration,
    render_registration,
)
from guest_engine.registry import Guest, Registry


class RegistrationFailed(RuntimeError):  # noqa: N818 - says why CAPE could not be updated, shown as it is
    """CAPE could not be brought in line with the registry; the message says why."""


class Registrar:
    def __init__(
        self,
        config: EngineConfig,
        registry: Registry,
        profiles: Mapping[str, Profile],
        host: Host,
        probe: MachinesProbe,
    ) -> None:
        self._config = config
        self._registry = registry
        self._profiles = profiles
        self._host = host
        self.probe = probe

    def sync(self, excluding: Collection[str] = ()) -> bool:
        """Make CAPE list exactly the testing and ready guests; True when `cape` was restarted."""
        guests = [guest for guest in self._registry.list() if guest.name not in excluding]
        text = self._render(guests)
        registered = sorted(g.name for g in guests if g.state in REGISTERED_STATES)
        self._require_defined(registered)
        if self._files_are_current(text):
            return False
        apply_registration(self._config.registration_dir, text)
        try:
            self._host.restart_cape()
        except HostError as error:
            raise RegistrationFailed(str(error)) from None
        self._wait_until_listed(registered)
        return True

    def write_files(self) -> None:
        """Write `guests.conf` and drop the other files without restarting `cape`.

        For the start of the service: the registration it leaves is equivalent to the one CAPE
        runs with, and a restart would kill an analysis that is running.
        """
        text = self._render(self._registry.list())
        if not self._files_are_current(text):
            apply_registration(self._config.registration_dir, text)

    def _render(self, guests: list[Guest]) -> str:
        try:
            return render_registration(guests, self._profiles)
        except (Conflict, GuestNotFound) as error:
            raise RegistrationFailed(str(error)) from None

    def _require_defined(self, names: list[str]) -> None:
        for name in names:
            if not self._host.domain_exists(name):
                raise RegistrationFailed(
                    f"the VM {name} is not defined in libvirt; registering it would stop CAPE"
                )

    def _files_are_current(self, text: str) -> bool:
        directory = self._config.registration_dir
        current = directory / REGISTRATION_FILE
        others = [path for path in directory.glob("*.conf") if path.name != REGISTRATION_FILE]
        if others:
            return False
        if not current.is_file():
            # CAPE ships with no machines, so a missing file already is the empty registration.
            return text == render_registration([], self._profiles)
        return current.read_text() == text

    def _wait_until_listed(self, expected: list[str]) -> None:
        attempts = max(
            1, math.ceil(self._config.registration_timeout_s / self._config.registration_poll_s)
        )
        problem = ""
        for attempt in range(attempts):
            try:
                listed = sorted(self.probe())
            except Exception as error:  # noqa: BLE001 - the API is down while cape restarts
                problem = f"CAPE's machine list could not be read: {error}"
            else:
                if listed == expected:
                    return
                problem = (
                    f"CAPE lists [{', '.join(listed)}] but should list [{', '.join(expected)}]"
                )
            if attempt < attempts - 1:
                self._config.sleep(self._config.registration_poll_s)
        raise RegistrationFailed(f"after restarting CAPE: {problem}")
