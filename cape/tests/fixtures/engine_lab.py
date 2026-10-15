"""An engine over the fake profile, a fake libvirt and CAPE, and a temporary filesystem."""

import os
from datetime import UTC, datetime

from fixtures.fake_host import FakeHost
from fixtures.guest_samples import seeded
from fixtures.profile_samples import FIXTURE_DIR

from guest_engine.config import EngineConfig
from guest_engine.engine import create_engine

FAKE = FIXTURE_DIR / "fake_profile"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
PASSWORD = "Sup3r-secret-pw"  # noqa: S105 - a fixture value
TOKEN = "tok-9f8e7d6c"  # noqa: S105 - a fixture value


class Lab:
    """Everything an engine test needs, rooted in one temporary directory."""

    def __init__(self, tmp_path, **overrides):
        self.tmp = tmp_path
        self.libvirt_dir = tmp_path / "lib"
        self.root = self.libvirt_dir / "tartarus" / "guests"
        self.registration_dir = self.libvirt_dir / "tartarus" / "kvm.conf.d"
        self.media_dir = tmp_path / "iso"
        self.registration_dir.mkdir(parents=True)
        self.media_dir.mkdir()
        (self.media_dir / "disc.fake").write_text("a toy installation medium")
        self.host = FakeHost(self.libvirt_dir, self.root, self.registration_dir)
        self.settings = {
            "registry_root": self.root,
            "media_dir": self.media_dir,
            "profiles_dir": FAKE / "profiles",
            "steps_dir": FAKE / "steps",
            "registration_dir": self.registration_dir,
            "libvirt_dir": self.libvirt_dir,
            "scan_root": tmp_path / "scan",
            "runner": self.host,
            "machines_probe": self.host.machines,
            "agent_check": lambda _guest, _profile: (True, "the agent answered"),
            "rng": seeded(7),
            "clock": lambda: NOW,
            "sleep": lambda _seconds: None,
            "registration_timeout_s": 3,
            "registration_poll_s": 1,
            "inherited_environment": {"PATH": os.environ["PATH"]},
            **overrides,
        }
        self.engine = create_engine(EngineConfig(**self.settings))

    def restarted(self, **overrides):
        """A new engine over the same filesystem, as after the service was killed."""
        settings = {**self.settings, **overrides}
        self.engine = create_engine(EngineConfig(**settings))
        return self.engine

    def build(self, name="alpha", wait=True, **extra):
        build_id = self.engine.start_build(params(name, **extra))
        return self.settle(build_id) if wait else build_id

    def settle(self, build_id):
        assert self.engine.wait(build_id, timeout=30), "the build did not end"
        return self.engine.build(build_id)

    def dir(self, name="alpha"):
        return self.root / name

    def ran(self, name="alpha"):
        return (self.dir(name) / "ran").read_text().split()


def params(name="alpha", **extra):
    return {
        "name": name,
        "profile": "fake",
        "media": {"file": "disc.fake", "variant": "1"},
        **extra,
    }
