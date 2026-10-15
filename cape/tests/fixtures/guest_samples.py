"""Guest records for engine tests: a valid build request resolved, and the record made from it."""

import random
from dataclasses import replace
from datetime import UTC, datetime

from fixtures.profile_samples import sample_profile

from guest_engine.profile import MediaRef
from guest_engine.registry import (
    Guest,
    GuestIdentity,
    GuestResources,
    GuestSpec,
    new_guest,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
SUBNET = "192.168.150.0/24"
PASSWORD = "Secret-pass-1"  # noqa: S105 - a fixture value


def seeded(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311 - determinism is the point, not secrecy


def make_spec(name: str = "alpha", **changes) -> GuestSpec:
    spec = GuestSpec(
        name=name,
        profile="windows",
        kind="build",
        cloned_from=None,
        media=MediaRef("disc.iso", "5", "10.0.26200", "pl-PL", "amd64"),
        options={"defender": True},
        identity=GuestIdentity("Michael", "DESKTOP-ABC1234", PASSWORD),
        resources=GuestResources(2, 4096, 80),
    )
    return replace(spec, **changes)


def make_guest(name: str = "alpha", ip: str = "192.168.150.10", **changes) -> Guest:
    profile = sample_profile("ubuntu" if changes.get("profile") == "ubuntu" else "windows")
    guest = new_guest(make_spec(name), profile, ip, rng=seeded(1), now=NOW)
    return replace(guest, **changes)
