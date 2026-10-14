"""Query text compiled and run on the real index; the expected sets come from a plain scan.

The index holds the events of the real, trimmed analysis 6. Each case names the query and a Python
predicate over the normalised documents (`fixture_events`, which the ingester also indexes), and
the expected count is pinned too, so a predicate that matches nothing by mistake cannot pass.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest

from app.query.compiler import compile_query
from tests.integration.views.conftest import ViewStack
from tests.integration.views.fixture_events import fixture_events
from tests.integration.views.helpers import indexed_events

pytestmark = pytest.mark.integration

Event = dict[str, Any]
Predicate = Callable[[Event], bool]


def values(event: Event, path: str) -> list[Any]:
    node: Any = event
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    if node is None:
        return []
    return node if isinstance(node, list) else [node]


def lowered(event: Event, path: str) -> list[str]:
    return [str(value).lower() for value in values(event, path)]


def is_(path: str, *wanted: str) -> Predicate:
    targets = {item.lower() for item in wanted}
    return lambda event: any(value in targets for value in lowered(event, path))


def matches(path: str, glob: str) -> Predicate:
    pattern = re.compile(
        "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in glob.lower()),
        re.DOTALL,
    )
    return lambda event: any(pattern.fullmatch(value) for value in lowered(event, path))


def exists(path: str) -> Predicate:
    return lambda event: bool(values(event, path))


def number(path: str, test: Callable[[int], bool]) -> Predicate:
    return lambda event: any(test(int(value)) for value in values(event, path))


def argument_values(event: Event) -> list[str]:
    arguments = (event.get("api") or {}).get("arguments") or {}
    return [str(value).lower() for value in arguments.values()]


def argument_value(event: Event, name: str) -> list[str]:
    arguments = (event.get("api") or {}).get("arguments") or {}
    return [str(arguments[name]).lower()] if name in arguments else []


def contains_anywhere(text: str) -> Predicate:
    needle = text.lower()
    searched = ("tartarus.summary", "process.command_line", "file.path", "url.full")

    def predicate(event: Event) -> bool:
        texts = [t for path in searched for t in lowered(event, path)] + argument_values(event)
        return any(needle in t for t in texts)

    return predicate


def any_argument(test: Callable[[str], bool]) -> Predicate:
    return lambda event: any(test(value) for value in argument_values(event))


def named_argument(name: str, test: Callable[[str], bool]) -> Predicate:
    return lambda event: any(test(value) for value in argument_value(event, name))


def all_of(*predicates: Predicate) -> Predicate:
    return lambda event: all(p(event) for p in predicates)


def any_of(*predicates: Predicate) -> Predicate:
    return lambda event: any(p(event) for p in predicates)


def not_(predicate: Predicate) -> Predicate:
    return lambda event: not predicate(event)


def instant_ms(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def timestamp_ms(event: Event) -> int:
    return instant_ms(event["@timestamp"])


def process_start_ms(event: Event) -> list[int]:
    return [instant_ms(value) for value in values(event, "process.start")]


@dataclass(frozen=True)
class Case:
    query: str
    expected: Predicate
    count: int


NOON = instant_ms("2026-10-13T12:12:42Z")
BUSY_MS = instant_ms("2026-10-13T12:12:42.258Z")

CASES = [
    Case("lane:network", is_("tartarus.lane", "network"), 213),
    Case("tartarus.lane:API", is_("tartarus.lane", "api"), 471),
    Case(
        "process.name:cmd.exe AND lane:network",
        all_of(is_("process.name", "cmd.exe"), is_("tartarus.lane", "network")),
        0,
    ),
    Case("process.name:CMD.EXE", is_("process.name", "cmd.exe"), 223),
    Case("PROCESS.NAME:cmd.exe", is_("process.name", "cmd.exe"), 223),
    Case("proc:Benign.EXE", is_("process.name", "benign.exe"), 257),
    Case("process.name:*.EXE", matches("process.name", "*.exe"), 480),
    Case("process.name:*", exists("process.name"), 480),
    Case("NOT process.name:*", not_(exists("process.name")), 223),
    Case('NOT process.name:"explorer.exe"', not_(is_("process.name", "explorer.exe")), 703),
    Case("NOT process.name:cmd.exe", not_(is_("process.name", "cmd.exe")), 480),
    Case("api:(NtWriteFile OR NtCreateFile)", is_("api.name", "NtWriteFile", "NtCreateFile"), 30),
    Case("api:Nt*File", matches("api.name", "nt*file"), 97),
    Case("api:NtClose OR api:RegCloseKey", is_("api.name", "NtClose", "RegCloseKey"), 83),
    Case(
        "api:(NtClose OR RegCloseKey) NOT process.name:cmd.exe",
        all_of(is_("api.name", "NtClose", "RegCloseKey"), not_(is_("process.name", "cmd.exe"))),
        47,
    ),
    Case(r"file.path:*\\Temp\\*", matches("file.path", "*\\temp\\*"), 2),
    Case(r"file.path:*\Temp\*", matches("file.path", "*\\temp\\*"), 2),
    Case(
        r'file.path:"C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt"',
        is_("file.path", "C:\\Users\\Analyst\\AppData\\Local\\Temp\\tartarus-benign.txt"),
        2,
    ),
    Case("path:*TARTARUS-BENIGN.TXT", matches("file.path", "*tartarus-benign.txt"), 2),
    Case(
        r"file.path:*\\AppData\\Roaming\\*.exe",
        matches("file.path", "*\\appdata\\roaming\\*.exe"),
        0,
    ),
    Case(
        r"reg:HKEY_CURRENT_USER\\Software\\Tartarus*",
        matches("registry.path", "hkey_current_user\\software\\tartarus*"),
        2,
    ),
    Case("registry.path:*selftest", matches("registry.path", "*selftest"), 1),
    Case("destination.port >= 1024", number("destination.port", lambda p: p >= 1024), 0),
    Case(
        "destination.port >= 80 AND destination.port < 443",
        number("destination.port", lambda p: 80 <= p < 443),
        114,
    ),
    Case("port:(80 OR 443)", number("destination.port", lambda p: p in (80, 443)), 203),
    Case("destination.port:53", number("destination.port", lambda p: p == 53), 4),
    Case("event.severity >= 2", number("event.severity", lambda s: s >= 2), 8),
    Case("sev >= 3", number("event.severity", lambda s: s >= 3), 1),
    Case("sev:0", number("event.severity", lambda s: s == 0), 691),
    Case("rule.ruleset:cape", is_("rule.ruleset", "cape"), 12),
    Case("rule.ruleset:sigma", is_("rule.ruleset", "sigma"), 0),
    Case(
        "rule.ruleset:cape AND event.severity >= 2",
        all_of(is_("rule.ruleset", "cape"), number("event.severity", lambda s: s >= 2)),
        8,
    ),
    Case("technique:T1055", is_("threat.technique.id", "T1055"), 2),
    Case("technique:t1055", is_("threat.technique.id", "T1055"), 2),
    Case("technique:(T1055 OR T1071)", is_("threat.technique.id", "T1055", "T1071"), 3),
    Case("technique:T10*", matches("threat.technique.id", "t10*"), 4),
    Case("technique:*", exists("threat.technique.id"), 7),
    Case(
        "event.kind:alert AND NOT technique:*",
        all_of(is_("event.kind", "alert"), not_(exists("threat.technique.id"))),
        5,
    ),
    Case("msftconnecttest", contains_anywhere("msftconnecttest"), 4),
    Case(
        "MSFTCONNECTTEST GET",
        all_of(contains_anywhere("msftconnecttest"), contains_anywhere("get")),
        2,
    ),
    Case('"cmd.exe /c ver"', contains_anywhere("cmd.exe /c ver"), 225),
    Case("tartarus-benign", contains_anywhere("tartarus-benign"), 4),
    Case("NTOPENKEY", contains_anywhere("ntopenkey"), 4),
    Case("*.txt", contains_anywhere(".txt"), 6),
    Case("powershell -enc", all_of(contains_anywhere("powershell"), contains_anywhere("-enc")), 0),
    Case("NOT benign.exe", not_(contains_anywhere("benign.exe")), 445),
    Case(
        "domain:*.example",
        any_of(
            matches("dns.question.name", "*.example"), matches("destination.domain", "*.example")
        ),
        2,
    ),
    Case(
        "domain:*msftconnecttest.com",
        any_of(
            matches("dns.question.name", "*msftconnecttest.com"),
            matches("destination.domain", "*msftconnecttest.com"),
        ),
        4,
    ),
    Case("domain:*", any_of(exists("dns.question.name"), exists("destination.domain")), 8),
    Case("dns.question.name:outlook.office.com", is_("dns.question.name", "outlook.office.com"), 1),
    Case("api.arguments:SHELL32.DLL", any_argument(lambda v: v == "shell32.dll"), 1),
    Case("api.arguments:*tartarus*", any_argument(lambda v: "tartarus" in v), 5),
    Case(
        "api.arguments.FileName:shell32.dll",
        named_argument("FileName", lambda v: v == "shell32.dll"),
        1,
    ),
    Case(
        "api.arguments.FileName:*TARTARUS-BENIGN*",
        named_argument("FileName", lambda v: "tartarus-benign" in v),
        1,
    ),
    Case("api.arguments.ModuleName:*", lambda e: bool(argument_value(e, "ModuleName")), 39),
    Case("api.status:false", lambda e: values(e, "api.status") == [False], 31),
    Case(
        "api.status:TRUE AND NOT lane:file",
        lambda e: values(e, "api.status") == [True] and not is_("tartarus.lane", "file")(e),
        440,
    ),
    Case(
        "NOT (lane:api OR lane:network)",
        not_(any_of(is_("tartarus.lane", "api"), is_("tartarus.lane", "network"))),
        19,
    ),
    Case(
        "NOT (lane:api OR lane:network) NOT event.kind:alert",
        all_of(
            not_(any_of(is_("tartarus.lane", "api"), is_("tartarus.lane", "network"))),
            not_(is_("event.kind", "alert")),
        ),
        7,
    ),
    Case("lane:file OR lane:registry", is_("tartarus.lane", "file", "registry"), 4),
    Case(
        "event.action:(process-created OR process-terminated)",
        is_("event.action", "process-created", "process-terminated"),
        3,
    ),
    Case("event.category:registry", is_("event.category", "registry"), 52),
    Case("tartarus.phase:final", is_("tartarus.phase", "final"), 703),
    Case("NOT tartarus.phase:final", not_(is_("tartarus.phase", "final")), 0),
    Case("pid:9632", number("process.pid", lambda p: p == 9632), 223),
    Case(
        "process.pid:10116 AND ppid:4336",
        all_of(
            number("process.pid", lambda p: p == 10116),
            number("process.parent.pid", lambda p: p == 4336),
        ),
        257,
    ),
    Case("ppid:10116", number("process.parent.pid", lambda p: p == 10116), 223),
    Case("ip:192.168.150.1", is_("destination.ip", "192.168.150.1"), 205),
    Case("ip:192.168.150.0/24", is_("destination.ip", "192.168.150.1"), 205),
    Case("ip:10.0.0.0/8", is_("destination.ip", "10.0.0.1"), 0),
    Case(
        "source.ip:192.168.150.10 AND port:443",
        all_of(is_("source.ip", "192.168.150.10"), number("destination.port", lambda p: p == 443)),
        89,
    ),
    Case("destination.ip > 192.168.150.0", is_("destination.ip", "192.168.150.1"), 205),
    Case("url:*connecttest.txt", matches("url.full", "*connecttest.txt"), 2),
    Case(
        "url:http://www.msftconnecttest.com/connecttest.txt",
        is_("url.full", "http://www.msftconnecttest.com/connecttest.txt"),
        1,
    ),
    Case('cmd:"cmd.exe /c ver"', is_("process.command_line", "cmd.exe /c ver"), 223),
    Case(
        "process.command_line:ver",
        lambda e: "ver" in re.split(r"\W+", " ".join(lowered(e, "process.command_line"))),
        223,
    ),
    Case("process.command_line:*/c*", matches("process.command_line", "*/c*"), 223),
    Case(
        'tartarus.summary:"benign.exe called NtOpenKey"',
        is_("tartarus.summary", "benign.exe called NtOpenKey"),
        1,
    ),
    Case(
        "rule.description:geofencing",
        lambda e: "geofencing" in re.split(r"\W+", " ".join(lowered(e, "rule.description"))),
        2,
    ),
    Case(
        "rule.description:geofenc*",
        lambda e: any(
            w.startswith("geofenc")
            for w in re.split(r"\W+", " ".join(lowered(e, "rule.description")))
        ),
        2,
    ),
    Case("@timestamp:2026-10-13", lambda e: e["@timestamp"].startswith("2026-10-13"), 703),
    Case("@timestamp:2026-10-14", lambda e: e["@timestamp"].startswith("2026-10-14"), 0),
    Case("@timestamp >= 2026-10-13T12:12:42Z", lambda e: timestamp_ms(e) >= NOON, 359),
    Case("@timestamp < 2026-10-13T12:12:42Z", lambda e: timestamp_ms(e) < NOON, 344),
    Case(f"@timestamp > {NOON}", lambda e: timestamp_ms(e) > NOON, 359),
    Case("@timestamp > 2026-10-13T12:12:42.258Z", lambda e: timestamp_ms(e) > BUSY_MS, 78),
    Case("@timestamp >= 2026-10-13T12:12:42.258Z", lambda e: timestamp_ms(e) >= BUSY_MS, 184),
    Case("@timestamp <= 2026-10-13T12:12:42.258Z", lambda e: timestamp_ms(e) <= BUSY_MS, 625),
    Case("@timestamp:2026-10-13T12:12:42.258Z", lambda e: timestamp_ms(e) == BUSY_MS, 106),
    Case(
        "rule.ruleset:sigma AND event.severity >= 3",
        all_of(is_("rule.ruleset", "sigma"), number("event.severity", lambda s: s >= 3)),
        0,
    ),
    Case(
        "destination.port >= 1024 AND dns.question.name:*.onion",
        all_of(
            number("destination.port", lambda p: p >= 1024),
            matches("dns.question.name", "*.onion"),
        ),
        0,
    ),
    Case(
        'api:(NtWriteVirtualMemory OR NtCreateThreadEx) NOT process.name:"explorer.exe"',
        all_of(
            is_("api.name", "NtWriteVirtualMemory", "NtCreateThreadEx"),
            not_(is_("process.name", "explorer.exe")),
        ),
        0,
    ),
    Case(
        "process.start > 2026-10-13T12:12:41.500Z",
        lambda e: any(ms > instant_ms("2026-10-13T12:12:41.500Z") for ms in process_start_ms(e)),
        223,
    ),
    Case(
        "process.start <= 2026-10-13T12:12:41.164Z",
        lambda e: any(ms <= instant_ms("2026-10-13T12:12:41.164Z") for ms in process_start_ms(e)),
        257,
    ),
]


async def search_ids(stack: ViewStack, text: str) -> set[str]:
    compiled = compile_query(text)
    assert compiled.errors == [], text
    body: dict[str, Any] = {"size": 10_000, "_source": False, "track_total_hits": True}
    body["query"] = compiled.query if compiled.query is not None else {"match_all": {}}
    response = await stack.index.search(stack.analysis_id, body)
    assert response["_shards"]["failed"] == 0, text
    return {hit["_id"] for hit in response["hits"]["hits"]}


def failures(
    cases: list[Case], events: dict[str, Event], results: dict[str, set[str]]
) -> Iterator[str]:
    for case in cases:
        expected = {i for i, event in events.items() if case.expected(event)}
        got = results[case.query]
        if expected != got or len(expected) != case.count:
            yield (
                f"{case.query!r}: expected {len(expected)} (pinned {case.count}), got {len(got)}; "
                f"missing {len(expected - got)}, extra {len(got - expected)}"
            )


def fingerprint(event: Event) -> tuple[Any, ...]:
    """Identifies an event without its ids and sequence, which depend on the analysis."""
    return (event["@timestamp"], event["event"]["dataset"], event["tartarus"].get("summary"))


async def test_an_empty_query_matches_every_event_the_report_normalises_to(
    view_stack: ViewStack,
) -> None:
    events = await indexed_events(view_stack)

    assert await search_ids(view_stack, "") == set(events)
    assert sorted(map(fingerprint, events.values()), key=str) == sorted(
        map(fingerprint, fixture_events()), key=str
    )


async def test_every_query_of_the_table_finds_exactly_the_events_a_plain_scan_finds(
    view_stack: ViewStack,
) -> None:
    events = await indexed_events(view_stack)
    results = {case.query: await search_ids(view_stack, case.query) for case in CASES}

    assert list(failures(CASES, events, results)) == []
    assert len(CASES) >= 25
