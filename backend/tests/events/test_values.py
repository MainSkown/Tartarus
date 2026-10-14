import pytest

from app.errors import ApiError
from app.events.values import build_values_body, include_pattern, read_values, value_paths
from app.schemas.events_api import ValueCount


@pytest.mark.parametrize(
    ("prefix", "pattern"),
    [
        ("cmd", "cmd.*"),
        ("Cmd.EXE", r"cmd\.exe.*"),
        ("C:\\Win", r"c:\\win.*"),
        ("a+b(c)[d]{e}|f?g*h", r"a\+b\(c\)\[d\]\{e\}\|f\?g\*h.*"),
        ('"~#@&<>', r"\"\~\#\@\&\<\>.*"),
    ],
)
def test_the_prefix_becomes_an_escaped_lowercase_regex_for_the_indexed_terms(
    prefix: str, pattern: str
) -> None:
    assert include_pattern(prefix) == pattern


def test_no_prefix_means_every_value() -> None:
    assert include_pattern("") is None


def test_a_plain_keyword_field_is_one_path() -> None:
    assert value_paths("process") == ["process.name"]
    assert value_paths("process.executable") == ["process.executable"]


def test_the_domain_alias_covers_both_its_fields() -> None:
    assert value_paths("domain") == ["dns.question.name", "destination.domain"]


@pytest.mark.parametrize(
    "field",
    [
        "process.pid",
        "@timestamp",
        "rule.description",
        "api.arguments",
        "tartarus.raw",
        "nope",
        "source.ip",
    ],
)
def test_only_keyword_fields_have_values(field: str) -> None:
    with pytest.raises(ApiError) as caught:
        value_paths(field)

    assert caught.value.status_code == 422
    assert caught.value.code == "invalid_value_field"


def test_the_body_asks_each_field_for_its_top_values_matching_the_prefix() -> None:
    body = build_values_body(["dns.question.name", "destination.domain"], "Ex", 5)

    assert body["size"] == 0
    assert body["query"] == {"match_all": {}}
    assert body["aggs"] == {
        "values_0": {"terms": {"field": "dns.question.name", "size": 5, "include": "ex.*"}},
        "values_1": {"terms": {"field": "destination.domain", "size": 5, "include": "ex.*"}},
    }


def test_the_body_without_a_prefix_has_no_include() -> None:
    body = build_values_body(["process.name"], "", 10)

    assert "include" not in body["aggs"]["values_0"]["terms"]


def test_the_values_of_several_fields_are_merged_by_summing_counts() -> None:
    response = {
        "aggregations": {
            "values_0": {
                "buckets": [{"key": "a.example", "doc_count": 2}, {"key": "b", "doc_count": 5}]
            },
            "values_1": {
                "buckets": [{"key": "a.example", "doc_count": 4}, {"key": "c", "doc_count": 1}]
            },
        }
    }

    values = read_values(2, response).values

    assert values == [ValueCount(value="a.example", count=6), ValueCount(value="b", count=5)]
    assert read_values(10, response).values[-1] == ValueCount(value="c", count=1)


def test_equal_counts_come_in_alphabetical_order() -> None:
    response = {
        "aggregations": {
            "values_0": {"buckets": [{"key": "b", "doc_count": 1}, {"key": "a", "doc_count": 1}]}
        }
    }

    assert [value.value for value in read_values(10, response).values] == ["a", "b"]


def test_an_analysis_with_no_events_has_no_values() -> None:
    assert read_values(10, {"aggregations": {}}).values == []
