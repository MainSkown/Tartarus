"""The session log: the JSONL records, the caps and the aggregation that keep a flood bounded."""

import json
from dataclasses import replace

from support import FakeClock, ListSink

from lan_sim.events import Endpoint
from lan_sim.limits import Limits
from lan_sim.session_log import SessionLog

SRC = Endpoint("192.168.150.10", 50123)
DST = Endpoint("192.168.150.201", 445)
SHA = "ab" * 32


class Rig:
    def __init__(self, **limits):
        self.clock = FakeClock()
        self.sink = ListSink()
        self.log = SessionLog("task-1", self.sink, self.clock, replace(Limits(), **limits))

    def login(self, user="admin", secret="pw", host="fs01.corp.local", service="smb"):
        return self.log.record(
            "login-attempt",
            host=host,
            service=service,
            src=SRC,
            dst=DST,
            user=user,
            domain="CORP",
            mechanism="ntlm",
            secret=secret,
            success=False,
        )

    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.sink.lines]

    def of_type(self, event_type: str) -> list[dict]:
        return [record for record in self.records() if record["type"] == event_type]

    def finish(self) -> dict:
        self.log.close()
        return self.of_type("session-end")[-1]


# --- the records ----------------------------------------------------------------------------------


def test_a_login_attempt_is_one_json_line_with_the_common_fields():
    rig = Rig()

    assert rig.login(user="Administrator", secret="s")

    assert rig.records() == [
        {
            "time": "2026-11-23T12:00:00.000Z",
            "type": "login-attempt",
            "host": "fs01.corp.local",
            "service": "smb",
            "src": {"ip": "192.168.150.10", "port": 50123},
            "dst": {"ip": "192.168.150.201", "port": 445},
            "user": "Administrator",
            "domain": "CORP",
            "mechanism": "ntlm",
            "secret": "s",
            "success": False,
        }
    ]


def test_the_time_comes_from_the_injected_clock():
    rig = Rig()
    rig.clock.advance(1.5)

    rig.login()

    assert rig.records()[0]["time"] == "2026-11-23T12:00:01.500Z"


def test_every_line_is_ascii_json_whatever_a_client_sent():
    rig = Rig()
    rig.login(user="a\nb\x00\u202e\ud800" + "x" * 10_000_000, secret="\n" * 100)

    for line in rig.sink.lines:
        line.encode("ascii")
        assert "\n" not in line
        json.loads(line)


def test_the_connection_log_has_one_method_per_event_type():
    rig = Rig()
    connection_log = rig.log.connection_log("fs01.corp.local", "smb", SRC, DST)

    connection_log.login_attempt(user="u", domain="d", mechanism="basic", secret="s", success=True)
    connection_log.share_access(share="C$", path="\\x", operation="read")
    connection_log.file_write(share="C$", path="\\x", size=5, sha256=SHA, truncated=False)
    connection_log.service_request(name="CreateService", detail="evil.exe")
    connection_log.connection(bytes_in=10, bytes_out=20, duration_ms=30)

    assert [record["type"] for record in rig.records()] == [
        "login-attempt",
        "share-access",
        "file-write",
        "service-request",
        "connection",
    ]
    assert rig.records()[2]["sha256"] == SHA
    assert rig.records()[4]["duration_ms"] == 30
    assert all(record["host"] == "fs01.corp.local" for record in rig.records())
    assert all(record["dst"] == {"ip": "192.168.150.201", "port": 445} for record in rig.records())


# --- the first events in full, then an aggregate --------------------------------------------------


def test_events_past_the_per_service_cap_become_one_aggregate():
    rig = Rig(full_events_per_service=3)

    results = [rig.login(user=f"user{n}", secret=f"secret{n}") for n in range(8)]

    assert results == [True] * 3 + [False] * 5
    assert len(rig.of_type("login-attempt")) == 3
    rig.log.close()
    [aggregate] = rig.of_type("aggregate")
    assert aggregate["host"] == "fs01.corp.local"
    assert aggregate["service"] == "smb"
    assert aggregate["count"] == 5
    assert aggregate["by_type"] == {"login-attempt": 5}
    assert aggregate["users"] == ["user3", "user4", "user5", "user6", "user7"]


def test_the_aggregate_keeps_few_distinct_usernames_and_secrets():
    rig = Rig(full_events_per_service=0, max_aggregate_usernames=2, max_aggregate_secrets=2)

    for n in range(10):
        rig.login(user=f"user{n % 5}", secret=f"secret{n % 4}")
    rig.log.close()

    [aggregate] = rig.of_type("aggregate")
    assert aggregate["count"] == 10
    assert aggregate["users"] == ["user0", "user1"]
    assert aggregate["secrets"] == ["secret0", "secret1"]


def test_the_aggregate_cuts_long_usernames_and_secrets_shorter_than_an_event_does():
    rig = Rig(
        full_events_per_service=0, max_aggregate_username_length=10, max_aggregate_secret_length=20
    )

    rig.login(user="u" * 200, secret="s" * 2000)
    rig.log.close()

    [aggregate] = rig.of_type("aggregate")
    assert len(aggregate["users"][0]) == 10
    assert len(aggregate["secrets"][0]) == 20


def test_the_aggregate_records_first_and_last_time():
    rig = Rig(full_events_per_service=0)
    rig.login()
    rig.clock.advance(5)
    rig.login()
    rig.log.close()

    [aggregate] = rig.of_type("aggregate")
    assert aggregate["first_time"] == "2026-11-23T12:00:00.000Z"
    assert aggregate["last_time"] == "2026-11-23T12:00:05.000Z"


def test_the_cap_is_per_host_and_service_not_per_session():
    rig = Rig(full_events_per_service=1)

    assert rig.login(host="a.corp.local", service="smb")
    assert not rig.login(host="a.corp.local", service="smb")
    assert rig.login(host="b.corp.local", service="smb")
    assert rig.login(host="a.corp.local", service="rdp")


def test_events_of_one_service_share_the_cap_whatever_their_type():
    rig = Rig(full_events_per_service=2)
    connection_log = rig.log.connection_log("fs01.corp.local", "smb", SRC, DST)

    connection_log.connection(bytes_in=0, bytes_out=0, duration_ms=1)
    connection_log.connection(bytes_in=0, bytes_out=0, duration_ms=1)
    connection_log.share_access(share="C$", path="x", operation="read")

    assert len(rig.records()) == 2
    rig.log.close()
    assert rig.of_type("aggregate")[0]["by_type"] == {"share-access": 1}


# --- the rate cap ---------------------------------------------------------------------------------


def test_above_the_rate_cap_events_are_only_counted_until_the_next_second():
    rig = Rig(max_events_per_second=2)

    first_second = [rig.login(user=f"a{n}") for n in range(5)]
    rig.clock.advance(1.0)
    next_second = [rig.login(user=f"b{n}") for n in range(3)]

    assert first_second == [True, True, False, False, False]
    assert next_second == [True, True, False]
    end = rig.finish()
    assert end["counters"]["events_rate_limited"] == 4
    assert end["counters"]["events_logged"] == 4
    assert rig.of_type("aggregate")[0]["count"] == 4


# --- the hard cap ---------------------------------------------------------------------------------


def test_after_the_event_cap_only_the_aggregates_and_the_final_record_are_written():
    rig = Rig(max_events_per_session=5, full_events_per_service=100, max_events_per_second=100)

    for n in range(50):
        rig.login(user=f"user{n}")

    assert len(rig.sink.lines) == 5
    end = rig.finish()
    assert end["log_truncated"] is True
    assert end["counters"]["events_logged"] == 5
    assert end["counters"]["events_hard_capped"] == 45
    assert rig.of_type("aggregate")[0]["count"] == 45


def test_the_byte_cap_stops_the_log_before_it_is_exceeded():
    rig = Rig(max_log_bytes_per_session=1000, full_events_per_service=100_000)

    for n in range(100):
        rig.login(user=f"user{n}")

    written = sum(len(line) + 1 for line in rig.sink.lines)
    assert written <= 1000
    assert rig.finish()["log_truncated"] is True


def test_a_small_event_after_the_byte_cap_does_not_slip_in():
    rig = Rig(max_log_bytes_per_session=700, full_events_per_service=100_000)
    assert rig.login(secret="x" * 300)

    assert not rig.login(secret="x" * 300)
    assert not rig.login(secret="")

    assert len(rig.sink.lines) == 1


def test_a_flood_of_ten_thousand_logins_leaves_a_bounded_log_with_exact_counts():
    rig = Rig()

    for n in range(10_000):
        rig.login(user=f"user{n}", secret=f"hash{n}")

    end = rig.finish()
    assert len(rig.sink.lines) <= 200 + 1 + 1
    counters = end["counters"]
    assert counters["events_by_type"]["login-attempt"] == 10_000
    assert counters["events_logged"] == 200
    assert counters["events_rate_limited"] + counters["events_aggregated"] == 9_800
    [aggregate] = rig.of_type("aggregate")
    assert aggregate["count"] == 9_800
    assert len(aggregate["users"]) == 50
    assert len(aggregate["secrets"]) == 5


# --- the final record -----------------------------------------------------------------------------


def test_close_writes_the_session_end_record_with_every_counter():
    rig = Rig()
    connection_log = rig.log.connection_log("fs01.corp.local", "smb", SRC, DST)
    connection_log.connection(bytes_in=10, bytes_out=20, duration_ms=5)
    connection_log.connection(bytes_in=1, bytes_out=2, duration_ms=5)
    rig.log.count_refused("connections-per-session")
    rig.log.count_refused("connections-per-session")
    rig.log.count_refused("host-not-in-session")

    end = rig.finish()

    assert end["session"] == "task-1"
    assert end["log_truncated"] is False
    assert end["counters"] == {
        "connections": 2,
        "bytes_in": 11,
        "bytes_out": 22,
        "events_logged": 2,
        "events_by_type": {"connection": 2},
        "events_aggregated": 0,
        "events_rate_limited": 0,
        "events_hard_capped": 0,
        "write_errors": 0,
        "refused": {"connections-per-session": 2, "host-not-in-session": 1},
    }
    assert "host" not in end


def test_the_session_end_record_is_last_and_close_closes_the_sink():
    rig = Rig(full_events_per_service=1)
    rig.login()
    rig.login()

    rig.log.close()

    assert [record["type"] for record in rig.records()] == [
        "login-attempt",
        "aggregate",
        "session-end",
    ]
    assert rig.sink.closed


def test_close_twice_writes_one_session_end_and_nothing_after_it_is_logged():
    rig = Rig()
    rig.log.close()
    rig.log.close()

    assert not rig.login()

    assert [record["type"] for record in rig.records()] == ["session-end"]


def test_a_failing_sink_loses_events_but_never_raises():
    class Broken(ListSink):
        def write_line(self, line):
            raise OSError("disk full")

    rig = Rig()
    rig.sink = Broken()
    rig.log = SessionLog("task-1", rig.sink, rig.clock, Limits())

    assert not rig.login()
    assert not rig.login()
    rig.log.close()

    assert rig.sink.closed


def test_write_errors_are_counted_in_the_final_record():
    class FailsOnce(ListSink):
        failed = False

        def write_line(self, line):
            if not self.failed:
                self.failed = True
                raise OSError("disk full")
            super().write_line(line)

    rig = Rig()
    rig.sink = FailsOnce()
    rig.log = SessionLog("task-1", rig.sink, rig.clock, Limits())

    rig.login()
    rig.login()
    end = rig.finish()

    assert end["counters"]["write_errors"] == 1
