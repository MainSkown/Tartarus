import pytest
from fixtures.fake_host import FakeHost
from fixtures.guest_samples import make_guest
from fixtures.profile_samples import sample_profile

from guest_engine.config import EngineConfig
from guest_engine.host import Host
from guest_engine.registrar import Registrar, RegistrationFailed
from guest_engine.registry import Registry


class World:
    def __init__(self, tmp_path):
        self.registration_dir = tmp_path / "conf.d"
        self.registration_dir.mkdir()
        self.registry = Registry(tmp_path / "guests")
        self.host = FakeHost(tmp_path / "lib", tmp_path / "guests", self.registration_dir)
        self.probe_error = None
        self.config = EngineConfig(
            registration_dir=self.registration_dir,
            registration_timeout_s=9,
            registration_poll_s=3,
            sleep=lambda _seconds: None,
        )
        self.registrar = Registrar(
            self.config,
            self.registry,
            {"windows": sample_profile("windows")},
            Host(self.host, "qemu:///system"),
            self.probe,
        )

    def probe(self):
        if self.probe_error:
            raise self.probe_error
        return self.host.machines()

    def guest(self, name, ip, state, define=True):
        self.registry.create(make_guest(name, ip, state=state))
        if define:
            (self.registry.root / name / "defined").write_text("")

    @property
    def guests_conf(self):
        return (self.registration_dir / "guests.conf").read_text()


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_every_testing_and_ready_guest_is_registered_then_cape_restarted_and_checked(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.guest("bravo", "192.168.150.11", "testing")
    world.guest("charlie", "192.168.150.12", "building")
    world.guest("delta", "192.168.150.13", "failed")

    restarted = world.registrar.sync()

    assert restarted is True
    assert "machines = alpha,bravo" in world.guests_conf
    assert "charlie" not in world.guests_conf
    assert world.host.cape_restarts == 1
    assert world.host.machines() == ["alpha", "bravo"]


def test_a_second_sync_with_nothing_changed_leaves_cape_alone(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.registrar.sync()

    restarted = world.registrar.sync()

    assert restarted is False
    assert world.host.cape_restarts == 1


def test_with_nothing_to_register_and_no_file_there_is_nothing_to_do(world):
    world.guest("alpha", "192.168.150.10", "failed")

    assert world.registrar.sync() is False

    assert world.host.cape_restarts == 0
    assert not (world.registration_dir / "guests.conf").exists()


def test_a_guest_going_from_testing_to_ready_does_not_restart_cape(world):
    world.guest("alpha", "192.168.150.10", "testing")
    world.registrar.sync()

    world.registry.update_state("alpha", "ready")

    assert world.registrar.sync() is False


def test_every_other_conf_file_is_removed_because_the_last_one_wins(world):
    world.guest("alpha", "192.168.150.10", "ready")
    (world.registration_dir / "win.conf").write_text("[kvm]\nmachines = win\n")

    world.registrar.sync()

    assert sorted(path.name for path in world.registration_dir.iterdir()) == ["guests.conf"]
    assert world.host.cape_restarts == 1


def test_a_stray_file_alone_is_reason_enough_to_rewrite_and_restart(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.registrar.sync()
    (world.registration_dir / "zz.conf").write_text("[kvm]\nmachines =\n")

    assert world.registrar.sync() is True
    assert not (world.registration_dir / "zz.conf").exists()


def test_a_guest_leaving_is_unregistered_and_cape_restarted(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.guest("bravo", "192.168.150.11", "ready")
    world.registrar.sync()

    world.registry.update_state("bravo", "failed")
    world.registrar.sync()

    assert world.host.machines() == ["alpha"]
    assert world.host.cape_restarts == 2


def test_the_last_guest_leaving_leaves_an_empty_registration_that_is_verified(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.registrar.sync()

    world.registrar.sync(excluding={"alpha"})

    assert world.host.machines() == []
    assert world.guests_conf.splitlines()[:2] == ["[kvm]", "machines ="]


def test_a_guest_named_in_excluding_is_left_out_whatever_its_state(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.guest("bravo", "192.168.150.11", "ready")

    world.registrar.sync(excluding={"bravo"})

    assert world.host.machines() == ["alpha"]


def test_a_vm_libvirt_does_not_have_is_never_registered(world):
    world.guest("alpha", "192.168.150.10", "ready", define=False)

    with pytest.raises(RegistrationFailed, match=r"alpha.*not defined"):
        world.registrar.sync()

    assert world.host.cape_restarts == 0
    assert not (world.registration_dir / "guests.conf").exists()


def test_two_guests_with_one_address_are_refused_before_anything_is_written(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.guest("bravo", "192.168.150.10", "ready")

    with pytest.raises(RegistrationFailed, match=r"192\.168\.150\.10"):
        world.registrar.sync()

    assert world.host.cape_restarts == 0


def test_a_cape_that_will_not_restart_is_reported_with_its_output(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.host.cape_fails = True

    with pytest.raises(RegistrationFailed, match="spawn error"):
        world.registrar.sync()


def test_a_machine_list_that_never_shows_the_guests_fails_naming_both(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.registrar.probe = lambda: ["stale"]

    with pytest.raises(RegistrationFailed, match=r"alpha.*stale|stale.*alpha"):
        world.registrar.sync()


def test_the_machine_list_is_polled_until_it_matches(world):
    world.guest("alpha", "192.168.150.10", "ready")
    answers = iter([[], ["stale"], ["alpha"]])
    world.registrar.probe = lambda: next(answers)

    assert world.registrar.sync() is True


def test_a_cape_api_that_is_down_for_a_moment_is_waited_for(world):
    world.guest("alpha", "192.168.150.10", "ready")
    answers = iter([OSError("connection refused"), ["alpha"]])

    def flaky():
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    world.registrar.probe = flaky

    assert world.registrar.sync() is True


def test_a_cape_api_that_stays_down_reports_the_last_error(world):
    world.guest("alpha", "192.168.150.10", "ready")
    world.probe_error = OSError("connection refused")

    with pytest.raises(RegistrationFailed, match="connection refused"):
        world.registrar.sync()


def test_the_polling_is_bounded_by_the_configured_timeout(world):
    world.guest("alpha", "192.168.150.10", "ready")
    polls = []
    world.registrar.probe = lambda: polls.append(1) or []

    with pytest.raises(RegistrationFailed):
        world.registrar.sync()

    assert len(polls) == 3  # 9 s timeout, 3 s apart


def test_files_can_be_written_without_touching_cape(world):
    world.guest("alpha", "192.168.150.10", "ready")
    (world.registration_dir / "win.conf").write_text("[kvm]\nmachines = win\n")

    world.registrar.write_files()

    assert world.host.cape_restarts == 0
    assert sorted(path.name for path in world.registration_dir.iterdir()) == ["guests.conf"]
    assert "machines = alpha" in world.guests_conf
