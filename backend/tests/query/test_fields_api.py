from app.query.fields_api import FieldInfo, field_catalog, suggest_fields
from app.search.fields import COMPOSITE_ALIASES, FIELDS, FieldType, Lane


def info(name: str) -> FieldInfo:
    (found,) = [entry for entry in field_catalog() if entry.name == name]
    return found


def names(prefix: str, limit: int = 20) -> list[str]:
    return [entry.name for entry in suggest_fields(prefix, limit)]


def test_the_catalog_lists_every_field_then_every_composite_alias() -> None:
    listed = [entry.name for entry in field_catalog()]
    assert listed == [*(field.name for field in FIELDS), *COMPOSITE_ALIASES]


def test_a_plain_field_carries_what_the_autocomplete_shows() -> None:
    port = info("destination.port")
    assert port.type is FieldType.LONG
    assert port.aliases == ("dst.port", "port")
    assert port.description == "Destination port"
    assert port.example == "443"
    assert port.lane is Lane.NETWORK
    assert port.members == ()
    assert port.searchable


def test_a_composite_alias_lists_the_fields_it_stands_for() -> None:
    domain = info("domain")
    assert domain.members == ("dns.question.name", "destination.domain")
    assert domain.type is FieldType.KEYWORD
    assert domain.aliases == ()
    assert domain.lane is Lane.NETWORK
    assert domain.description == "dns.question.name or destination.domain"
    assert domain.example == "example.com"
    assert domain.searchable


def test_only_the_raw_record_is_marked_not_searchable() -> None:
    assert [entry.name for entry in field_catalog() if not entry.searchable] == ["tartarus.raw"]


def test_a_prefix_finds_fields_by_name() -> None:
    assert names("process.p") == [
        "process.pid",
        "process.parent.pid",
        "process.parent.name",
        "process.parent.executable",
        "process.parent.command_line",
    ]


def test_a_prefix_is_case_insensitive() -> None:
    assert names("PROCESS.PI") == ["process.pid"]


def test_a_prefix_finds_a_field_through_its_alias() -> None:
    assert "process.name" in names("proc")
    assert names("sev") == ["event.severity"]


def test_a_prefix_of_a_composite_alias_finds_it() -> None:
    assert names("dom") == ["domain", "destination.domain", "user.domain"]


def test_prefix_matches_come_before_alias_matches_before_matches_inside_a_name() -> None:
    assert names("path") == ["file.path", "file.target_path", "registry.path"]
    assert names("reg")[0] == "registry.path"


def test_a_fragment_inside_a_name_is_found_after_the_prefix_matches() -> None:
    found = names("name")
    assert "process.name" in found
    assert "api.name" in found


def test_the_limit_caps_the_list() -> None:
    assert len(names("", limit=5)) == 5


def test_an_empty_prefix_lists_the_searchable_fields_in_catalog_order() -> None:
    found = names("", limit=1000)
    assert found[0] == "@timestamp"
    assert "tartarus.raw" not in found
    assert found.count("domain") == 1


def test_nothing_matches_nonsense() -> None:
    assert names("zzzz") == []


def test_the_raw_record_is_never_suggested() -> None:
    assert "tartarus.raw" not in names("tartarus.r")
