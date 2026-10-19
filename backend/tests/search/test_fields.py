import pytest

from app.search.fields import (
    COMPOSITE_ALIASES,
    FIELDS,
    FieldDefinition,
    FieldType,
    Lane,
    field_by_name,
    resolve_composite,
    resolve_field,
)

COMMON = [
    "@timestamp",
    "event.id",
    "event.sequence",
    "event.kind",
    "event.category",
    "event.type",
    "event.action",
    "event.module",
    "event.dataset",
    "event.severity",
    "event.outcome",
    "tartarus.analysis_id",
    "tartarus.lane",
    "tartarus.phase",
    "tartarus.summary",
    "tartarus.raw",
]
PROCESS = [
    "process.pid",
    "process.parent.pid",
    "process.thread.id",
    "process.name",
    "process.parent.name",
    "process.parent.executable",
    "process.parent.command_line",
    "process.executable",
    "process.command_line",
    "process.entity_id",
    "process.start",
    "process.integrity_level",
]
FILE = [
    "file.path",
    "file.name",
    "file.extension",
    "file.size",
    "file.hash.sha256",
    "file.target_path",
]
REGISTRY = [
    "registry.path",
    "registry.hive",
    "registry.key",
    "registry.value",
    "registry.data.type",
    "registry.data.strings",
]
NETWORK = [
    "source.ip",
    "source.port",
    "destination.ip",
    "destination.port",
    "destination.domain",
    "network.transport",
    "network.protocol",
    "dns.question.name",
    "dns.question.type",
    "dns.answers.data",
    "url.full",
    "http.request.method",
    "http.response.status_code",
    "user_agent.original",
    "tls.server.sni",
    "tls.server.ja3s",
    "tls.client.ja3",
]
API = [
    "api.name",
    "api.category",
    "api.status",
    "api.return_value",
    "api.arguments",
    "api.repeated",
]
MEMORY = [
    "tartarus.memory.plugin",
    "tartarus.memory.address",
    "tartarus.memory.protection",
    "tartarus.memory.dump_ref",
    "tartarus.memory.note",
]
DETECTION = [
    "rule.id",
    "rule.name",
    "rule.description",
    "rule.ruleset",
    "rule.reference",
    "threat.technique.id",
    "threat.technique.name",
    "threat.tactic.name",
    "related.events",
    "related.hash",
    "related.ip",
    "related.hosts",
    "tartarus.detection.match",
    "tartarus.detection.repeated",
]
INJECTION = [
    "tartarus.inject.target_pid",
    "tartarus.inject.target_name",
    "tartarus.inject.target_executable",
    "tartarus.inject.target_command_line",
]
ACCOUNT_AND_ERROR = ["user.name", "user.domain", "error.code", "error.message"]
DEFENDER = [
    "tartarus.defender.detection_id",
    "tartarus.defender.scope",
    "tartarus.defender.action_id",
    "tartarus.defender.category_id",
    "tartarus.defender.state",
    "tartarus.defender.status_code",
    "tartarus.defender.clock",
]
SPEC_FIELDS = (
    COMMON
    + PROCESS
    + INJECTION
    + FILE
    + REGISTRY
    + NETWORK
    + API
    + MEMORY
    + DETECTION
    + ACCOUNT_AND_ERROR
    + DEFENDER
)


def test_the_catalog_holds_exactly_the_fields_of_the_data_model_spec() -> None:
    assert sorted(field.name for field in FIELDS) == sorted(SPEC_FIELDS)


def test_field_names_are_unique() -> None:
    names = [field.name for field in FIELDS]
    assert len(names) == len(set(names))


def test_no_field_is_the_parent_object_of_another() -> None:
    names = {field.name for field in FIELDS}
    parents = {name.rsplit(".", 1)[0] for name in names if "." in name}
    assert names.isdisjoint(parents)


def test_aliases_never_collide_with_each_other_or_with_field_names() -> None:
    claimed = [field.name for field in FIELDS]
    claimed += [alias for field in FIELDS for alias in field.aliases]
    assert len(claimed) == len(set(claimed))


def test_every_field_is_described_and_has_an_example() -> None:
    assert [f.name for f in FIELDS if not f.description.strip() or not f.example.strip()] == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("@timestamp", FieldType.DATE),
        ("event.sequence", FieldType.LONG),
        ("event.severity", FieldType.INTEGER),
        ("event.category", FieldType.KEYWORD),
        ("process.pid", FieldType.LONG),
        ("tartarus.inject.target_pid", FieldType.LONG),
        ("process.name", FieldType.KEYWORD),
        ("process.command_line", FieldType.KEYWORD_WITH_TEXT),
        ("process.executable", FieldType.KEYWORD_WITH_TEXT),
        ("process.parent.executable", FieldType.KEYWORD_WITH_TEXT),
        ("process.parent.command_line", FieldType.KEYWORD_WITH_TEXT),
        ("tartarus.inject.target_name", FieldType.KEYWORD),
        ("tartarus.inject.target_executable", FieldType.KEYWORD_WITH_TEXT),
        ("tartarus.inject.target_command_line", FieldType.KEYWORD_WITH_TEXT),
        ("tartarus.detection.repeated", FieldType.LONG),
        ("file.path", FieldType.KEYWORD_WITH_TEXT),
        ("tartarus.summary", FieldType.KEYWORD_WITH_TEXT),
        ("source.ip", FieldType.IP),
        ("destination.port", FieldType.LONG),
        ("related.ip", FieldType.IP),
        ("api.status", FieldType.BOOLEAN),
        ("api.arguments", FieldType.FLAT_OBJECT),
        ("tartarus.raw", FieldType.OBJECT_DISABLED),
    ],
)
def test_field_types_follow_the_spec(name: str, expected: FieldType) -> None:
    assert field_by_name(name).type is expected


def test_fields_carry_their_lane_only_when_the_spec_assigns_one() -> None:
    assert field_by_name("file.path").lane is Lane.FILE
    assert field_by_name("registry.key").lane is Lane.REGISTRY
    assert field_by_name("dns.question.name").lane is Lane.NETWORK
    assert field_by_name("api.name").lane is Lane.API
    assert field_by_name("tartarus.memory.plugin").lane is Lane.MEMORY
    assert field_by_name("tartarus.inject.target_pid").lane is Lane.PROCESS
    assert field_by_name("tartarus.inject.target_name").lane is Lane.PROCESS
    assert field_by_name("tartarus.inject.target_executable").lane is Lane.PROCESS
    assert field_by_name("tartarus.inject.target_command_line").lane is Lane.PROCESS
    assert field_by_name("event.id").lane is None
    assert field_by_name("rule.name").lane is None


def test_field_by_name_rejects_an_unknown_name() -> None:
    with pytest.raises(KeyError):
        field_by_name("no.such.field")


def test_resolve_field_accepts_names_and_aliases() -> None:
    process_pid = field_by_name("process.pid")
    assert resolve_field("process.pid") is process_pid
    alias = process_pid.aliases[0]
    assert resolve_field(alias) is process_pid


def test_resolve_field_returns_none_for_an_unknown_name() -> None:
    assert resolve_field("no.such.field") is None


def test_field_definitions_are_immutable() -> None:
    with pytest.raises(AttributeError):
        field_by_name("process.pid").name = "x"  # type: ignore[misc]


def test_every_field_has_the_catalog_record_type() -> None:
    assert all(isinstance(field, FieldDefinition) for field in FIELDS)


SPEC_ALIASES = {
    "pid": "process.pid",
    "ppid": "process.parent.pid",
    "proc": "process.name",
    "cmd": "process.command_line",
    "api": "api.name",
    "path": "file.path",
    "reg": "registry.path",
    "ip": "destination.ip",
    "port": "destination.port",
    "url": "url.full",
    "lane": "tartarus.lane",
    "action": "event.action",
    "rule": "rule.name",
    "sev": "event.severity",
    "technique": "threat.technique.id",
}


@pytest.mark.parametrize(("alias", "name"), sorted(SPEC_ALIASES.items()))
def test_every_alias_of_the_query_spec_resolves_to_its_field(alias: str, name: str) -> None:
    assert resolve_field(alias) is field_by_name(name)


def test_existing_aliases_are_kept() -> None:
    assert resolve_field("cmdline") is field_by_name("process.command_line")
    assert resolve_field("severity") is field_by_name("event.severity")
    assert resolve_field("process") is field_by_name("process.name")


def test_domain_is_a_composite_alias_and_no_single_field_alias() -> None:
    assert COMPOSITE_ALIASES["domain"] == ("dns.question.name", "destination.domain")
    assert resolve_field("domain") is None
    assert [f.name for f in resolve_composite("domain")] == [
        "dns.question.name",
        "destination.domain",
    ]


def test_resolve_composite_returns_nothing_for_a_plain_name() -> None:
    assert resolve_composite("process.name") == ()


def test_composite_aliases_collide_with_no_field_name_or_alias() -> None:
    singles = {field.name for field in FIELDS} | {a for f in FIELDS for a in f.aliases}
    assert singles.isdisjoint(COMPOSITE_ALIASES)


def test_composite_members_are_catalog_fields() -> None:
    members = {name for names in COMPOSITE_ALIASES.values() for name in names}
    assert members <= {field.name for field in FIELDS}
