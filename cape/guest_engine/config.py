"""The engine's configuration: paths, the guest subnet and every collaborator it can be given.

Defaults are those of the cape image and are overridden from the environment, so the container
needs no setup; tests inject a runner, a probe, a clock and a random source instead and need no
containers.
"""

import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from guest_engine.media import Runner, run_command
from guest_engine.media.mount import SCAN_ROOT

if TYPE_CHECKING:
    from guest_engine.profile import Profile
    from guest_engine.registry import Guest

DEFAULT_SUBNET = "192.168.150.0/24"
DEFAULT_CAPE_API_URL = "http://127.0.0.1:8000"
REGISTRATION_TIMEOUT_S = 180.0
REGISTRATION_POLL_S = 3.0
DEFAULT_CHECK_TIMEOUT_S = 480

type MachinesProbe = Callable[[], Sequence[str]]
type AgentCheck = Callable[["Guest", "Profile"], tuple[bool, str]]

ENVIRONMENT_PATHS = {
    "GUEST_REGISTRY_DIR": "registry_root",
    "GUEST_MEDIA_DIR": "media_dir",
    "GUEST_PROFILES_DIR": "profiles_dir",
    "GUEST_STEPS_DIR": "steps_dir",
    "GUEST_REGISTRATION_DIR": "registration_dir",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class EngineConfig:
    registry_root: Path = Path("/var/lib/libvirt/tartarus/guests")
    media_dir: Path = Path("/data/iso")
    profiles_dir: Path = Path("/usr/local/lib/tartarus/profiles")
    steps_dir: Path = Path("/usr/local/lib/tartarus/steps")
    registration_dir: Path = Path("/var/lib/libvirt/tartarus/kvm.conf.d")
    libvirt_dir: Path = Path("/var/lib/libvirt")
    scan_root: Path = SCAN_ROOT
    guest_subnet: str = DEFAULT_SUBNET
    libvirt_uri: str = "qemu:///system"
    cape_api_url: str = DEFAULT_CAPE_API_URL
    cape_api_token: str = ""
    registration_timeout_s: float = REGISTRATION_TIMEOUT_S
    registration_poll_s: float = REGISTRATION_POLL_S
    selftest_check_timeout_s: int = DEFAULT_CHECK_TIMEOUT_S
    inherited_environment: Mapping[str, str] = field(default_factory=dict)
    runner: Runner = run_command
    machines_probe: MachinesProbe | None = None
    agent_check: AgentCheck | None = None
    clock: Callable[[], datetime] = _utc_now
    rng: random.Random | None = None
    sleep: Callable[[float], None] = time.sleep

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "EngineConfig":
        paths: dict[str, Any] = {
            field_name: Path(environ[variable])
            for variable, field_name in ENVIRONMENT_PATHS.items()
            if environ.get(variable)
        }
        defaults = cls()
        return replace(
            defaults,
            **paths,
            guest_subnet=environ.get("GUEST_SUBNET") or defaults.guest_subnet,
            cape_api_token=environ.get("CAPE_API_TOKEN", ""),
            inherited_environment=dict(environ),
        )
