"""The guest engine behind the control service: profiles, media, guests, builds, health, deletion.

`create_engine()` is what `bin/guest-control` calls. Everything the engine touches outside its own
state (libvirt, `cape`, CAPE's API, the clock, randomness) comes in through `EngineConfig`, so the
whole of it runs in unit tests with a fake command runner.

Engine operations that change anything hold one lock, which the build sequencer shares, so a delete
never lands between two halves of a build's status change. Reads take no lock.
"""

import configparser
import ipaddress
import json
import logging
import os
import sys
import threading
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from guest_engine.builds import (
    BUILD_FILE,
    CONTEXT_FILE,
    LOG_FILE,
    BuildRecord,
    BuildStore,
    timestamp,
)
from guest_engine.config import EngineConfig
from guest_engine.errors import Conflict, GuestNotFound
from guest_engine.health import CapeMachinesProbe, SnapshotAgentCheck, run_checks
from guest_engine.host import Host, HostError
from guest_engine.inspectors import load_inspectors
from guest_engine.media import MediaProblem, cleanup_stale_mounts, scan_media
from guest_engine.profile import PipelineStep, Profile, derive_badges, load_profiles
from guest_engine.registrar import Registrar, RegistrationFailed
from guest_engine.registration import REGISTRATION_FILE
from guest_engine.registry import (
    GUEST_FILE,
    Guest,
    GuestSpec,
    Registry,
    new_guest,
    write_atomically,
)
from guest_engine.selftest import (
    ChecksCollector,
    ChecksFailed,
    PreparedChecks,
    SampleBuilder,
    run_check_step,
)
from guest_engine.sequencer import BuildFailed, BuildJob, Sequencer
from guest_engine.steps import Redactor, StepPaths, step_environment
from guest_engine.validation import ValidationContext, validate_build, validate_clone

log = logging.getLogger(__name__)

HIDDEN_VALUE = "***"
CHECKS_DIR = "checks"
CHECKS_KIND = "checks"
TESTABLE_STATES = ("testing", "ready")
SELFTEST_CACHE = Path("tartarus") / "cache" / "selftest"
type Json = dict[str, Any]


def create_engine(config: EngineConfig | None = None) -> "Engine":
    _log_to_stderr()
    return Engine(config or EngineConfig.from_environment(os.environ))


def _log_to_stderr() -> None:
    package = logging.getLogger("guest_engine")
    if not package.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("guest-control: %(levelname)s %(message)s"))
        package.addHandler(handler)
        package.setLevel(logging.INFO)


class Engine:
    def __init__(self, config: EngineConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        catalog = load_profiles(config.profiles_dir, config.steps_dir)
        for broken in catalog.broken:
            log.error("profile %s is unusable: %s", broken.directory.name, broken.message)
        self._profiles = catalog.profiles
        self._inspectors = load_inspectors(self._profiles)
        self._registry = Registry(config.registry_root)
        self._builds = BuildStore(config.registry_root)
        self._sequencer = Sequencer(self._builds, self._lock, config.inherited_environment)
        self._host = Host(config.runner, config.libvirt_uri)
        self._probe = config.machines_probe or CapeMachinesProbe(
            config.cape_api_url, config.cape_api_token
        )
        self._agent_check = config.agent_check or SnapshotAgentCheck(self._host, sleep=config.sleep)
        self._registrar = Registrar(config, self._registry, self._profiles, self._host, self._probe)
        self._samples = SampleBuilder(config.libvirt_dir / SELFTEST_CACHE, config.runner)
        self._start()

    # --- reading ---------------------------------------------------------------------

    def profiles(self) -> list[Json]:
        return [_profile_view(profile) for profile in self._profiles.values()]

    def media(self) -> list[Json]:
        return scan_media(
            self._config.media_dir, self._inspectors, self._config.runner, self._config.scan_root
        )

    def guests(self) -> list[Json]:
        views = [self._guest_view(guest) for guest in self._registry.list()]
        broken = [
            {"name": name, "state": "broken", "error": error}
            for name, error in self._registry.broken()
        ]
        return views + broken

    def guest(self, name: str) -> Json:
        try:
            return self._guest_view(self._registry.get(name))
        except ValueError as error:
            return {"name": name, "state": "broken", "error": str(error)}

    def guest_address(self, name: str) -> Json:
        guest = self._registry.get(name)
        profile = self._profile_of(guest)
        return {
            "ip": guest.ip,
            "agent_port": profile.agent.port,
            "finish_dir": profile.agent.finish_dir,
        }

    def display(self, name: str) -> Json | None:
        self._registry.get(name)
        return self._host.display(name)

    def selftest_sample(self, name: str) -> Json:
        guest = self._registry.get(name)
        profile = self._profile_of(guest)
        built = self._samples.sample(profile, self._profile_dir(profile))
        return {"path": str(built.path), "filename": built.filename}

    def build(self, build_id: str) -> Json:
        return _build_view(self._builds.load(build_id))

    def build_log(self, build_id: str, tail: int) -> list[str]:
        return self._builds.tail(build_id, tail)

    def wait(self, build_id: str, timeout: float | None = None) -> bool:
        """Block until the build's sequencer has stopped; False if it still runs after `timeout`."""
        return self._sequencer.wait(build_id, timeout)

    # --- building and cloning ------------------------------------------------------------

    def start_build(self, params: Json) -> str:
        with self._lock:
            self._sequencer.require_free_slot()
            validated = validate_build(params, self._context(media=self.media()), self._config.rng)
            profile = self._profiles[validated.spec.profile]
            pipeline = profile.build_pipeline(validated.media_kind, validated.spec.options)
            return self._begin(validated.spec, profile, pipeline)

    def start_clone(self, source: str, params: Json) -> str:
        with self._lock:
            self._sequencer.require_free_slot()
            spec = validate_clone(source, params, self._context(media=[]), self._config.rng)
            profile = self._profiles[spec.profile]
            return self._begin(spec, profile, profile.clone_pipeline(spec.options))

    def resume(self, build_id: str) -> None:
        self._run_again(build_id, self._sequencer.resume)

    def restart(self, build_id: str) -> None:
        self._run_again(build_id, self._sequencer.restart)

    def continue_after_pause(self, build_id: str) -> None:
        self._run_again(build_id, self._sequencer.continue_after_pause)

    def complete_build(self, build_id: str, passed: bool, selftest: Json) -> None:
        with self._lock:
            build = self._builds.load(build_id)
            guest = self._registry.get(build.guest)
            if build.status != "succeeded":
                raise Conflict(
                    f"the {build.kind} of {guest.name} is {build.status}; "
                    "a self-test verdict applies to a finished build"
                )
            wanted = "ready" if passed else "failed"
            if guest.state == wanted:
                self._registry.store_selftest(guest.name, selftest)
            elif guest.state == "testing":
                self._conclude_testing(guest, wanted, selftest)
            else:
                raise Conflict(
                    f"{guest.name} is {guest.state}; a {'passed' if passed else 'failed'} "
                    "self-test cannot change that"
                )

    def shutdown(self) -> None:
        """Stop the running step and fail its build so a restarted service can resume it."""
        self._sequencer.shutdown()

    # --- health and deletion -------------------------------------------------------------

    def check(self, name: str) -> Json:
        with self._lock:
            self._sequencer.require_unoccupied()
            guest = self._registry.get(name)
            profile = self._profile_of(guest)
            active = self._builds.active()
            if active is not None:
                raise Conflict(
                    f"the {active.kind} of {active.guest} is {active.status}; "
                    "checks restore a snapshot and wait until it is done"
                )
            return run_checks(guest, profile, self._host, self._probe, self._agent_check)

    def selftest_checks(self, name: str) -> Json:
        with ExitStack() as holding:
            with self._lock:
                guest = self._registry.get(name)
                profile = self._profile_of(guest)
                if guest.state not in TESTABLE_STATES:
                    raise Conflict(
                        f"{name} is {guest.state}; the self-test checks need it testing or ready"
                    )
                control = holding.enter_context(
                    self._sequencer.occupy(f"the self-test checks of {name}")
                )
                if profile.selftest.check_step is None:
                    return ChecksCollector().report()
                checks = self._prepare_checks(guest, profile, profile.selftest.check_step)
            try:
                return run_check_step(
                    checks, redact=Redactor(_secrets_of(guest, profile)), control=control
                )
            except ChecksFailed:
                # A step killed at its limit cannot run its own clean-up.
                self._host.destroy(name)
                raise

    def delete_guest(self, name: str) -> None:
        with self._lock:
            self._sequencer.require_unoccupied()
            guest = self._registry.get(name)
            self._refuse_while_in_use(guest)
            try:
                self._registrar.sync(excluding={name})
            except RegistrationFailed as error:
                raise Conflict(
                    f"{name} could not be unregistered, so it was not deleted: {error}"
                ) from None
            files = self._host.owned_files(name) if self._host.domain_exists(name) else []
            self._host.destroy(name)
            try:
                self._host.undefine(name)
            except HostError as error:
                raise Conflict(
                    f"{name} is unregistered but its VM was not removed: {error}"
                ) from None
            self._remove_files(files)
            self._registry.delete(name)

    # --- internals -------------------------------------------------------------------------

    def _start(self) -> None:
        self._clean_stale_mounts()
        for build in self._sequencer.recover_interrupted():
            self._mark_state(build.guest, "failed")
        self._adopt_existing_guests()

    def _clean_stale_mounts(self) -> None:
        try:
            cleanup_stale_mounts(self._config.runner, self._config.scan_root)
        except (MediaProblem, OSError):
            log.exception("could not clean up the mounts a killed service left behind")

    def _context(self, media: list[Json]) -> ValidationContext:
        return ValidationContext(self._profiles, self._registry.list(), media)

    def _profile_of(self, guest: Guest) -> Profile:
        profile = self._profiles.get(guest.profile)
        if profile is None:
            raise Conflict(f"the profile {guest.profile} of {guest.name} is not installed")
        return profile

    def _begin(self, spec: GuestSpec, profile: Profile, pipeline: list[PipelineStep]) -> str:
        address = self._registry.allocate_ip(self._config.guest_subnet)
        guest = new_guest(spec, profile, address, rng=self._config.rng, now=self._config.clock())
        self._registry.create(guest)
        try:
            build = self._sequencer.begin(
                guest.name, spec.kind, pipeline, self._job(guest, profile), now=self._config.clock()
            )
        except BaseException:
            self._registry.delete(guest.name)
            raise
        return build.id

    def _profile_dir(self, profile: Profile) -> Path:
        return profile.directory or self._config.profiles_dir / profile.id

    def _job(self, guest: Guest, profile: Profile) -> BuildJob:
        return BuildJob(
            find_step=profile.step_path,
            profile_dir=self._profile_dir(profile),
            secrets=_secrets_of(guest, profile),
            on_status=self._on_build_status,
            prepare=self._write_context,
            finalize=self._register_when_built,
        )

    def _run_again(self, build_id: str, action: Any) -> None:
        with self._lock:
            build = self._builds.load(build_id)
            guest = self._registry.get(build.guest)
            action(build_id, self._job(guest, self._profile_of(guest)))

    def _on_build_status(self, build: BuildRecord) -> None:
        state = {"running": "building", "failed": "failed"}.get(build.status)
        if state is None:
            return
        self._mark_state(build.guest, state)
        if state == "failed":
            self._unregister_quietly()

    def _mark_state(self, name: str, state: str) -> None:
        try:
            self._registry.update_state(name, state)
        except GuestNotFound:
            log.warning("guest %s is gone; its state was not set to %s", name, state)

    def _unregister_quietly(self) -> None:
        try:
            self._registrar.sync()
        except RegistrationFailed as error:
            log.warning("could not unregister the failed guest: %s", error)

    def _register_when_built(self, build: BuildRecord) -> None:
        with self._lock:
            self._registry.update_state(build.guest, "testing")
            try:
                self._registrar.sync()
            except RegistrationFailed as error:
                raise BuildFailed(str(error)) from None

    def _conclude_testing(self, guest: Guest, wanted: str, selftest: Json) -> None:
        if wanted == "ready":
            self._sync_or_refuse(guest.name)
            self._registry.update(guest.name, state="ready", selftest=selftest)
            return
        self._registry.update(guest.name, state="failed", selftest=selftest)
        self._sync_or_refuse(guest.name)

    def _sync_or_refuse(self, name: str) -> None:
        try:
            self._registrar.sync()
        except RegistrationFailed as error:
            raise Conflict(f"CAPE could not be updated for {name}: {error}") from None

    def _refuse_while_in_use(self, guest: Guest) -> None:
        active = self._builds.active()
        if active is None:
            return
        if active.guest == guest.name and active.status == "running":
            raise Conflict(f"the {active.kind} of {guest.name} is running; wait for it to finish")
        building = self._registry.get(active.guest)
        if building.cloned_from == guest.name:
            raise Conflict(f"{active.guest} is being cloned from {guest.name}; wait for it")

    def _remove_files(self, files: list[Path]) -> None:
        libvirt_dir = self._config.libvirt_dir.resolve()
        media_dir = self._config.media_dir.resolve()
        for file in files:
            resolved = file.resolve()
            if resolved.is_relative_to(libvirt_dir) and not resolved.is_relative_to(media_dir):
                resolved.unlink(missing_ok=True)

    def _write_context(self, build: BuildRecord) -> None:
        guest = self._registry.get(build.guest)
        self._store_context(
            self._builds.directory(build),
            guest,
            {"id": build.id, "kind": build.kind, "steps": [s.name for s in build.steps]},
        )

    def _store_context(self, directory: Path, guest: Guest, build: Json) -> None:
        source = self._source_of(guest)
        context = {
            "guest": guest.to_dict(),
            "profile": _profile_view(self._profile_of(guest)),
            "source": source.to_dict() if source else None,
            "build": build,
            "host": self._host_view(),
        }
        write_atomically(directory / CONTEXT_FILE, json.dumps(context, indent=2) + "\n", 0o600)

    def _prepare_checks(self, guest: Guest, profile: Profile, step_name: str) -> PreparedChecks:
        step = profile.step_path(step_name)
        if step is None:
            raise ChecksFailed(f"the check step '{step_name}' was not found or is not executable")
        started = timestamp(self._config.clock())
        guest_dir = self._config.registry_root / guest.name
        directory = guest_dir / CHECKS_DIR / started
        directory.mkdir(parents=True, exist_ok=True)
        check_id = f"{CHECKS_KIND}-{started}"
        self._store_context(
            directory, guest, {"id": check_id, "kind": CHECKS_KIND, "steps": [step_name]}
        )
        paths = StepPaths(
            guest_dir=guest_dir,
            guest_json=guest_dir / GUEST_FILE,
            profile_dir=self._profile_dir(profile),
            # No build record exists for checks; the variable still names where one would be.
            state_file=directory / BUILD_FILE,
            build_dir=directory,
            log=directory / LOG_FILE,
            context_json=directory / CONTEXT_FILE,
        )
        environment = step_environment(
            paths,
            step=step_name,
            build_id=check_id,
            inherited=self._config.inherited_environment,
        )
        return PreparedChecks(step, environment, self._config.selftest_check_timeout_s, paths.log)

    def _source_of(self, guest: Guest) -> Guest | None:
        if guest.cloned_from is None:
            return None
        try:
            return self._registry.get(guest.cloned_from)
        except GuestNotFound:
            raise BuildFailed(f"the source guest {guest.cloned_from} no longer exists") from None

    def _host_view(self) -> Json:
        network = ipaddress.ip_network(self._config.guest_subnet)
        return {
            "subnet": self._config.guest_subnet,
            "gateway": str(network.network_address + 1),
            "registry_root": str(self._config.registry_root),
            "libvirt_dir": str(self._config.libvirt_dir),
            "media_dir": str(self._config.media_dir),
            "registration_dir": str(self._config.registration_dir),
            "libvirt_uri": self._config.libvirt_uri,
        }

    def _guest_view(self, guest: Guest) -> Json:
        profile = self._profiles.get(guest.profile)
        view = guest.to_dict()
        view["options"] = _masked_options(guest.options, profile)
        view["badges"] = derive_badges(profile, guest.options) if profile else []
        builds = self._builds.of_guest(guest.name)
        view["build_id"] = builds[-1].id if builds else None
        return view

    def _adopt_existing_guests(self) -> None:
        files = sorted(
            path
            for path in self._config.registration_dir.glob("*.conf")
            if path.name != REGISTRATION_FILE
        )
        if not files:
            return
        profile = next((p for _, p in sorted(self._profiles.items()) if p.adoption), None)
        left = [file for file in files if not self._adopt(file, profile)]
        if left:
            log.warning(
                "registration files left as they are, nothing adopts them: %s",
                ", ".join(file.name for file in left),
            )
            return
        try:
            self._registrar.write_files()
        except RegistrationFailed as error:
            log.warning("could not write the single registration file: %s", error)

    def _adopt(self, file: Path, profile: Profile | None) -> bool:
        """Adopt the guest `file` registers if there is one; True when the registry knows it now."""
        text = file.read_text()
        label = _single_machine(text)
        if label is None:
            log.warning("%s does not register exactly one machine; not adopted", file.name)
            return False
        if self._registry.exists(label):
            return True
        if profile is None:
            log.info("%s is not adopted: no installed profile has adoption data", label)
            return False
        if not self._host.domain_exists(label):
            log.info("%s is not adopted: libvirt has no VM of that name", label)
            return False
        try:
            self._registry.adopt(
                self._host.domain_xml(label) or "", text, profile, now=self._config.clock()
            )
        except ValueError as error:
            log.warning("%s is not adopted: %s", label, error)
            return False
        log.info("adopted the existing guest %s", label)
        return True


def _single_machine(registration: str) -> str | None:
    parser = configparser.ConfigParser()
    try:
        parser.read_string(registration)
    except configparser.Error:
        return None
    machines = [
        name.strip()
        for name in parser.get("kvm", "machines", fallback="").split(",")
        if name.strip()
    ]
    return machines[0] if len(machines) == 1 else None


def _secrets_of(guest: Guest, profile: Profile) -> list[str]:
    secret_options = (
        str(guest.options[option.key])
        for option in profile.options
        if option.type == "secret" and option.key in guest.options
    )
    return [guest.identity.password, *secret_options]


def _masked_options(options: Mapping[str, Any], profile: Profile | None) -> Json:
    secret_keys = {o.key for o in profile.options if o.type == "secret"} if profile else set()
    return {
        key: HIDDEN_VALUE if key in secret_keys and value else value
        for key, value in options.items()
    }


def _profile_view(profile: Profile) -> Json:
    view = profile.to_dict()
    del view["adoption"]
    return view


def _build_view(build: BuildRecord) -> Json:
    current = build.steps[build.step] if build.steps else None
    on_desktop = current is not None and current.desktop and build.status in ("running", "paused")
    return {**build.to_dict(), "desktop": on_desktop}
