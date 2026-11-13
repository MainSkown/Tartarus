"""`bin/pin-host` keeps the address of one name in the hosts file.

The `cape` user is refused Docker's resolver (guest_engine/egress.py), so the entrypoint resolves
the one name CAPE needs, its database's, as root and pins it. Docker bind-mounts /etc/hosts, so the
file is rewritten in place, never replaced.
"""

import os
import subprocess
from pathlib import Path

import pytest

CAPE = Path(__file__).resolve().parents[1]
PIN_HOST = CAPE / "bin" / "pin-host"
DOCKER_HOSTS = "127.0.0.1\tlocalhost\n172.20.0.3\t0c57c64bba16\n"


@pytest.fixture
def hosts(tmp_path) -> Path:
    file = tmp_path / "hosts"
    file.write_text(DOCKER_HOSTS)
    return file


@pytest.fixture
def resolver(tmp_path):
    """A getent that answers from the hosts file first, as libc does, then from `dns`."""

    def install(hosts: Path, dns: dict[str, str]) -> dict[str, str]:
        records = "\n".join(f"{name} {address}" for name, address in dns.items())
        (tmp_path / "dns").write_text(records + "\n")
        script = tmp_path / "bin" / "getent"
        script.parent.mkdir(exist_ok=True)
        script.write_text(
            "#!/bin/sh\n"
            '[ "$1" = ahostsv4 ] || exit 2\n'
            f"address=$(awk -v name=\"$2\" '$2 == name {{print $1; exit}}' {hosts})\n"
            f'[ -n "$address" ] || address=$(awk -v name="$2" \'$1 == name {{print $2; exit}}\' '
            f"{tmp_path / 'dns'})\n"
            '[ -n "$address" ] || exit 2\n'
            'printf "%s STREAM %s\\n%s DGRAM\\n" "$address" "$2" "$address"\n'
        )
        script.chmod(0o755)
        return {"PATH": f"{script.parent}:{os.environ['PATH']}"}

    return install


def pin(name: str, hosts: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - this repository's own script
        [str(PIN_HOST), name, str(hosts)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_the_resolved_address_is_added_and_the_other_lines_are_kept(hosts, resolver):
    result = pin("postgres", hosts, resolver(hosts, {"postgres": "172.20.0.2"}))

    assert result.returncode == 0, result.stderr
    assert hosts.read_text() == DOCKER_HOSTS + "172.20.0.2\tpostgres\n"


def test_the_file_is_rewritten_in_place_because_docker_bind_mounts_it(hosts, resolver):
    before = hosts.stat().st_ino

    pin("postgres", hosts, resolver(hosts, {"postgres": "172.20.0.2"}))

    assert hosts.stat().st_ino == before


def test_a_restart_asks_again_and_does_not_trust_the_address_it_pinned_before(hosts, resolver):
    hosts.write_text(DOCKER_HOSTS + "172.20.0.2\tpostgres\n")

    result = pin("postgres", hosts, resolver(hosts, {"postgres": "172.20.0.9"}))

    assert result.returncode == 0, result.stderr
    assert hosts.read_text() == DOCKER_HOSTS + "172.20.0.9\tpostgres\n"


def test_a_name_that_only_ends_the_same_is_left_alone(hosts, resolver):
    hosts.write_text(DOCKER_HOSTS + "10.0.0.5\told-postgres\n")

    pin("postgres", hosts, resolver(hosts, {"postgres": "172.20.0.2"}))

    assert "10.0.0.5\told-postgres\n" in hosts.read_text()


def test_a_name_that_does_not_resolve_is_a_failure_that_says_which(hosts, resolver):
    result = pin("postgres", hosts, resolver(hosts, {}))

    assert result.returncode != 0
    assert "postgres" in result.stderr
    assert hosts.read_text() == DOCKER_HOSTS


@pytest.mark.parametrize("name", ["", "two words", "a/b", "x;rm"])
def test_only_a_host_name_is_taken(hosts, resolver, name):
    result = pin(name, hosts, resolver(hosts, {"postgres": "172.20.0.2"}))

    assert result.returncode != 0
    assert hosts.read_text() == DOCKER_HOSTS


def test_the_entrypoint_pins_the_host_of_capes_database_connection_before_cape_is_confined():
    entrypoint = (CAPE / "entrypoint.sh").read_text()
    connection = (CAPE / "conf" / "cuckoo.conf").read_text()

    assert "DATABASE_HOST=postgres\n" in entrypoint
    assert "@postgres:5432/" in connection
    pinned = entrypoint.index('/usr/local/lib/tartarus/pin-host "$DATABASE_HOST" /etc/hosts\n')
    assert pinned < entrypoint.index("/usr/local/lib/tartarus/container-egress init")
