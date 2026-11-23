"""The entry point, run as the container runs it: a process, a root directory, SIGTERM."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from lan_session import (
    HostSpec,
    Layout,
    ServiceSpec,
    SessionSpec,
    publish_session,
    wait_for_status,
)
from lan_sim.__main__ import build_registry

PROJECT = Path(__file__).resolve().parents[1]
SHARED = PROJECT.parent / "cape" / "guest_engine"
PASSWORD = "Sup3rSecret-Password1"


def test_the_registry_is_empty_until_a_protocol_registers():
    assert build_registry() == {}


def test_a_session_of_an_unregistered_kind_fails_and_sigterm_stops_the_process_cleanly(tmp_path):
    layout = Layout(tmp_path)
    layout.make_directories()
    host = HostSpec(
        "fs01.corp.local",
        "127.0.0.3",
        "Windows",
        (("Administrator", PASSWORD),),
        (ServiceSpec("smb", 445),),
    )
    environment = {
        **os.environ,
        "LAN_SIM_ROOT": str(tmp_path),
        "LAN_SIM_POLL_SECONDS": "0.05",
        "PYTHONPATH": os.pathsep.join([str(PROJECT), str(SHARED)]),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "lan_sim"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        publish_session(layout, SessionSpec("task-1", "127.0.0.2", "small-office", (host,)))
        status = wait_for_status(layout, "task-1", {"listening", "failed"}, timeout=10)
        process.send_signal(signal.SIGTERM)
        output, errors = process.communicate(timeout=10)
    finally:
        process.kill()

    assert status.state == "failed"
    assert status.error == "no service registered for kind 'smb'"
    assert process.returncode == 0, errors
    lines = [json.loads(line) for line in output.splitlines()]
    assert lines
    assert all(set(line) == {"time", "level", "message"} for line in lines)
    assert PASSWORD not in output + errors
