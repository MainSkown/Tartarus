"""The `lan-sim` compose service: what it may hold, and the directory it shares with `cape`.

The container shares cape's network namespace and parses hostile input from a guest, so these keep
its confinement from drifting; docker-compose.yml's own comments say why each line is there. The
proofs against the running stack are in docs/history/fake-lan-notes/step5-notes.md.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((REPO / "docker-compose.yml").read_text())
SERVICE: dict[str, Any] = COMPOSE["services"]["lan-sim"]
CAPE: dict[str, Any] = COMPOSE["services"]["cape"]
ENTRYPOINT = (REPO / "cape" / "entrypoint.sh").read_text()
DOCKERFILE = (REPO / "lan-sim" / "Dockerfile").read_text()
SHARED_DIRECTORY = "/run/lan-sim"
DAEMON_ID = "10001"


def test_it_shares_the_cape_namespace_and_joins_no_network_of_its_own():
    assert SERVICE["network_mode"] == "service:cape"
    assert "networks" not in SERVICE
    assert "ports" not in SERVICE


def test_it_holds_no_capability_but_binding_low_ports():
    assert SERVICE["cap_drop"] == ["ALL"]
    assert SERVICE["cap_add"] == ["NET_BIND_SERVICE"]
    assert "privileged" not in SERVICE
    assert "devices" not in SERVICE


def test_it_cannot_gain_privileges_or_write_its_own_filesystem():
    assert "no-new-privileges:true" in SERVICE["security_opt"]
    assert SERVICE["read_only"] is True
    assert "tmpfs" not in SERVICE


def test_it_runs_as_the_fixed_non_root_id_of_its_image():
    assert str(SERVICE["user"]).split(":")[0] == DAEMON_ID
    assert f"--uid {DAEMON_ID}" in DOCKERFILE
    assert f"USER {DAEMON_ID}:{DAEMON_ID}" in DOCKERFILE


def test_it_has_memory_and_process_limits():
    assert SERVICE["mem_limit"] == "512m"
    assert SERVICE["memswap_limit"] == SERVICE["mem_limit"]
    assert 64 <= SERVICE["pids_limit"] <= 4096


def test_it_gets_no_secret_and_mounts_only_the_shared_directory():
    assert "env_file" not in SERVICE
    assert not re.search(r"TOKEN|PASSWORD|SECRET", str(SERVICE.get("environment", {})))
    assert SERVICE["volumes"] == [f"lan-run:{SHARED_DIRECTORY}"]


def test_it_starts_after_cape_is_healthy_and_never_restarts_by_itself():
    assert SERVICE["depends_on"]["cape"]["condition"] == "service_healthy"
    assert SERVICE["restart"] == "no"


def test_its_healthcheck_reads_the_heartbeat_age_without_curl_or_a_shell():
    check = SERVICE["healthcheck"]["test"]

    assert check[0] == "CMD"
    assert check[1] == "python"
    assert "alive_file" in check[-1]


def test_the_shared_directory_is_a_tmpfs_volume_so_no_session_outlives_its_containers():
    options = COMPOSE["volumes"]["lan-run"]

    assert options["driver"] == "local"
    assert options["driver_opts"]["type"] == "tmpfs"
    assert options["driver_opts"]["device"] == "tmpfs"
    assert "size=" in options["driver_opts"]["o"]


def test_cape_mounts_the_same_volume_where_the_daemon_does():
    assert f"lan-run:{SHARED_DIRECTORY}" in CAPE["volumes"]


def test_the_entrypoint_makes_sessions_root_owned_and_the_daemons_directories_the_daemons():
    function = ENTRYPOINT[ENTRYPOINT.index("prepare_lan_sim_directory() {") :].split("\n}\n")[0]

    assert (
        f"install -d -m 0755 -o root -g root {SHARED_DIRECTORY} {SHARED_DIRECTORY}/sessions"
        in function
    )
    for name in ("status", "logs"):
        assert re.search(
            rf"install -d -m 07[05][05] -o {DAEMON_ID} -g {DAEMON_ID} {SHARED_DIRECTORY}/{name}\b",
            function,
        )


@pytest.mark.parametrize("call", ["prepare_lan_sim_directory"])
def test_the_entrypoint_makes_the_directories_before_it_hands_over_to_supervisord(call):
    assert ENTRYPOINT.index(f"\n{call}\n") < ENTRYPOINT.index("exec setpriv")
