"""Tests of `bin/lan_logic.py`: the control service's half of the fake local network.

Everything it talks to is a fake: the `guest-firewall` command is a runner that keeps a ledger, the
daemon is a function run on every sleep of the clock (so a 20 s timeout takes no time), the guests
are a dict, and the analysis storage is a folder in tmp_path.
"""

import importlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest
from hostile_files import KINDS, bounded, plant
from test_control_http import BIN  # noqa: F401 - importing it puts bin/ on sys.path

from guest_engine.errors import Conflict, GuestNotFound, InvalidParameters
from guest_engine.lan_session import (
    Layout,
    SessionStatus,
    read_status,
    session_keys,
    write_heartbeat,
    write_status,
)
from guest_engine.media import CommandResult, MediaProblem
from guest_engine.media.errors import Fault

lan_logic = importlib.import_module("lan_logic")

SUBNET = "192.168.150.0/24"
GUESTS = {"lab1": "192.168.150.11", "lab2": "192.168.150.12"}
ADMIN_PASSWORD = "Zx9-Admin-Secret"  # noqa: S105
SERVICE_PASSWORD = "Hunter2-Backup!"  # noqa: S105
PASSWORDS = (ADMIN_PASSWORD, SERVICE_PASSWORD)
WALL_NOW = 1_700_000_000.0
OWN_NAMESPACE = "net:[4026532812]"
OLD_NAMESPACE = "net:[4026531840]"
FIREWALL_COMMAND = ["python3", "-I", "/usr/local/lib/tartarus/guest-firewall"]


def a_preset(preset_id="small-office", first_offset=200):
    own = "" if preset_id == "small-office" else f"{preset_id}."
    return {
        "id": preset_id,
        "name": "Small office",
        "description": "A domain controller and a file server.",
        "domain": "corp.local",
        "hosts": [
            {
                "fqdn": f"dc01.{own}corp.local",
                "host_offset": first_offset,
                "role": "domain-controller",
                "os_banner": "Windows Server 2019",
                "accounts": [
                    {"user": "Administrator", "password": ADMIN_PASSWORD},
                    {"user": "svc_backup", "password": SERVICE_PASSWORD},
                ],
                "services": [
                    {"kind": "smb", "port": 445, "options": {"shares": ["Public"]}},
                    {"kind": "ldap", "port": 389, "options": {}},
                ],
            },
            {
                "fqdn": f"fs01.{own}corp.local",
                "host_offset": first_offset + 1,
                "role": "file-server",
                "os_banner": "Windows Server 2019",
                "accounts": [{"user": "Administrator", "password": ADMIN_PASSWORD}],
                "services": [
                    {"kind": "smb", "port": 445, "options": {}},
                    {"kind": "rdp", "port": 3389, "options": {}},
                ],
            },
        ],
    }


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeFirewall:
    """The `guest-firewall` command as the runner sees it, with a ledger like the real one's."""

    def __init__(self, stack: "Stack") -> None:
        self.stack = stack
        self.calls: list[tuple[str, ...]] = []
        self.timeouts: list[float | None] = []
        self.ledger: dict[str, dict] = {}
        self.fail: dict[str, CommandResult | Exception] = {}
        self.session_file_existed_at_open: dict[str, bool] = {}

    def __call__(self, args, timeout=None, stdin=None):
        assert list(args[:3]) == FIREWALL_COMMAND, args
        command, *rest = args[3:]
        self.calls.append((command, *rest))
        self.timeouts.append(timeout)
        failure = self.fail.get(command)
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        if command == "lan-open":
            session = json.loads(stdin.read().decode())
            self.session_file_existed_at_open[session["key"]] = self.stack.layout.session_file(
                session["key"]
            ).exists()
            self.ledger[session["key"]] = session
        elif command == "lan-close":
            self.ledger.pop(rest[0], None)
            self.stack.at_firewall_close(rest[0])
        else:
            assert command == "lan-list", command
            return CommandResult(0, "".join(f"{key}\n" for key in sorted(self.ledger)), "")
        return CommandResult(0, "", "")

    def commands(self, name: str) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] == name]


class FakeDaemon:
    """Reacts to the files like the real daemon, whenever the clock sleeps."""

    def __init__(self, layout: Layout) -> None:
        self.layout = layout
        self.opens = "listening"  # or "failed" or "silent"
        self.closes = "closed"  # or "stuck"
        self.failure = "port 445 is already in use"
        self.writes_log = True

    def react(self) -> None:
        on_disk = set(session_keys(self.layout))
        for key in sorted(on_disk):
            if read_status(self.layout, key) is None and self.opens != "silent":
                self._open(key)
        for status_file in sorted(self.layout.status_dir.glob("*.json")):
            key = status_file.stem
            status = read_status(self.layout, key)
            if key not in on_disk and status.state != "closed" and self.closes == "closed":
                self._close(key)

    def _open(self, key: str) -> None:
        if self.opens == "failed":
            write_status(self.layout, key, SessionStatus("failed", self.failure))
            return
        with self.layout.log_file(key).open("a") as log:
            log.write('{"type":"connection"}\n')
        write_status(self.layout, key, SessionStatus("listening"))

    def _close(self, key: str) -> None:
        if self.writes_log:
            with self.layout.log_file(key).open("a") as log:
                log.write('{"type":"session-end"}\n')
        write_status(self.layout, key, SessionStatus("closed"))


class Stack:
    def __init__(self, tmp_path: Path) -> None:
        self.layout = Layout(tmp_path / "lan-sim")
        self.layout.make_directories()
        self.presets_dir = tmp_path / "presets"
        self.presets_dir.mkdir()
        self.add_preset(a_preset())
        self.storage = tmp_path / "storage"
        (self.storage / "analyses" / "7").mkdir(parents=True)
        self.clock = FakeClock()
        self.wall_now = WALL_NOW
        self.daemon = FakeDaemon(self.layout)
        self.firewall = FakeFirewall(self)
        self.lines: list[str] = []
        self.order: list[str] = []
        self.sessions = lan_logic.LanSessions(
            lan_logic.LanSettings(
                layout=self.layout,
                presets_dir=self.presets_dir,
                subnet=SUBNET,
                storage=self.storage,
                firewall_command=FIREWALL_COMMAND,
            ),
            guest_address=self.guest_address,
            runner=self.firewall,
            clock=self.clock,
            sleep=self.sleep,
            wall_clock=lambda: self.wall_now,
            log=self.lines.append,
            network_namespace=lambda: OWN_NAMESPACE,
        )

    def add_preset(self, preset: dict) -> None:
        (self.presets_dir / f"{preset['id']}.json").write_text(json.dumps(preset))

    def guest_address(self, name: str) -> str:
        if name not in GUESTS:
            raise GuestNotFound(name)
        return GUESTS[name]

    def sleep(self, seconds: float) -> None:
        self.clock.now += seconds
        self.daemon.react()

    def at_firewall_close(self, key: str) -> None:
        events = self.storage / "analyses" / "7" / "lansim" / "events.jsonl"
        self.order.append(f"firewall-close(events copied: {events.exists()})")

    def beat(self, age: float | None, namespace: str = OWN_NAMESPACE) -> None:
        """Make the daemon's heartbeat `age` seconds old, or remove it."""
        alive = self.layout.alive_file
        if age is None:
            alive.unlink(missing_ok=True)
            return
        write_heartbeat(self.layout, namespace)
        os.utime(alive, (self.wall_now - age, self.wall_now - age))

    def open(self, key="analysis-7", guest="lab1", preset="small-office"):
        return self.sessions.open({"key": key, "guest": guest, "preset": preset})

    def events_file(self, task_id=7) -> Path:
        return self.storage / "analyses" / str(task_id) / "lansim" / "events.jsonl"

    def everything_said(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def stack(tmp_path):
    return Stack(tmp_path)


def nothing_is_left(stack: Stack, key: str = "analysis-7") -> None:
    assert session_keys(stack.layout) == []
    assert key not in stack.firewall.ledger
    assert not stack.layout.status_file(key).exists()


# --- GET /lan-presets -----------------------------------------------------------------------------


def test_the_presets_are_listed_as_the_api_shows_them_without_an_account(stack):
    status, body = stack.sessions.presets()

    assert status == 200
    [preset] = body["presets"]
    assert preset["id"] == "small-office"
    assert [host["address"] for host in preset["hosts"]] == ["192.168.150.200", "192.168.150.201"]
    assert not any(password in json.dumps(body) for password in PASSWORDS)


def test_presets_that_cannot_be_loaded_are_a_500_with_the_reason(stack):
    (stack.presets_dir / "broken.json").write_text("{not json")

    status, body = stack.sessions.presets()

    assert status == 500
    assert "broken.json" in body["error"]


# --- GET /lan/health ------------------------------------------------------------------------------


def test_the_service_is_ready_when_the_daemon_beats_and_the_presets_load(stack):
    stack.beat(age=0.4)

    assert stack.sessions.health() == (200, {"ready": True, "reason": None})


def test_a_heartbeat_exactly_at_the_limit_still_counts_as_alive(stack):
    stack.beat(age=lan_logic.HEARTBEAT_STALE_AFTER_S)

    assert stack.sessions.health()[1]["ready"] is True


def test_a_stale_heartbeat_is_not_ready_and_says_how_long_the_daemon_was_silent(stack):
    stack.beat(age=lan_logic.HEARTBEAT_STALE_AFTER_S + 1)

    status, body = stack.sessions.health()

    assert status == 200
    assert body["ready"] is False
    assert "has not answered for 6 s" in body["reason"]


def test_a_missing_heartbeat_file_is_not_ready(stack):
    stack.beat(age=None)

    body = stack.sessions.health()[1]

    assert body["ready"] is False
    assert "not running" in body["reason"]


def test_a_heartbeat_from_the_future_is_alive_not_an_error(stack):
    stack.beat(age=-30)

    assert stack.sessions.health()[1]["ready"] is True


def test_a_daemon_left_in_the_namespace_of_a_cape_container_that_was_recreated_is_not_ready(stack):
    stack.beat(age=0.1, namespace=OLD_NAMESPACE)

    status, body = stack.sessions.health()

    assert status == 200
    assert body["ready"] is False
    assert "old network namespace" in body["reason"]
    assert "docker compose up -d" in body["reason"]


def test_a_heartbeat_that_names_no_namespace_counts_as_the_wrong_one(stack):
    stack.beat(age=0.1, namespace="")

    body = stack.sessions.health()[1]

    assert body["ready"] is False
    assert "old network namespace" in body["reason"]


def test_a_silent_daemon_is_reported_silent_before_its_namespace_is_compared(stack):
    stack.beat(age=lan_logic.HEARTBEAT_STALE_AFTER_S + 1, namespace=OLD_NAMESPACE)

    assert "has not answered" in stack.sessions.health()[1]["reason"]


@pytest.mark.parametrize("kind", KINDS)
def test_a_heartbeat_the_daemon_made_a_pipe_a_link_or_a_directory_is_not_ready_and_never_blocks(
    stack, tmp_path, kind
):
    stack.layout.alive_file.unlink(missing_ok=True)
    plant(kind, stack.layout.alive_file, tmp_path / "secret")

    body = bounded(stack.sessions.health)[1]

    assert body["ready"] is False
    assert "not running" in body["reason"]


@pytest.mark.parametrize("damage", ["missing folder", "bad json", "address outside the block"])
def test_presets_that_do_not_load_are_not_ready_even_with_a_live_daemon(stack, damage):
    stack.beat(age=0.1)
    if damage == "missing folder":
        stack.presets_dir.rename(stack.presets_dir.with_name("gone"))
    elif damage == "bad json":
        (stack.presets_dir / "broken.json").write_text("[")
    else:
        stack.add_preset(a_preset("other", first_offset=40))

    body = stack.sessions.health()[1]

    assert body["ready"] is False
    assert body["reason"].startswith("the LAN presets cannot be loaded")


def test_health_never_says_a_password(stack):
    stack.add_preset(a_preset("other", first_offset=40))
    stack.beat(age=None)

    assert not any(password in json.dumps(stack.sessions.health()) for password in PASSWORDS)


# --- GET /lan/sessions ----------------------------------------------------------------------------


def test_no_session_anywhere_is_an_empty_list(stack):
    assert stack.sessions.keys() == (200, {"keys": []})


def test_the_keys_are_those_in_the_session_directory_and_in_the_firewall_ledger_once_each(stack):
    stack.open("analysis-3")
    stack.firewall.ledger["analysis-9"] = {}  # the file is gone, as after a restart of lan-sim
    stack.layout.session_file("analysis-5").write_text("{}")  # the ledger is gone, as after init
    stack.firewall.ledger.pop("analysis-3")
    stack.firewall.ledger["analysis-3"] = {}

    status, body = stack.sessions.keys()

    assert (status, body) == (200, {"keys": ["analysis-3", "analysis-5", "analysis-9"]})


def test_a_firewall_that_cannot_list_is_a_500_so_the_backend_tries_again(stack):
    stack.firewall.fail["lan-list"] = CommandResult(1, "", "guest-firewall: no policy")

    status, body = stack.sessions.keys()

    assert status == 500
    assert "no policy" in body["error"]


def test_a_firewall_line_that_is_not_a_key_is_ignored(stack):
    stack.firewall.fail["lan-list"] = CommandResult(0, "analysis-3\n../etc\n\n", "")

    assert stack.sessions.keys() == (200, {"keys": ["analysis-3"]})


# --- POST /lan/sessions ---------------------------------------------------------------------------


def test_opening_a_session_answers_201_with_the_key(stack):
    assert stack.open() == (201, {"key": "analysis-7"})


def test_the_firewall_is_asked_for_every_host_address_and_tcp_port_of_the_preset(stack):
    stack.open()

    [call] = stack.firewall.commands("lan-open")
    assert call == ("lan-open",)
    assert stack.firewall.ledger["analysis-7"] == {
        "key": "analysis-7",
        "guest_address": "192.168.150.11",
        "targets": [
            {"address": "192.168.150.200", "tcp_ports": [445, 389]},
            {"address": "192.168.150.201", "tcp_ports": [445, 3389]},
        ],
    }
    assert stack.firewall.timeouts == [60]


def test_the_firewall_opens_before_the_daemon_is_told_so_the_listeners_are_never_unreachable(
    stack,
):
    stack.open()

    assert stack.firewall.session_file_existed_at_open == {"analysis-7": False}


def test_the_session_file_holds_the_hosts_services_and_accounts_the_daemon_needs(stack):
    stack.open()

    document = json.loads(stack.layout.session_file("analysis-7").read_text())
    assert document["guest_address"] == "192.168.150.11"
    assert document["preset_id"] == "small-office"
    [dc, fs] = document["hosts"]
    assert (dc["fqdn"], dc["address"]) == ("dc01.corp.local", "192.168.150.200")
    assert dc["accounts"] == [
        {"user": "Administrator", "password": ADMIN_PASSWORD},
        {"user": "svc_backup", "password": SERVICE_PASSWORD},
    ]
    assert [(s["kind"], s["port"]) for s in fs["services"]] == [("smb", 445), ("rdp", 3389)]
    assert dc["services"][0]["options"] == {"shares": ["Public"]}


def test_it_answers_only_once_the_daemon_says_it_listens(stack):
    stack.daemon.opens = "silent"

    status, _body = stack.open()

    assert status == 503
    assert stack.clock.now >= lan_logic.DAEMON_TIMEOUT_S


def test_opening_the_same_session_again_is_201_and_does_not_publish_it_again(stack):
    stack.open()
    published = stack.layout.session_file("analysis-7").stat()

    assert stack.open() == (201, {"key": "analysis-7"})

    again = stack.layout.session_file("analysis-7").stat()
    assert (again.st_ino, again.st_mtime_ns) == (published.st_ino, published.st_mtime_ns)


def test_opening_the_same_session_again_runs_lan_open_again_to_heal_a_ledger_lost_in_a_restart(
    stack,
):
    stack.open()
    stack.firewall.ledger.clear()

    stack.open()

    assert "analysis-7" in stack.firewall.ledger
    assert len(stack.firewall.commands("lan-open")) == 2


def test_the_same_key_with_another_preset_is_a_conflict_and_changes_nothing(stack):
    stack.add_preset(a_preset("other", first_offset=210))
    stack.open()
    before = stack.layout.session_file("analysis-7").read_bytes()
    calls_before = list(stack.firewall.calls)

    with pytest.raises(Conflict, match="analysis-7"):
        stack.open(preset="other")

    assert stack.layout.session_file("analysis-7").read_bytes() == before
    assert stack.firewall.calls == calls_before


def test_the_same_key_for_another_guest_is_a_conflict_and_changes_nothing(stack):
    stack.open()
    calls_before = list(stack.firewall.calls)

    with pytest.raises(Conflict):
        stack.open(guest="lab2")

    assert stack.firewall.calls == calls_before


def test_another_session_already_holding_the_guests_address_is_a_conflict(stack):
    stack.open("analysis-7")
    calls_before = list(stack.firewall.calls)

    with pytest.raises(Conflict, match=r"192\.168\.150\.11"):
        stack.open("analysis-8")

    assert stack.firewall.calls == calls_before
    assert session_keys(stack.layout) == ["analysis-7"]


def test_two_guests_may_each_have_a_session(stack):
    stack.add_preset(a_preset("other", first_offset=210))
    stack.open("analysis-7", guest="lab1")

    assert stack.open("analysis-8", guest="lab2", preset="other") == (201, {"key": "analysis-8"})


def test_a_guest_that_is_not_registered_is_not_found_and_nothing_is_touched(stack):
    with pytest.raises(GuestNotFound):
        stack.open(guest="nobody")

    assert stack.firewall.calls == []
    assert session_keys(stack.layout) == []


def test_a_preset_that_does_not_exist_is_not_found_and_nothing_is_touched(stack):
    with pytest.raises(GuestNotFound, match="no-such-preset"):
        stack.open(preset="no-such-preset")

    assert stack.firewall.calls == []
    assert session_keys(stack.layout) == []


def test_a_guest_that_is_not_running_is_no_reason_to_refuse(stack):
    # The firewall binds ports by running domain: the session simply waits for the guest.
    assert stack.open(guest="lab2")[0] == 201


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"key": "analysis-7", "guest": "lab1"},
        {"key": 7, "guest": "lab1", "preset": "small-office"},
        {"key": "-bad", "guest": "lab1", "preset": "small-office"},
        {"key": "../x", "guest": "lab1", "preset": "small-office"},
        {"key": "a" * 65, "guest": "lab1", "preset": "small-office"},
        {"key": "analysis-7", "guest": "Lab 1", "preset": "small-office"},
        {"key": "analysis-7", "guest": "lab1", "preset": ["small-office"]},
        {"key": "analysis-7", "guest": "lab1", "preset": "x"},
    ],
)
def test_a_body_that_is_not_a_key_a_guest_and_a_preset_is_rejected_before_anything_runs(
    stack, body
):
    with pytest.raises(InvalidParameters):
        stack.sessions.open(body)

    assert stack.firewall.calls == []
    assert session_keys(stack.layout) == []


def test_presets_that_cannot_be_loaded_refuse_the_session_with_503_and_leave_nothing(stack):
    (stack.presets_dir / "broken.json").write_text("{")

    status, body = stack.open()

    assert status == 503
    assert "broken.json" in body["error"]
    assert stack.firewall.calls == []


# --- opening fails closed -------------------------------------------------------------------------


def test_a_daemon_that_fails_the_session_is_a_503_with_its_reason_and_nothing_stays_open(stack):
    stack.daemon.opens = "failed"

    status, body = stack.open()

    assert (status, body) == (503, {"error": "port 445 is already in use"})
    nothing_is_left(stack)
    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-7")]


def test_a_daemon_that_never_answers_is_a_503_after_20_s_and_nothing_stays_open(stack):
    stack.daemon.opens = "silent"

    status, body = stack.open()

    assert status == 503
    assert "did not start within 20 s" in body["error"]
    assert 20 <= stack.clock.now < 21
    nothing_is_left(stack)
    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-7")]


def test_a_firewall_that_refuses_is_a_503_with_its_reason_and_the_daemon_is_never_asked(stack):
    stack.firewall.fail["lan-open"] = CommandResult(1, "", "guest-firewall: nft refused it")

    status, body = stack.open()

    assert status == 503
    assert "nft refused it" in body["error"]
    nothing_is_left(stack)
    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-7")]


def test_a_firewall_command_that_cannot_run_is_a_503_and_nothing_stays_open(stack):
    stack.firewall.fail["lan-open"] = MediaProblem(Fault.TIMED_OUT, detail="python3")

    status, body = stack.open()

    assert status == 503
    assert "timed_out" in body["error"]
    nothing_is_left(stack)


def test_a_failed_open_whose_cleanup_also_fails_says_so(stack):
    stack.daemon.opens = "failed"
    stack.firewall.fail["lan-close"] = CommandResult(1, "", "guest-firewall: ledger locked")

    status, body = stack.open()

    assert status == 503
    assert "port 445 is already in use" in body["error"]
    assert "could not be closed" in body["error"]
    assert "ledger locked" in body["error"]
    assert session_keys(stack.layout) == []


def test_an_error_nobody_expected_is_still_a_503_that_cleans_up(stack, monkeypatch):
    def explode(*_arguments, **_options):
        raise RuntimeError("something odd")

    monkeypatch.setattr(lan_logic, "publish_session", explode)

    status, body = stack.open()

    assert status == 503
    assert "something odd" in body["error"]
    nothing_is_left(stack)


def test_reopening_a_session_whose_status_is_failed_cleans_up_and_is_a_503(stack):
    stack.open()
    write_status(stack.layout, "analysis-7", SessionStatus("failed", "bind failed"))

    status, body = stack.open()

    assert (status, body) == (503, {"error": "bind failed"})
    nothing_is_left(stack)


def test_a_session_that_fails_leaves_the_log_and_status_of_a_failed_open_removed(stack):
    stack.daemon.opens = "failed"
    stack.open()

    assert list(stack.layout.logs_dir.iterdir()) == []
    assert list(stack.layout.status_dir.iterdir()) == []


# --- DELETE /lan/sessions/{key} -------------------------------------------------------------------


def close_after_open(stack: Stack, task_id: int | None = 7):
    stack.open()
    return stack.sessions.close("analysis-7", task_id)


def test_closing_copies_the_log_once_the_daemon_closed_and_before_the_firewall_closes(stack):
    status, body = close_after_open(stack)

    assert (status, body) == (200, {"copied": True})
    assert stack.events_file().read_text() == '{"type":"connection"}\n{"type":"session-end"}\n'
    assert stack.order == ["firewall-close(events copied: True)"]


def test_the_copy_belongs_to_the_analysis_folder_and_is_readable_by_the_backend(stack):
    close_after_open(stack)

    assert stat.S_IMODE(stack.events_file().stat().st_mode) == 0o644
    assert stat.S_IMODE(stack.events_file().parent.stat().st_mode) == 0o755


def test_closing_removes_the_session_file_the_staged_log_and_the_status_and_the_firewall_entry(
    stack,
):
    close_after_open(stack)

    nothing_is_left(stack)
    assert list(stack.layout.logs_dir.iterdir()) == []
    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-7")]


def test_closing_without_a_task_id_copies_nothing_and_still_cleans_up(stack):
    status, body = close_after_open(stack, task_id=None)

    assert (status, body) == (200, {"copied": False})
    assert not stack.events_file().parent.exists()
    nothing_is_left(stack)
    assert list(stack.layout.logs_dir.iterdir()) == []


def test_closing_an_unknown_key_is_200_not_copied_and_does_not_wait_for_a_daemon(stack):
    assert stack.sessions.close("analysis-99", 7) == (200, {"copied": False})

    assert stack.clock.now == 0
    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-99")]


def test_closing_twice_is_harmless_and_the_second_copies_nothing(stack):
    close_after_open(stack)
    first = stack.events_file().read_bytes()

    assert stack.sessions.close("analysis-7", 7) == (200, {"copied": False})

    assert stack.events_file().read_bytes() == first


def test_a_close_that_comes_after_a_failed_first_close_cannot_overwrite_the_copy(stack):
    stack.open()
    stack.firewall.fail["lan-close"] = CommandResult(1, "", "guest-firewall: busy")
    assert stack.sessions.close("analysis-7", 7)[0] == 500
    first = stack.events_file().read_bytes()
    stack.layout.log_file("analysis-7").write_text("a later, different log\n")
    del stack.firewall.fail["lan-close"]

    assert stack.sessions.close("analysis-7", 7) == (200, {"copied": False})

    assert stack.events_file().read_bytes() == first


def test_an_existing_events_file_is_never_overwritten(stack):
    stack.events_file().parent.mkdir()
    stack.events_file().write_text("first")

    status, body = close_after_open(stack)

    assert (status, body) == (200, {"copied": False})
    assert stack.events_file().read_text() == "first"
    nothing_is_left(stack)


def test_a_daemon_that_never_says_closed_does_not_keep_the_firewall_open(stack):
    stack.open()
    stack.daemon.closes = "stuck"

    status, body = stack.sessions.close("analysis-7", 7)

    assert status == 200
    assert 20 <= stack.clock.now < 21
    assert body["copied"] is True
    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-7")]
    nothing_is_left(stack)
    assert any("did not confirm" in warning for warning in body["warnings"])


def test_a_missing_log_is_not_a_failure_and_copies_nothing(stack):
    stack.open()
    stack.layout.log_file("analysis-7").unlink()
    stack.daemon.writes_log = False

    assert stack.sessions.close("analysis-7", 7) == (200, {"copied": False})

    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-7")]
    assert not stack.events_file().parent.exists()


def test_a_task_without_an_analysis_folder_copies_nothing_creates_nothing_and_cleans_up(stack):
    stack.open()

    assert stack.sessions.close("analysis-7", 8) == (200, {"copied": False})

    assert not (stack.storage / "analyses" / "8").exists()
    nothing_is_left(stack)
    assert list(stack.layout.logs_dir.iterdir()) == []


def test_a_firewall_that_will_not_close_is_a_500_after_the_copy_and_the_cleanup(stack):
    stack.open()
    stack.firewall.fail["lan-close"] = CommandResult(1, "", "guest-firewall: lock busy")

    status, body = stack.sessions.close("analysis-7", 7)

    assert status == 500
    assert "lock busy" in body["error"]
    assert stack.events_file().exists()
    assert session_keys(stack.layout) == []
    assert list(stack.layout.logs_dir.iterdir()) == []


def test_a_firewall_command_that_cannot_run_on_close_is_a_500(stack):
    stack.open()
    stack.firewall.fail["lan-close"] = MediaProblem(Fault.TIMED_OUT, detail="python3")

    status, body = stack.sessions.close("analysis-7", None)

    assert status == 500
    assert "timed_out" in body["error"]


def test_a_copy_that_fails_keeps_the_log_so_a_retry_can_copy_it_and_still_closes_the_firewall(
    stack, monkeypatch
):
    stack.open()
    monkeypatch.setattr(lan_logic, "EVENTS_FILE", replace(lan_logic.EVENTS_FILE, limit=5))

    status, body = stack.sessions.close("analysis-7", 7)

    assert status == 200
    assert body["copied"] is False
    assert any("could not be copied" in warning for warning in body["warnings"])
    assert stack.layout.log_file("analysis-7").exists()
    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-7")]
    monkeypatch.undo()
    assert stack.sessions.close("analysis-7", 7) == (200, {"copied": True})


# --- a daemon that has been taken over leaves hostile names behind --------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_closing_a_key_whose_status_is_something_hostile_answers_and_removes_it(
    stack, tmp_path, kind
):
    status_file = stack.layout.status_file("analysis-7")
    plant(kind, status_file, tmp_path / "secret")

    status, _body = bounded(stack.sessions.close, "analysis-7", None)

    assert status == 200
    if kind == "directory":
        assert any("could not be deleted" in line for line in stack.lines)
    else:
        assert not status_file.is_symlink()
        assert not status_file.exists()


def test_closing_removes_a_link_in_place_of_a_status_without_touching_what_it_points_at(
    stack, tmp_path
):
    secret = tmp_path / "secret"
    plant("symlink", stack.layout.status_file("analysis-7"), secret)

    bounded(stack.sessions.close, "analysis-7", None)

    assert secret.read_text() == '{"state":"closed","error":null}'


def test_listing_sessions_with_a_pipe_in_the_status_directory_answers(stack):
    os.mkfifo(stack.layout.status_file("analysis-9"))

    assert bounded(stack.sessions.keys) == (200, {"keys": []})


@pytest.mark.parametrize("kind", ["fifo", "symlink", "dangling-symlink", "directory"])
def test_a_log_that_is_not_a_file_is_not_copied_warns_and_is_deleted(stack, tmp_path, kind):
    stack.open()
    log = stack.layout.log_file("analysis-7")
    log.unlink()
    stack.daemon.writes_log = False
    secret = tmp_path / "secret"
    plant(kind, log, secret)
    secret.write_text("/etc/shadow of the cape container")

    status, body = bounded(stack.sessions.close, "analysis-7", 7)

    assert status == 200
    assert body["copied"] is False
    assert any("could not be copied" in warning for warning in body["warnings"])
    assert not stack.events_file().exists()
    assert "shadow" not in "".join(
        path.read_text() for path in stack.storage.rglob("*") if path.is_file()
    )
    assert not log.is_symlink()
    assert kind == "directory" or not log.exists()


def test_a_task_folder_whose_lansim_name_is_a_file_is_a_warning_not_a_crash(stack):
    stack.open()
    (stack.storage / "analyses" / "7" / "lansim").write_text("in the way")

    status, body = stack.sessions.close("analysis-7", 7)

    assert status == 200
    assert body["copied"] is False
    assert any("could not be copied" in warning for warning in body["warnings"])
    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-7")]


def test_a_failure_to_retract_the_file_does_not_stop_the_rest(stack, monkeypatch):
    stack.open()

    def refuse(*_arguments):
        raise PermissionError("read-only")

    monkeypatch.setattr(lan_logic, "retract_session", refuse)

    status, body = stack.sessions.close("analysis-7", 7)

    assert status == 200
    assert any("could not be removed" in warning for warning in body["warnings"])
    assert stack.firewall.commands("lan-close") == [("lan-close", "analysis-7")]


def test_a_close_that_went_well_has_no_warnings_in_the_answer(stack):
    assert "warnings" not in close_after_open(stack)[1]


def test_closing_a_session_whose_status_is_still_listening_after_its_file_went_waits_for_closed(
    stack,
):
    write_status(stack.layout, "analysis-7", SessionStatus("listening"))

    assert stack.sessions.close("analysis-7", None) == (200, {"copied": False})

    assert read_status(stack.layout, "analysis-7") is None
    assert stack.clock.now > 0


def test_the_events_of_the_session_are_copied_even_when_the_firewall_entry_is_long_gone(stack):
    stack.open()
    stack.firewall.ledger.clear()

    assert stack.sessions.close("analysis-7", 7) == (200, {"copied": True})


# --- a password is never said ---------------------------------------------------------------------


def test_no_answer_and_no_log_line_holds_a_password_through_a_whole_session(stack, capsys):
    answers = [
        stack.open(),
        stack.sessions.keys(),
        stack.sessions.health(),
        stack.sessions.presets(),
    ]
    with pytest.raises(Conflict) as conflict:
        stack.open("analysis-8")
    answers.append(str(conflict.value))
    stack.daemon.opens = "failed"
    stack.daemon.failure = f"login {ADMIN_PASSWORD} refused by {SERVICE_PASSWORD}"
    stack.sessions.close("analysis-7", 7)
    answers.append(stack.open())
    answers.append(stack.sessions.close("analysis-7", 7))

    said = json.dumps(answers) + stack.everything_said() + "".join(capsys.readouterr())
    for password in PASSWORDS:
        assert password not in said
    assert stack.lines  # something was logged, so the check above means something


def test_a_daemon_error_that_echoes_a_password_is_redacted_in_the_answer(stack):
    stack.daemon.opens = "failed"
    stack.daemon.failure = f"bad option {SERVICE_PASSWORD} for dc01"

    status, body = stack.open()

    assert status == 503
    assert SERVICE_PASSWORD not in body["error"]
    assert "bad option" in body["error"]


def test_the_firewall_never_receives_a_password(stack):
    stack.open()

    assert not any(password in json.dumps(stack.firewall.ledger) for password in PASSWORDS)


def test_the_log_says_which_session_and_what_happened_without_the_session_file(stack):
    stack.open()
    stack.sessions.close("analysis-7", 7)

    text = stack.everything_said()
    assert "analysis-7" in text
    assert "small-office" in text


# --- the firewall command -------------------------------------------------------------------------


def test_the_session_reaches_the_firewall_as_json_on_a_real_file_the_program_can_read():
    seen = {}

    def runner(args, timeout=None, stdin=None):
        seen["stdin"] = stdin.read()
        seen["fileno"] = stdin.fileno()
        return CommandResult(0, "", "")

    lan_logic.FirewallCommand(FIREWALL_COMMAND, runner).open_session({"key": "analysis-7"})

    assert json.loads(seen["stdin"]) == {"key": "analysis-7"}
    assert seen["fileno"] > 2
