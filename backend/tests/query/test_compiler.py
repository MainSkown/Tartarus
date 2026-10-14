import time
from typing import Any

import pytest

from app.query.compiler import compile_query
from app.query.errors import QueryError
from app.query.limits import (
    MAX_DEPTH,
    MAX_QUERY_LENGTH,
    MAX_TERMS,
    MAX_WILDCARD_TERMS,
)

Query = dict[str, Any]
DATE_HINT = "use ISO 8601 (2026-10-13T10:12:41Z) or epoch milliseconds"


def term(field: str, value: Any) -> Query:
    return {"term": {field: value}}


def wildcard(field: str, pattern: str) -> Query:
    return {"wildcard": {field: {"value": pattern, "case_insensitive": True}}}


def phrase(field: str, text: str) -> Query:
    return {"match_phrase": {field: text}}


def exists(field: str) -> Query:
    return {"exists": {"field": field}}


def should(*clauses: Query) -> Query:
    return {"bool": {"should": list(clauses), "minimum_should_match": 1}}


def must_not(clause: Query) -> Query:
    return {"bool": {"must_not": [clause]}}


def every(*clauses: Query) -> Query:
    return {"bool": {"filter": list(clauses)}}


def ci_term(field: str, value: str) -> Query:
    return {"term": {field: {"value": value, "case_insensitive": True}}}


def query_of(text: str) -> Query:
    compiled = compile_query(text)
    assert compiled.errors == []
    assert compiled.query is not None
    return compiled.query


def errors_of(text: str) -> list[QueryError]:
    compiled = compile_query(text)
    assert compiled.query is None
    assert compiled.errors
    return compiled.errors


def only_error(text: str) -> QueryError:
    (error,) = errors_of(text)
    return error


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_an_empty_query_matches_everything(text: str) -> None:
    compiled = compile_query(text)
    assert compiled.query is None
    assert compiled.errors == []


def test_the_compiled_query_says_whether_it_is_usable() -> None:
    assert compile_query("pid:4").ok
    assert compile_query("").ok
    assert not compile_query("pid:abc").ok


class TestKeywordFields:
    def test_a_plain_value_is_a_term_lowercased_like_the_index_normalizer(self) -> None:
        assert query_of("process.name:CMD.EXE") == term("process.name", "cmd.exe")

    def test_a_quoted_value_is_the_same_as_a_bare_one(self) -> None:
        assert query_of('process.name:"explorer.exe"') == term("process.name", "explorer.exe")

    def test_a_wildcard_value_is_a_case_insensitive_wildcard_query(self) -> None:
        assert query_of("process.name:*.EXE") == wildcard("process.name", "*.exe")

    def test_a_question_mark_is_a_wildcard_too(self) -> None:
        assert query_of("file.extension:p?1") == wildcard("file.extension", "p?1")

    def test_backslashes_in_a_wildcard_are_escaped_for_the_wildcard_syntax(self) -> None:
        query = query_of(r"registry.path:HKLM\\Software\\*")
        assert query == wildcard("registry.path", "hklm\\\\software\\\\*")

    def test_backslashes_in_a_plain_value_are_kept_as_they_are(self) -> None:
        assert query_of(r"registry.path:HKLM\\Software\\Run") == term(
            "registry.path", "hklm\\software\\run"
        )

    def test_lowercasing_follows_the_one_to_one_rule_of_the_index_normalizer(self) -> None:
        assert query_of("process.name:İ") == term("process.name", "i")

    def test_a_group_of_plain_values_is_one_terms_query(self) -> None:
        assert query_of("api:(NtWriteFile OR NtCreateFile)") == {
            "terms": {"api.name": ["ntwritefile", "ntcreatefile"]}
        }

    def test_a_group_with_a_wildcard_is_a_bool_should(self) -> None:
        assert query_of("api:(NtWriteFile OR Nt*Thread*)") == should(
            term("api.name", "ntwritefile"), wildcard("api.name", "nt*thread*")
        )

    def test_a_group_of_one_value_is_the_value(self) -> None:
        assert query_of("api:(NtWriteFile)") == term("api.name", "ntwritefile")

    def test_field_star_is_an_exists_query(self) -> None:
        assert query_of("process.name:*") == exists("process.name")

    def test_there_is_no_regular_expression_syntax(self) -> None:
        query = query_of("process.name:/a.*b/")
        assert query == wildcard("process.name", "/a.*b/")
        assert "regexp" not in str(query)


class TestKeywordWithTextFields:
    def test_a_plain_value_is_the_exact_value_or_a_phrase_of_the_text_subfield(self) -> None:
        assert query_of('process.command_line:"cmd.exe /C ver"') == should(
            term("process.command_line", "cmd.exe /c ver"),
            phrase("process.command_line.text", "cmd.exe /C ver"),
        )

    def test_a_wildcard_value_is_a_wildcard_on_the_keyword_only(self) -> None:
        assert query_of("file.path:*.EXE") == wildcard("file.path", "*.exe")

    def test_a_group_merges_all_alternatives_into_one_flat_should(self) -> None:
        assert query_of("file.path:(a OR b*)") == should(
            term("file.path", "a"), phrase("file.path.text", "a"), wildcard("file.path", "b*")
        )

    def test_the_spec_example_with_doubled_backslashes_matches_single_backslash_paths(self) -> None:
        assert query_of(r"file.path:*\\AppData\\Roaming\\*.exe") == wildcard(
            "file.path", "*\\\\appdata\\\\roaming\\\\*.exe"
        )

    def test_exists_works_on_these_fields(self) -> None:
        assert query_of("file.path:*") == exists("file.path")


class TestTextFields:
    def test_a_plain_value_is_a_phrase_query(self) -> None:
        assert query_of('rule.description:"temp directory"') == phrase(
            "rule.description", "temp directory"
        )

    def test_a_wildcard_value_is_a_per_word_wildcard(self) -> None:
        assert query_of("rule.description:Exec*") == wildcard("rule.description", "exec*")

    def test_a_wildcard_across_words_is_refused(self) -> None:
        error = only_error('rule.description:"temp *"')
        assert (error.start, error.end) == (17, 25)
        assert error.message == (
            "a wildcard on the text field rule.description matches one word: remove the spaces"
        )


class TestNumberFields:
    def test_a_value_is_a_term_with_a_number(self) -> None:
        assert query_of("pid:4") == term("process.pid", 4)

    @pytest.mark.parametrize(
        ("operator", "bound"),
        [(">", "gt"), (">=", "gte"), ("<", "lt"), ("<=", "lte")],
    )
    def test_each_range_operator_is_a_range_bound(self, operator: str, bound: str) -> None:
        assert query_of(f"destination.port {operator} 1024") == {
            "range": {"destination.port": {bound: 1024}}
        }

    def test_a_group_is_a_terms_query(self) -> None:
        assert query_of("port:(80 OR 443)") == {"terms": {"destination.port": [80, 443]}}

    def test_integer_fields_work_like_long_fields(self) -> None:
        assert query_of("event.severity >= 2") == {"range": {"event.severity": {"gte": 2}}}

    def test_a_negative_number_is_allowed(self) -> None:
        assert query_of("process.pid > -1") == {"range": {"process.pid": {"gt": -1}}}

    def test_field_star_is_an_exists_query(self) -> None:
        assert query_of("pid:*") == exists("process.pid")

    @pytest.mark.parametrize(
        ("text", "start", "end", "message"),
        [
            ("pid:abc", 4, 7, "'abc' is not a whole number"),
            ("pid:1.5", 4, 7, "'1.5' is not a whole number"),
            ("pid:(1 OR x)", 10, 11, "'x' is not a whole number"),
            ("port > 80k", 7, 10, "'80k' is not a whole number"),
            ("pid:1*", 4, 6, "process.pid is a number field: wildcards are not supported"),
            ("pid:?", 4, 5, "process.pid is a number field: wildcards are not supported"),
            ('pid:""', 4, 6, "empty value"),
        ],
    )
    def test_a_value_that_is_not_a_number_is_an_error_over_that_value(
        self, text: str, start: int, end: int, message: str
    ) -> None:
        error = only_error(text)
        assert (error.start, error.end, error.message) == (start, end, message)


class TestDateFields:
    def test_an_iso_value_with_a_colon_is_the_whole_instant_or_day_as_a_range(self) -> None:
        assert query_of("@timestamp:2026-10-13") == {
            "range": {"@timestamp": {"gte": "2026-10-13", "lte": "2026-10-13"}}
        }

    def test_an_epoch_value_with_a_colon_is_the_same_instant_on_both_bounds(self) -> None:
        assert query_of("@timestamp:1760350361000") == {
            "range": {"@timestamp": {"gte": 1760350361000, "lte": 1760350361000}}
        }

    def test_a_comparison_passes_an_iso_value_to_the_range(self) -> None:
        assert query_of("@timestamp >= 2026-10-13T12:12:42Z") == {
            "range": {"@timestamp": {"gte": "2026-10-13T12:12:42Z"}}
        }

    def test_a_quoted_iso_value_may_carry_fractions_and_offsets(self) -> None:
        text = '@timestamp < "2026-10-13T12:12:42.123+02:00"'
        assert query_of(text) == {"range": {"@timestamp": {"lt": "2026-10-13T12:12:42.123+02:00"}}}

    def test_an_all_digit_value_is_epoch_milliseconds(self) -> None:
        assert query_of("process.start > 1760350361000") == {
            "range": {"process.start": {"gt": 1760350361000}}
        }

    @pytest.mark.parametrize(
        ("text", "start", "end", "message"),
        [
            (
                "@timestamp > yesterday",
                13,
                22,
                f"'yesterday' is not a date: {DATE_HINT}",
            ),
            (
                "@timestamp > 2026-13-45",
                13,
                23,
                f"'2026-13-45' is not a date: {DATE_HINT}",
            ),
            (
                "@timestamp:2026-10-1*",
                11,
                21,
                "@timestamp is a date field: wildcards are not supported",
            ),
        ],
    )
    def test_a_value_that_is_not_a_date_is_an_error_over_that_value(
        self, text: str, start: int, end: int, message: str
    ) -> None:
        error = only_error(text)
        assert (error.start, error.end, error.message) == (start, end, message)


class TestBooleanFields:
    @pytest.mark.parametrize(("text", "value"), [("true", True), ("FALSE", False)])
    def test_true_and_false_are_terms_in_any_case(self, text: str, value: bool) -> None:
        assert query_of(f"api.status:{text}") == term("api.status", value)

    def test_other_words_are_an_error(self) -> None:
        error = only_error("api.status:maybe")
        assert (error.start, error.end) == (11, 16)
        assert error.message == "'maybe' is not true or false"

    def test_ranges_are_an_error(self) -> None:
        error = only_error("api.status > true")
        assert (
            error.message
            == "'>' needs a number, date or ip field, and api.status is a boolean field"
        )


class TestIpFields:
    def test_an_address_is_a_term(self) -> None:
        assert query_of("ip:93.184.216.34") == term("destination.ip", "93.184.216.34")

    def test_a_cidr_range_is_a_term_too(self) -> None:
        assert query_of("destination.ip:10.0.0.0/8") == term("destination.ip", "10.0.0.0/8")

    def test_an_ipv6_address_is_a_term(self) -> None:
        assert query_of("source.ip:fe80::1") == term("source.ip", "fe80::1")

    def test_a_comparison_is_a_range_on_one_address(self) -> None:
        assert query_of("destination.ip > 10.0.0.1") == {
            "range": {"destination.ip": {"gt": "10.0.0.1"}}
        }

    @pytest.mark.parametrize(
        ("text", "start", "end", "message"),
        [
            ("ip:999.1.1.1", 3, 12, "'999.1.1.1' is not an IP address or CIDR range"),
            ("ip > 10.0.0.0/8", 5, 15, "'10.0.0.0/8' is not an IP address"),
            (
                "ip:10.0.*",
                3,
                9,
                "destination.ip is an ip field: wildcards are not supported, use a CIDR range",
            ),
        ],
    )
    def test_a_value_that_is_not_an_address_is_an_error_over_that_value(
        self, text: str, start: int, end: int, message: str
    ) -> None:
        error = only_error(text)
        assert (error.start, error.end, error.message) == (start, end, message)


class TestFlatObjectFields:
    def test_a_value_matches_any_argument_value_case_insensitively(self) -> None:
        assert query_of("api.arguments:Shell32.DLL") == ci_term("api.arguments", "shell32.dll")

    def test_a_wildcard_value_matches_any_argument_value(self) -> None:
        assert query_of("api.arguments:*TEMP*") == wildcard("api.arguments", "*temp*")

    def test_a_named_argument_is_addressed_by_a_dotted_path_that_keeps_its_case(self) -> None:
        assert query_of("api.arguments.FileName:shell32.dll") == ci_term(
            "api.arguments.FileName", "shell32.dll"
        )

    def test_the_path_prefix_is_case_insensitive_but_the_argument_name_is_not(self) -> None:
        assert query_of("API.Arguments.FileName:x") == ci_term("api.arguments.FileName", "x")

    def test_a_group_of_values_is_a_bool_should(self) -> None:
        assert query_of("api.arguments.FileName:(a OR b*)") == should(
            ci_term("api.arguments.FileName", "a"), wildcard("api.arguments.FileName", "b*")
        )

    def test_exists_works_on_a_named_argument(self) -> None:
        assert query_of("api.arguments.FileName:*") == exists("api.arguments.FileName")

    def test_a_range_is_an_error(self) -> None:
        error = only_error("api.arguments.Size > 5")
        assert error.message == (
            "'>' needs a number, date or ip field, and api.arguments.Size is a text field"
        )

    def test_an_argument_path_must_name_something(self) -> None:
        error = only_error("api.arguments.:x")
        assert error.message.startswith("unknown field 'api.arguments.'")


class TestDisabledFields:
    @pytest.mark.parametrize("text", ["tartarus.raw:x", "tartarus.raw:*"])
    def test_the_raw_record_is_not_searchable(self, text: str) -> None:
        error = only_error(text)
        assert (error.start, error.end) == (0, len("tartarus.raw"))
        assert error.message == "tartarus.raw is stored but not searchable"


class TestFieldNames:
    @pytest.mark.parametrize(
        ("alias", "field"),
        [
            ("pid", "process.pid"),
            ("ppid", "process.parent.pid"),
            ("proc", "process.name"),
            ("cmd", "process.command_line"),
            ("api", "api.name"),
            ("path", "file.path"),
            ("reg", "registry.path"),
            ("url", "url.full"),
            ("lane", "tartarus.lane"),
            ("action", "event.action"),
            ("rule", "rule.name"),
            ("technique", "threat.technique.id"),
        ],
    )
    def test_the_aliases_of_the_spec_reach_their_field(self, alias: str, field: str) -> None:
        assert query_of(f"{alias}:*") == exists(field)

    def test_the_numeric_aliases_reach_their_field(self) -> None:
        assert query_of("sev >= 3") == {"range": {"event.severity": {"gte": 3}}}
        assert query_of("port:80") == term("destination.port", 80)
        assert query_of("ip:1.2.3.4") == term("destination.ip", "1.2.3.4")

    def test_names_and_aliases_are_case_insensitive(self) -> None:
        assert query_of("PROCESS.NAME:x") == term("process.name", "x")
        assert query_of("Proc:x") == term("process.name", "x")
        assert query_of("@TIMESTAMP > 5") == {"range": {"@timestamp": {"gt": 5}}}

    def test_domain_stands_for_the_dns_name_or_the_destination_domain(self) -> None:
        assert query_of("domain:example.com") == should(
            term("dns.question.name", "example.com"), term("destination.domain", "example.com")
        )

    def test_a_composite_alias_works_with_wildcards_groups_and_exists(self) -> None:
        assert query_of("domain:*.onion") == should(
            wildcard("dns.question.name", "*.onion"), wildcard("destination.domain", "*.onion")
        )
        assert query_of("domain:*") == should(
            exists("dns.question.name"), exists("destination.domain")
        )
        assert query_of("domain:(a OR b)") == should(
            {"terms": {"dns.question.name": ["a", "b"]}},
            {"terms": {"destination.domain": ["a", "b"]}},
        )

    def test_not_over_a_composite_alias_excludes_both_fields(self) -> None:
        assert query_of("NOT domain:x") == must_not(
            should(term("dns.question.name", "x"), term("destination.domain", "x"))
        )

    def test_a_composite_alias_reports_a_problem_once(self) -> None:
        error = only_error("domain > 5")
        assert error.message == "'>' needs a number, date or ip field, and domain is a text field"

    def test_destination_domain_is_still_a_field_of_its_own(self) -> None:
        assert query_of("destination.domain:x") == term("destination.domain", "x")

    @pytest.mark.parametrize(
        ("text", "start", "end", "message", "suggestion"),
        [
            (
                "proc.name:cmd.exe",
                0,
                9,
                "unknown field 'proc.name'; did you mean 'process.name'?",
                "process.name",
            ),
            (
                "x AND destination.prot:80",
                6,
                22,
                "unknown field 'destination.prot'; did you mean 'destination.port', "
                "'destination.ip'?",
                "destination.port",
            ),
            (
                "pid:1 OR sevrity > 2",
                9,
                16,
                "unknown field 'sevrity'; did you mean 'severity'?",
                "severity",
            ),
            (
                "http://evil.example",
                0,
                4,
                "unknown field 'http'; put text that contains ':' in quotes to search for it",
                None,
            ),
            (
                "xyzzy:1",
                0,
                5,
                "unknown field 'xyzzy'; put text that contains ':' in quotes to search for it",
                None,
            ),
        ],
    )
    def test_an_unknown_field_is_an_error_over_the_field_with_a_suggestion(
        self, text: str, start: int, end: int, message: str, suggestion: str | None
    ) -> None:
        error = only_error(text)
        assert (error.start, error.end) == (start, end)
        assert error.message == message
        assert error.suggestion == suggestion

    def test_every_unknown_field_of_the_query_is_reported(self) -> None:
        errors = errors_of("foo:1 AND pid:2 AND bar:3")
        assert [(e.start, e.end) for e in errors] == [(0, 3), (20, 23)]

    def test_an_unknown_field_inside_a_negation_is_still_reported(self) -> None:
        assert only_error("NOT foo:1").start == 4

    def test_the_existing_process_alias_still_works(self) -> None:
        assert query_of("process:x") == term("process.name", "x")


class TestFreeText:
    @staticmethod
    def contains(pattern: str, phrase_text: str) -> Query:
        return should(
            wildcard("tartarus.summary", pattern),
            phrase("tartarus.summary.text", phrase_text),
            wildcard("process.command_line", pattern),
            phrase("process.command_line.text", phrase_text),
            wildcard("file.path", pattern),
            phrase("file.path.text", phrase_text),
            wildcard("url.full", pattern),
            wildcard("api.arguments", pattern),
        )

    def test_a_word_is_found_anywhere_in_the_summary_command_line_paths_url_and_arguments(
        self,
    ) -> None:
        assert query_of("PowerShell") == self.contains("*powershell*", "PowerShell")

    def test_a_quoted_phrase_is_found_as_a_whole(self) -> None:
        assert query_of('"cmd.exe /c ver"') == self.contains("*cmd.exe /c ver*", "cmd.exe /c ver")

    def test_wildcards_in_a_word_are_kept_and_the_word_is_padded(self) -> None:
        assert query_of("*.dll") == self.contains("*.dll*", "*.dll")

    def test_backslashes_are_escaped_for_the_wildcard_clauses_only(self) -> None:
        assert query_of(r"Temp\\a.txt") == self.contains("*temp\\\\a.txt*", "Temp\\a.txt")

    def test_two_words_are_two_anded_searches(self) -> None:
        assert query_of("powershell -enc") == every(
            self.contains("*powershell*", "powershell"), self.contains("*-enc*", "-enc")
        )

    def test_a_negated_word(self) -> None:
        assert query_of("NOT powershell") == must_not(self.contains("*powershell*", "powershell"))

    def test_an_empty_quoted_phrase_is_an_error(self) -> None:
        error = only_error('""')
        assert (error.start, error.end, error.message) == (0, 2, "empty value")


class TestBooleanStructure:
    def test_and_is_a_flat_bool_filter(self) -> None:
        assert query_of("process.name:cmd.exe AND lane:network") == every(
            term("process.name", "cmd.exe"), term("tartarus.lane", "network")
        )

    def test_a_chain_of_ands_and_nested_ands_stay_flat(self) -> None:
        assert query_of("pid:1 AND (pid:2 AND pid:3) pid:4") == every(
            term("process.pid", 1),
            term("process.pid", 2),
            term("process.pid", 3),
            term("process.pid", 4),
        )

    def test_or_is_a_bool_should_with_one_required(self) -> None:
        assert query_of("pid:1 OR pid:2") == should(term("process.pid", 1), term("process.pid", 2))

    def test_nested_ors_are_merged(self) -> None:
        assert query_of("pid:1 OR (pid:2 OR pid:3)") == should(
            term("process.pid", 1), term("process.pid", 2), term("process.pid", 3)
        )

    def test_not_is_a_bool_must_not(self) -> None:
        assert query_of("NOT pid:1") == must_not(term("process.pid", 1))

    def test_negations_inside_an_and_are_folded_into_its_must_not(self) -> None:
        assert query_of("pid:1 NOT pid:2 NOT lane:file") == {
            "bool": {
                "filter": [term("process.pid", 1)],
                "must_not": [term("process.pid", 2), term("tartarus.lane", "file")],
            }
        }

    def test_an_and_of_only_negations_is_a_bool_with_only_must_not(self) -> None:
        assert query_of("NOT pid:1 NOT pid:2") == {
            "bool": {"must_not": [term("process.pid", 1), term("process.pid", 2)]}
        }

    def test_precedence_not_over_and_over_or(self) -> None:
        assert query_of("pid:1 OR pid:2 pid:3") == should(
            term("process.pid", 1), every(term("process.pid", 2), term("process.pid", 3))
        )
        assert query_of("(pid:1 OR pid:2) pid:3") == every(
            should(term("process.pid", 1), term("process.pid", 2)), term("process.pid", 3)
        )

    def test_a_negated_group(self) -> None:
        assert query_of("NOT (pid:1 OR pid:2)") == must_not(
            should(term("process.pid", 1), term("process.pid", 2))
        )

    def test_a_negation_inside_an_or_stays_a_clause_of_the_or(self) -> None:
        assert query_of("pid:1 OR NOT pid:2") == should(
            term("process.pid", 1), must_not(term("process.pid", 2))
        )

    def test_the_spec_example_with_a_group_and_a_negation(self) -> None:
        text = 'api:(NtWriteVirtualMemory OR NtCreateThreadEx) NOT process.name:"explorer.exe"'
        assert query_of(text) == {
            "bool": {
                "filter": [{"terms": {"api.name": ["ntwritevirtualmemory", "ntcreatethreadex"]}}],
                "must_not": [term("process.name", "explorer.exe")],
            }
        }

    def test_the_spec_example_with_a_range_and_a_wildcard(self) -> None:
        assert query_of("destination.port >= 1024 AND dns.question.name:*.onion") == every(
            {"range": {"destination.port": {"gte": 1024}}}, wildcard("dns.question.name", "*.onion")
        )


class TestErrorsAreValuesNotExceptions:
    def test_a_syntax_error_becomes_a_compile_error_with_its_span(self) -> None:
        error = only_error('a "x')
        assert (error.start, error.end, error.message) == (2, 4, "unterminated quoted string")

    def test_an_unbalanced_parenthesis(self) -> None:
        error = only_error("(pid:1 OR pid:2")
        assert (error.start, error.end) == (0, 1)
        assert error.message == "unbalanced parenthesis: '(' is never closed"

    @pytest.mark.parametrize("text", ["pid:1 AND", "NOT", "AND pid:1", "pid:", "pid:()"])
    def test_a_dangling_keyword_or_value_never_raises(self, text: str) -> None:
        assert errors_of(text)

    def test_a_range_on_a_keyword_field_is_an_error_over_the_whole_comparison(self) -> None:
        error = only_error("x AND process.name > cmd")
        assert (error.start, error.end) == (6, 24)
        assert (
            error.message
            == "'>' needs a number, date or ip field, and process.name is a text field"
        )

    def test_a_query_with_a_semantic_and_a_value_error_reports_both_in_order(self) -> None:
        errors = errors_of("pid:abc AND foo:1")
        assert [(e.start, e.end) for e in errors] == [(4, 7), (12, 15)]

    def test_arbitrary_garbage_never_raises(self) -> None:
        for text in [
            '"',
            ")(",
            ":::",
            "a:b:c:",
            "\\",
            '"\\"',
            "AND OR NOT",
            "(((",
            "pid:(",
            "\x00",
        ]:
            compile_query(text)


class TestLimits:
    def test_a_query_over_the_length_limit_is_refused_before_it_is_parsed(self) -> None:
        text = "a " * (MAX_QUERY_LENGTH // 2) + "b"
        error = only_error(text)
        assert (error.start, error.end) == (MAX_QUERY_LENGTH, len(text))
        assert error.message == (
            f"the query is {len(text)} characters long, the limit is {MAX_QUERY_LENGTH}"
        )

    def test_a_query_of_exactly_the_length_limit_is_accepted(self) -> None:
        assert compile_query("a" * MAX_QUERY_LENGTH).ok

    def test_nesting_up_to_the_depth_limit_is_accepted(self) -> None:
        assert compile_query("NOT " * MAX_DEPTH + "pid:1").ok

    def test_nesting_beyond_the_depth_limit_is_an_error_at_the_first_level_over(self) -> None:
        text = "NOT " * (MAX_DEPTH + 1) + "pid:1"
        error = only_error(text)
        assert (error.start, error.end) == (4 * MAX_DEPTH, len(text))
        assert error.message == f"the query nests AND, OR and NOT deeper than {MAX_DEPTH} levels"

    def test_a_deeply_parenthesised_query_with_a_shallow_tree_is_accepted(self) -> None:
        assert compile_query("(" * 300 + "pid:1" + ")" * 300).ok

    def test_the_terms_limit_counts_every_value_of_a_group_and_every_exists(self) -> None:
        within = " ".join(f"pid:{n}" for n in range(MAX_TERMS))
        assert compile_query(within).ok
        text = within + " pid:(1 OR 2)"
        error = only_error(text)
        assert error.message == f"the query has more than {MAX_TERMS} terms"
        assert text[error.start : error.end] == "1"

    def test_the_terms_limit_error_is_over_the_first_term_past_the_limit(self) -> None:
        text = " ".join(f"pid:{n}" for n in range(MAX_TERMS + 1))
        error = only_error(text)
        assert text[error.start : error.end] == str(MAX_TERMS)

    def test_the_wildcard_limit_counts_leading_wildcards_and_free_text_words(self) -> None:
        within = " ".join(f"process.name:*a{n}" for n in range(MAX_WILDCARD_TERMS))
        assert compile_query(within).ok
        text = within + " word"
        error = only_error(text)
        assert text[error.start : error.end] == "word"
        assert error.message == (
            f"the query has more than {MAX_WILDCARD_TERMS} wildcard terms "
            "(a free-text word counts as one)"
        )

    def test_plain_values_do_not_count_as_wildcards(self) -> None:
        assert compile_query(" ".join(f"process.name:a{n}" for n in range(60))).ok

    def test_a_limit_error_is_reported_without_compiling_the_rest(self) -> None:
        text = "unknown:1 " + " ".join(f"pid:{n}" for n in range(MAX_TERMS + 1))
        assert [e.message for e in errors_of(text)] == [
            f"the query has more than {MAX_TERMS} terms"
        ]


ADVERSARIAL = [
    "a" * MAX_QUERY_LENGTH,
    "\\" * MAX_QUERY_LENGTH,
    '"' * MAX_QUERY_LENGTH,
    "(" * MAX_QUERY_LENGTH,
    ")" * MAX_QUERY_LENGTH,
    "a:" * (MAX_QUERY_LENGTH // 2),
    "a:(" * (MAX_QUERY_LENGTH // 3),
    '\\"' * (MAX_QUERY_LENGTH // 2),
    "NOT " * (MAX_QUERY_LENGTH // 4 - 1) + "a",
    "a OR " * (MAX_QUERY_LENGTH // 5 - 1) + "a",
    "*" * MAX_QUERY_LENGTH,
    "a" * 1000 + " " * 1000,
    "pid > " * (MAX_QUERY_LENGTH // 6),
]


@pytest.mark.parametrize("text", ADVERSARIAL, ids=lambda text: f"{text[:6]!r}x{len(text)}")
def test_inputs_made_to_stress_the_lexer_finish_quickly_and_never_raise(text: str) -> None:
    started = time.perf_counter()
    compile_query(text)
    assert time.perf_counter() - started < 1.0
