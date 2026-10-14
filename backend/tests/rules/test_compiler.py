import base64
import time
from typing import Any

import pytest
from sigma.rule import SigmaRule

from app.rules.compiler import RegexLimits, compile_sigma_rule
from app.rules.mapping import map_fields
from app.rules.predicate import Predicate
from app.rules.rule import RuleProblem, Validity
from tests.rules.support import rule_yaml, simple_detection

CATEGORY = "process_creation"


def predicate_for(detection: str, limits: RegexLimits | None = None) -> Predicate:
    rule = SigmaRule.from_yaml(rule_yaml(detection, category=CATEGORY))
    map_fields(rule, CATEGORY)
    return compile_sigma_rule(rule, limits or RegexLimits())


def selection(
    body: str, condition: str = "selection", limits: RegexLimits | None = None
) -> Predicate:
    return predicate_for(simple_detection(body, condition), limits)


def event(**fields: Any) -> dict[str, Any]:
    """`event(**{"process.executable": "x"})` as the nested document the app indexes."""
    document: dict[str, Any] = {}
    for dotted, value in fields.items():
        *parents, leaf = dotted.split(".")
        node = document
        for parent in parents:
            node = node.setdefault(parent, {})
        node[leaf] = value
    return document


def cmd(line: object) -> dict[str, Any]:
    return event(**{"process.command_line": line})


def problem_of(detection: str) -> RuleProblem:
    with pytest.raises(RuleProblem) as caught:
        predicate_for(detection)
    return caught.value


class TestStrings:
    def test_equality_matches_the_whole_value_only(self) -> None:
        check = selection("process.name: cmd.exe")

        assert check(event(**{"process.name": "cmd.exe"}))
        assert not check(event(**{"process.name": "xcmd.exe"}))
        assert not check(event(**{"process.name": "cmd.exe "}))

    def test_matching_ignores_case_in_both_directions(self) -> None:
        check = selection("process.name: CMD.exe")

        assert check(event(**{"process.name": "cmd.EXE"}))

    def test_windows_paths_match_case_insensitively_with_literal_backslashes(self) -> None:
        check = selection("process.executable|endswith: '\\System32\\cmd.exe'")

        assert check(event(**{"process.executable": "C:\\WINDOWS\\SYSTEM32\\CMD.EXE"}))
        assert not check(event(**{"process.executable": "C:\\Windows\\System32\\cmd.exe.bak"}))

    def test_a_slash_is_not_a_backslash(self) -> None:
        check = selection("process.executable|endswith: '\\System32\\cmd.exe'")

        assert not check(event(**{"process.executable": "C:/Windows/System32/cmd.exe"}))

    def test_a_trailing_backslash_in_the_rule_is_literal(self) -> None:
        check = selection("file.path|contains: '\\Temp\\'")

        assert check(event(**{"file.path": "C:\\Users\\a\\TEMP\\x.exe"}))
        assert not check(event(**{"file.path": "C:\\Users\\a\\Temporary\\x.exe"}))

    def test_contains(self) -> None:
        check = selection("process.command_line|contains: ' -enc'")

        assert check(cmd("powershell.exe -ENC AAAA"))
        assert not check(cmd("powershell.exe -e AAAA"))

    def test_startswith(self) -> None:
        check = selection("process.command_line|startswith: 'cmd /c'")

        assert check(cmd("CMD /C whoami"))
        assert not check(cmd("start cmd /c whoami"))

    def test_endswith(self) -> None:
        check = selection("file.path|endswith: '.ps1'")

        assert check(event(**{"file.path": "C:\\a\\B.PS1"}))
        assert not check(event(**{"file.path": "C:\\a\\b.ps1x"}))

    def test_a_list_of_values_is_an_or(self) -> None:
        check = selection("process.name:\n  - cmd.exe\n  - powershell.exe")

        assert check(event(**{"process.name": "powershell.exe"}))
        assert not check(event(**{"process.name": "calc.exe"}))

    def test_all_requires_every_value(self) -> None:
        check = selection("process.command_line|contains|all:\n  - '-nop'\n  - '-w hidden'")

        assert check(cmd("powershell -W HIDDEN -nop"))
        assert not check(cmd("powershell -nop"))

    def test_a_star_matches_any_run_of_characters(self) -> None:
        check = selection("file.path: 'C:\\Users\\\\*\\AppData\\\\*.exe'")

        assert check(event(**{"file.path": "c:\\users\\bob\\appdata\\x\\y.EXE"}))
        assert not check(event(**{"file.path": "C:\\Users\\bob\\Documents\\y.exe"}))

    def test_a_question_mark_matches_exactly_one_character(self) -> None:
        check = selection("process.name: 'cmd.ex?'")

        assert check(event(**{"process.name": "cmd.exe"}))
        assert not check(event(**{"process.name": "cmd.ex"}))
        assert not check(event(**{"process.name": "cmd.exee"}))

    def test_an_escaped_star_and_question_mark_are_literal(self) -> None:
        check = selection("process.command_line: 'a\\*b\\?c'")

        assert check(cmd("a*b?c"))
        assert not check(cmd("aXbYc"))

    def test_a_lone_star_matches_any_present_value_including_empty(self) -> None:
        check = selection("process.name: '*'")

        assert check(event(**{"process.name": ""}))
        assert not check(event())

    def test_the_empty_string_matches_only_the_empty_string(self) -> None:
        check = selection("process.command_line: ''")

        assert check(cmd(""))
        assert not check(cmd("x"))

    def test_a_pattern_of_several_stars_does_not_blow_up_on_a_long_miss(self) -> None:
        check = selection("process.command_line: '*a*a*a*a*a*a*a*a*a*b'")

        started = time.perf_counter()
        assert not check(cmd("a" * 20_000))
        assert time.perf_counter() - started < 0.5

    def test_a_non_string_event_value_is_compared_by_its_text(self) -> None:
        check = selection("process.name: '1234'")

        assert check(event(**{"process.name": 1234}))

    def test_cased_matches_exactly(self) -> None:
        check = selection("process.name|cased: 'cmd.exe'")

        assert check(event(**{"process.name": "cmd.exe"}))
        assert not check(event(**{"process.name": "CMD.EXE"}))

    def test_a_multivalued_field_matches_when_any_value_does(self) -> None:
        check = selection("registry.data.strings|contains: 'evil'")

        assert check(event(**{"registry.data.strings": ["fine", "an EVIL string"]}))
        assert not check(event(**{"registry.data.strings": ["fine", "also fine"]}))

    def test_a_path_through_a_list_of_objects_is_followed(self) -> None:
        check = selection("dns.answers.data: 1.2.3.4")

        assert check({"dns": {"answers": [{"data": "9.9.9.9"}, {"data": "1.2.3.4"}]}})

    @pytest.mark.parametrize(
        "document", [{}, {"process": None}, {"process": "text"}, {"process": []}]
    )
    def test_a_path_that_does_not_lead_to_a_value_is_just_missing(
        self, document: dict[str, Any]
    ) -> None:
        assert not selection("process.name: cmd.exe")(document)


class TestMissingNullAndExists:
    def test_a_missing_field_makes_the_leaf_false(self) -> None:
        assert not selection("process.name: cmd.exe")(event())

    def test_a_missing_field_under_not_is_true(self) -> None:
        detection = "selection:\n  process.name: cmd.exe\ncondition: not selection"

        assert predicate_for(detection)(event())

    def test_null_matches_a_missing_field_and_an_explicit_null(self) -> None:
        check = selection("process.command_line: null")

        assert check(event())
        assert check(cmd(None))

    def test_null_does_not_match_a_value_or_an_empty_string(self) -> None:
        check = selection("process.command_line: null")

        assert not check(cmd("x"))
        assert not check(cmd(""))

    def test_exists_true_needs_a_non_null_value(self) -> None:
        check = selection("process.command_line|exists: true")

        assert check(cmd("x"))
        assert check(cmd(""))
        assert not check(event())
        assert not check(cmd(None))

    def test_exists_false_is_the_opposite(self) -> None:
        check = selection("process.command_line|exists: false")

        assert check(event())
        assert check(cmd(None))
        assert not check(cmd("x"))


class TestNumbersAndComparisons:
    def test_a_number_matches_a_number_or_numeric_text(self) -> None:
        check = selection("destination.port: 445")

        assert check(event(**{"destination.port": 445}))
        assert check(event(**{"destination.port": "445"}))
        assert not check(event(**{"destination.port": 446}))
        assert not check(event(**{"destination.port": "44x"}))

    def test_a_boolean_is_not_a_number(self) -> None:
        assert not selection("destination.port: 1")(event(**{"destination.port": True}))

    def test_a_boolean_matches_a_boolean(self) -> None:
        check = selection("api.status: true")

        assert check(event(**{"api.status": True}))
        assert not check(event(**{"api.status": False}))
        assert check(event(**{"api.status": "true"}))

    @pytest.mark.parametrize(
        ("modifier", "matching", "failing"),
        [("gt", 4, 3), ("gte", 3, 2), ("lt", 2, 3), ("lte", 3, 4)],
    )
    def test_comparisons(self, modifier: str, matching: int, failing: int) -> None:
        check = selection(f"event.severity|{modifier}: 3")

        assert check(event(**{"event.severity": matching}))
        assert not check(event(**{"event.severity": failing}))

    def test_a_comparison_accepts_numeric_text_and_floats(self) -> None:
        check = selection("event.severity|gt: 2.5")

        assert check(event(**{"event.severity": "3"}))
        assert not check(event(**{"event.severity": 2.5}))

    def test_a_comparison_on_a_non_number_is_false_not_an_error(self) -> None:
        check = selection("event.severity|gt: 2")

        assert not check(event(**{"event.severity": "high"}))
        assert not check(event(**{"event.severity": True}))
        assert not check(event())

    def test_neq_is_the_negation_of_equality(self) -> None:
        check = selection("destination.port|neq: 80")

        assert check(event(**{"destination.port": 443}))
        assert not check(event(**{"destination.port": 80}))


class TestCidr:
    def test_an_address_inside_the_range_matches(self) -> None:
        check = selection("destination.ip|cidr: 10.0.0.0/8")

        assert check(event(**{"destination.ip": "10.20.30.40"}))
        assert not check(event(**{"destination.ip": "11.0.0.1"}))

    def test_an_ipv6_range(self) -> None:
        check = selection("destination.ip|cidr: 'fe80::/10'")

        assert check(event(**{"destination.ip": "fe80::1"}))
        assert not check(event(**{"destination.ip": "2001:db8::1"}))

    def test_an_address_of_the_other_family_does_not_match(self) -> None:
        assert not selection("destination.ip|cidr: 10.0.0.0/8")(event(**{"destination.ip": "::1"}))

    def test_a_value_that_is_not_an_address_does_not_match(self) -> None:
        check = selection("destination.ip|cidr: 10.0.0.0/8")

        assert not check(event(**{"destination.ip": "not-an-ip"}))
        assert not check(event())


class TestRegularExpressions:
    def test_a_regex_searches_anywhere_in_the_value(self) -> None:
        check = selection("process.command_line|re: 'ps[0-9]+\\.exe'")

        assert check(cmd("run ps12.exe now"))
        assert not check(cmd("run psx.exe now"))

    def test_a_regex_is_case_sensitive_unless_flagged(self) -> None:
        assert not selection("process.name|re: 'CMD'")(event(**{"process.name": "cmd.exe"}))
        assert selection("process.name|re|i: 'CMD'")(event(**{"process.name": "cmd.exe"}))

    def test_anchors_are_honoured(self) -> None:
        check = selection("process.name|re: '^cmd\\.exe$'")

        assert check(event(**{"process.name": "cmd.exe"}))
        assert not check(event(**{"process.name": "xcmd.exe"}))

    def test_the_dotall_flag_lets_a_dot_cross_a_newline(self) -> None:
        assert not selection("process.command_line|re: 'a.b'")(cmd("a\nb"))
        assert selection("process.command_line|re|s: 'a.b'")(cmd("a\nb"))

    def test_the_multiline_flag_anchors_each_line(self) -> None:
        assert not selection("process.command_line|re: '^b$'")(cmd("a\nb\nc"))
        assert selection("process.command_line|re|m: '^b$'")(cmd("a\nb\nc"))

    def test_an_escaped_star_stays_a_regex_escape(self) -> None:
        check = selection("process.command_line|re: 'a\\*b'")

        assert check(cmd("a*b"))
        assert not check(cmd("aab"))

    def test_a_catastrophic_pattern_finishes_at_once(self) -> None:
        check = selection("process.command_line|re: '(a+)+$'")

        started = time.perf_counter()
        assert not check(cmd("a" * 30_000 + "b"))
        assert time.perf_counter() - started < 0.5

    def test_the_input_is_cut_at_the_length_cap(self) -> None:
        limits = RegexLimits(max_input_length=100)
        check = selection("process.command_line|re: 'needle'", limits=limits)

        assert check(cmd("x" * 90 + "needle"))
        assert not check(cmd("x" * 100 + "needle"))

    def test_a_pattern_longer_than_the_limit_is_invalid(self) -> None:
        limits = RegexLimits(max_pattern_length=10)

        with pytest.raises(RuleProblem) as caught:
            selection("process.command_line|re: 'abcdefghijklmnop'", limits=limits)

        assert caught.value.validity is Validity.INVALID
        assert "pattern" in caught.value.reason

    def test_a_pattern_that_compiles_too_large_is_invalid(self) -> None:
        limits = RegexLimits(max_program_bytes=8000)

        with pytest.raises(RuleProblem) as caught:
            selection("process.command_line|re: 'a{1000}'", limits=limits)

        assert caught.value.validity is Validity.INVALID
        assert "too large" in caught.value.reason


class TestBase64AndWindash:
    def test_base64_matches_the_encoded_value(self) -> None:
        check = selection("process.command_line|base64: 'evil'")

        assert check(cmd(base64.b64encode(b"evil").decode()))
        assert not check(cmd(base64.b64encode(b"good").decode()))

    @pytest.mark.parametrize("prefix", [b"", b"A", b"AA"])
    def test_base64offset_finds_the_value_at_any_alignment(self, prefix: bytes) -> None:
        check = selection("process.command_line|base64offset|contains: 'evilcmd'")
        payload = base64.b64encode(prefix + b"evilcmd" + b"tail").decode()

        assert check(cmd(f"powershell -e {payload}"))

    def test_base64offset_does_not_match_unrelated_text(self) -> None:
        check = selection("process.command_line|base64offset|contains: 'evilcmd'")

        assert not check(cmd("powershell -e " + base64.b64encode(b"harmless text").decode()))

    @pytest.mark.parametrize("dash", ["-", "/", "\u2013", "\u2014", "\u2015"])
    def test_windash_accepts_every_windows_dash(self, dash: str) -> None:
        check = selection("process.command_line|windash|contains: ' -enc'")

        assert check(cmd(f"powershell {dash}enc AAAA"))

    def test_windash_does_not_accept_other_characters(self) -> None:
        check = selection("process.command_line|windash|contains: ' -enc'")

        assert not check(cmd("powershell +enc AAAA"))
        assert not check(cmd("powershell enc AAAA"))


class TestConditions:
    DETECTION = """\
a:
  process.name: a.exe
b:
  process.name: b.exe
c:
  process.command_line|contains: flag
"""

    def predicate(self, condition: str) -> Predicate:
        return predicate_for(f"{self.DETECTION}condition: {condition}")

    def test_and_or_and_not(self) -> None:
        check = self.predicate("a and not (b or c)")

        assert check(event(**{"process.name": "a.exe"}))
        assert not check(event(**{"process.name": "a.exe", "process.command_line": "flag"}))

    def test_one_of_them(self) -> None:
        check = self.predicate("1 of them")

        assert check(event(**{"process.name": "b.exe"}))
        assert not check(event(**{"process.name": "z.exe"}))

    def test_all_of_a_name_pattern(self) -> None:
        detection = """\
part_start:
  process.name|startswith: a
part_end:
  process.name|endswith: .exe
unrelated:
  process.name: nothing
condition: all of part_*
"""
        check = predicate_for(detection)

        assert check(event(**{"process.name": "a.exe"}))
        assert not check(event(**{"process.name": "a.com"}))

    def test_one_of_a_name_pattern(self) -> None:
        detection = """\
selection_a:
  process.name: a.exe
selection_b:
  process.name: b.exe
other:
  process.name: c.exe
condition: 1 of selection_*
"""
        check = predicate_for(detection)

        assert check(event(**{"process.name": "b.exe"}))
        assert not check(event(**{"process.name": "c.exe"}))

    def test_several_fields_in_one_selection_must_all_match(self) -> None:
        check = selection("process.name: a.exe\nprocess.command_line|contains: x")

        assert check(event(**{"process.name": "a.exe", "process.command_line": "x"}))
        assert not check(event(**{"process.name": "a.exe"}))

    def test_a_list_of_maps_is_an_or_of_ands(self) -> None:
        body = "- process.name: a.exe\n  process.command_line: x\n- process.name: b.exe"
        check = selection(body)

        assert check(event(**{"process.name": "b.exe"}))
        assert check(event(**{"process.name": "a.exe", "process.command_line": "x"}))
        assert not check(event(**{"process.name": "a.exe"}))


class TestUnsupportedConstructs:
    def test_fieldref_is_unsupported(self) -> None:
        problem = problem_of(simple_detection("process.name|fieldref: process.command_line"))

        assert problem.validity is Validity.UNSUPPORTED
        assert "fieldref" in problem.reason

    def test_a_keyword_search_without_a_field_is_unsupported(self) -> None:
        problem = problem_of("keywords:\n  - evil\ncondition: keywords")

        assert problem.validity is Validity.UNSUPPORTED
        assert "keyword" in problem.reason

    def test_a_placeholder_is_unsupported(self) -> None:
        problem = problem_of(simple_detection("process.name|expand: '%name%'"))

        assert problem.validity is Validity.UNSUPPORTED
        assert "placeholder" in problem.reason

    def test_a_timestamp_part_is_unsupported(self) -> None:
        problem = problem_of(simple_detection("process.start|hour: 3"))

        assert problem.validity is Validity.UNSUPPORTED
        assert "timestamp" in problem.reason
