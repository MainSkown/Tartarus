from pathlib import Path

from guest_engine.config import EngineConfig
from guest_engine.media import run_command


def test_the_defaults_are_the_paths_of_the_cape_image():
    config = EngineConfig()

    assert config.registry_root == Path("/var/lib/libvirt/tartarus/guests")
    assert config.media_dir == Path("/data/iso")
    assert config.profiles_dir == Path("/usr/local/lib/tartarus/profiles")
    assert config.steps_dir == Path("/usr/local/lib/tartarus/steps")
    assert config.registration_dir == Path("/var/lib/libvirt/tartarus/kvm.conf.d")
    assert config.libvirt_dir == Path("/var/lib/libvirt")
    assert config.guest_subnet == "192.168.150.0/24"
    assert config.libvirt_uri == "qemu:///system"
    assert config.runner is run_command


def test_the_environment_overrides_the_defaults():
    environ = {
        "GUEST_REGISTRY_DIR": "/r",
        "GUEST_MEDIA_DIR": "/m",
        "GUEST_PROFILES_DIR": "/p",
        "GUEST_STEPS_DIR": "/s",
        "GUEST_REGISTRATION_DIR": "/k",
        "GUEST_SUBNET": "10.1.2.0/24",
        "CAPE_API_TOKEN": "tok",
        "PATH": "/bin",
    }

    config = EngineConfig.from_environment(environ)

    assert config.registry_root == Path("/r")
    assert config.media_dir == Path("/m")
    assert config.profiles_dir == Path("/p")
    assert config.steps_dir == Path("/s")
    assert config.registration_dir == Path("/k")
    assert config.guest_subnet == "10.1.2.0/24"
    assert config.cape_api_token == "tok"  # noqa: S105
    assert config.inherited_environment == environ


def test_an_empty_environment_gives_the_defaults():
    assert EngineConfig.from_environment({}) == EngineConfig(inherited_environment={})


def test_a_blank_variable_does_not_override_a_default():
    config = EngineConfig.from_environment({"GUEST_MEDIA_DIR": "", "GUEST_SUBNET": ""})

    assert config.media_dir == Path("/data/iso")
    assert config.guest_subnet == "192.168.150.0/24"


def test_every_collaborator_can_be_replaced():
    marker = object()
    config = EngineConfig(
        runner=marker,
        machines_probe=marker,
        agent_check=marker,
        clock=marker,
        rng=marker,
        sleep=marker,
    )

    assert (config.runner, config.machines_probe, config.agent_check) == (marker,) * 3
    assert (config.clock, config.rng, config.sleep) == (marker,) * 3
