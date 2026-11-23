from datetime import UTC, datetime, timedelta

import pytest

from app.ingest.lan_derived import (
    CREDENTIAL_SPRAY,
    FAN_OUT,
    SWEEP,
    BurstRule,
    Sighting,
    bursts,
)

T0 = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)


def sighting(host: int, seconds: float, service: str | None = "smb") -> Sighting:
    return Sighting(
        time=T0 + timedelta(seconds=seconds),
        host=f"ws{host}.corp.local",
        address=f"192.168.150.{200 + host}",
        service=service,
        port=445,
        process=None,
        event_id=None,
    )


def hosts_of(burst: list[Sighting]) -> list[str]:
    return [s.host for s in burst]


def test_the_thresholds_are_the_numbers_the_plan_set_from_the_flood_data() -> None:
    assert (SWEEP.min_hosts, SWEEP.window) == (5, timedelta(seconds=30))
    assert (FAN_OUT.min_hosts, FAN_OUT.min_services, FAN_OUT.window) == (4, 2, timedelta(minutes=5))
    assert (CREDENTIAL_SPRAY.min_hosts, CREDENTIAL_SPRAY.window) == (3, timedelta(minutes=5))


def test_four_distinct_hosts_are_not_a_sweep_and_five_are() -> None:
    assert bursts([sighting(n, n) for n in range(4)], SWEEP) == []

    [burst] = bursts([sighting(n, n) for n in range(5)], SWEEP)

    assert len(burst) == 5


def test_a_sweep_that_takes_exactly_thirty_seconds_counts_and_thirty_one_does_not() -> None:
    inside = [sighting(n, n * 7.5) for n in range(5)]
    outside = [sighting(n, n * 7.75) for n in range(5)]

    assert len(bursts(inside, SWEEP)) == 1
    assert bursts(outside, SWEEP) == []


def test_the_same_host_many_times_is_one_host() -> None:
    assert bursts([sighting(1, n) for n in range(40)], SWEEP) == []


def test_unsorted_sightings_are_ordered_by_time() -> None:
    [burst] = bursts([sighting(n, 10 - n) for n in range(5)], SWEEP)

    assert [s.time for s in burst] == sorted(s.time for s in burst)


def test_a_window_may_start_late_when_the_early_sightings_were_alone() -> None:
    sightings = [sighting(0, 0)] + [sighting(n, 31 + n) for n in range(1, 6)]

    [burst] = bursts(sightings, SWEEP)

    assert hosts_of(burst) == [f"ws{n}.corp.local" for n in range(1, 6)]


def test_a_long_scan_is_one_burst_per_window_not_one_per_member() -> None:
    scan = [sighting(n % 9, n) for n in range(20)]

    assert len(bursts(scan, SWEEP)) == 1


def test_two_scans_far_apart_are_two_bursts() -> None:
    scans = [sighting(n, n) for n in range(5)] + [sighting(n, 600 + n) for n in range(5)]

    assert [len(burst) for burst in bursts(scans, SWEEP)] == [5, 5]


def test_fan_out_needs_two_services_as_well_as_four_hosts() -> None:
    one_service = [sighting(n, n, "smb") for n in range(4)]
    two_services = [sighting(n, n, "smb" if n < 2 else "rdp") for n in range(4)]
    three_hosts = [sighting(n, n, "smb" if n < 2 else "rdp") for n in range(3)]

    assert bursts(one_service, FAN_OUT) == []
    assert len(bursts(two_services, FAN_OUT)) == 1
    assert bursts(three_hosts, FAN_OUT) == []


def test_a_sighting_without_a_known_service_adds_a_host_but_no_service() -> None:
    mixed = [
        sighting(0, 0, "smb"),
        sighting(1, 1, None),
        sighting(2, 2, None),
        sighting(3, 3, None),
    ]

    assert bursts(mixed, FAN_OUT) == []


def test_fan_out_takes_exactly_five_minutes_and_not_one_second_more() -> None:
    def spread(last: float) -> list[Sighting]:
        return [
            sighting(0, 0, "smb"),
            sighting(1, 1, "rdp"),
            sighting(2, 2, "smb"),
            sighting(3, last, "smb"),
        ]

    assert len(bursts(spread(300), FAN_OUT)) == 1
    assert bursts(spread(302), FAN_OUT) == []


def test_credential_spray_is_three_hosts_in_five_minutes() -> None:
    assert bursts([sighting(n, n * 100) for n in range(2)], CREDENTIAL_SPRAY) == []
    assert len(bursts([sighting(n, n * 150) for n in range(3)], CREDENTIAL_SPRAY)) == 1
    assert bursts([sighting(n, n * 151) for n in range(3)], CREDENTIAL_SPRAY) == []


def test_a_rule_names_its_event_and_nothing_is_found_in_no_sightings() -> None:
    rule = BurstRule("lan-sweep", timedelta(seconds=1), 1)

    assert bursts([], rule) == []
    assert rule.action == "lan-sweep"


@pytest.mark.parametrize("rule", [SWEEP, FAN_OUT, CREDENTIAL_SPRAY])
def test_every_rule_names_a_distinct_event_action(rule: BurstRule) -> None:
    assert rule.action.startswith("lan-")
    assert len({SWEEP.action, FAN_OUT.action, CREDENTIAL_SPRAY.action}) == 3
