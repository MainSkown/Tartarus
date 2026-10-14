import pytest

from app.query.ast import And, Comparison, Exists, FreeText, Node, Not, Or
from app.query.errors import QuerySyntaxError
from app.query.parser import parse


def show(node: Node) -> str:
    """The tree as one line, with values quoted by repr so unescaping is visible."""
    match node:
        case Or(terms) | And(terms):
            return f"{type(node).__name__}({', '.join(show(t) for t in terms)})"
        case Not(term):
            return f"Not({show(term)})"
        case Comparison(field, op, values):
            return f"{field.name} {op} {[v.text for v in values]!r}"
        case Exists(field):
            return f"{field.name}:*"
        case FreeText(value):
            return f"text {value.text!r}"
    raise AssertionError(node)


def shown(text: str) -> str:
    return show(parse(text))


def syntax_error(text: str) -> QuerySyntaxError:
    with pytest.raises(QuerySyntaxError) as raised:
        parse(text)
    return raised.value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "process.name:cmd.exe AND lane:network",
            "And(process.name : ['cmd.exe'], lane : ['network'])",
        ),
        (
            'api:(NtWriteVirtualMemory OR NtCreateThreadEx) NOT process.name:"explorer.exe"',
            "And(api : ['NtWriteVirtualMemory', 'NtCreateThreadEx'], "
            "Not(process.name : ['explorer.exe']))",
        ),
        (
            r"file.path:*\\AppData\\Roaming\\*.exe",
            r"file.path : ['*\\AppData\\Roaming\\*.exe']",
        ),
        (
            "destination.port >= 1024 AND dns.question.name:*.onion",
            "And(destination.port >= ['1024'], dns.question.name : ['*.onion'])",
        ),
        (
            "rule.ruleset:sigma AND event.severity >= 3",
            "And(rule.ruleset : ['sigma'], event.severity >= ['3'])",
        ),
        ("powershell -enc", "And(text 'powershell', text '-enc')"),
    ],
)
def test_every_example_of_the_spec_parses(text: str, expected: str) -> None:
    assert shown(text) == expected


def test_a_double_backslash_in_the_spec_example_is_one_backslash_in_the_value() -> None:
    node = parse(r"file.path:*\\AppData\\Roaming\\*.exe")
    assert isinstance(node, Comparison)
    assert node.values[0].text == "*\\AppData\\Roaming\\*.exe"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a OR b c", "Or(text 'a', And(text 'b', text 'c'))"),
        ("a b OR c", "Or(And(text 'a', text 'b'), text 'c')"),
        ("a AND b OR c AND d", "Or(And(text 'a', text 'b'), And(text 'c', text 'd'))"),
        ("NOT a b", "And(Not(text 'a'), text 'b')"),
        ("NOT a OR b", "Or(Not(text 'a'), text 'b')"),
        ("NOT NOT a", "Not(Not(text 'a'))"),
        ("(a OR b) c", "And(Or(text 'a', text 'b'), text 'c')"),
        ("a AND b c AND d", "And(text 'a', text 'b', text 'c', text 'd')"),
        ("a OR b OR c", "Or(text 'a', text 'b', text 'c')"),
    ],
)
def test_not_binds_tighter_than_and_which_binds_tighter_than_or(text: str, expected: str) -> None:
    assert shown(text) == expected


def test_adjacent_terms_are_anded_like_an_explicit_and() -> None:
    assert shown("pid:4 lane:file") == shown("pid:4 AND lane:file")


@pytest.mark.parametrize("keyword", ["and", "And", "aNd"])
def test_and_is_case_insensitive(keyword: str) -> None:
    assert shown(f"a {keyword} b") == "And(text 'a', text 'b')"


@pytest.mark.parametrize("keyword", ["or", "Or", "oR"])
def test_or_is_case_insensitive(keyword: str) -> None:
    assert shown(f"a {keyword} b") == "Or(text 'a', text 'b')"


@pytest.mark.parametrize("keyword", ["not", "Not", "nOT"])
def test_not_is_case_insensitive(keyword: str) -> None:
    assert shown(f"{keyword} a") == "Not(text 'a')"


@pytest.mark.parametrize(
    "word", ["android", "oracle", "notepad.exe", "ANDROID", "ornate", "nothing"]
)
def test_a_word_that_merely_starts_with_a_keyword_is_a_word(word: str) -> None:
    assert shown(f"a {word}") == f"And(text 'a', text {word!r})"


def test_a_keyword_directly_before_a_parenthesis_or_quote_is_still_a_keyword() -> None:
    assert shown("NOT(a)") == "Not(text 'a')"
    assert shown('NOT"a b"') == "Not(text 'a b')"
    assert shown("(a)OR(b)") == "Or(text 'a', text 'b')"


def test_a_field_named_like_a_keyword_prefix_is_a_field_not_a_keyword() -> None:
    assert shown("not:1") == "not : ['1']"


def test_a_keyword_in_value_position_is_a_value() -> None:
    assert shown("process.name:and") == "process.name : ['and']"
    assert shown("process.name:NOT") == "process.name : ['NOT']"
    assert shown("process.name:or") == "process.name : ['or']"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("api:(a OR b)", "api : ['a', 'b']"),
        ("api:(a or b or c)", "api : ['a', 'b', 'c']"),
        ("api:(a)", "api : ['a']"),
        ('api:("a b" OR c*)', "api : ['a b', 'c*']"),
        ("api:( a OR b )", "api : ['a', 'b']"),
    ],
)
def test_a_value_group_lists_the_alternatives_of_one_field(text: str, expected: str) -> None:
    assert shown(text) == expected


@pytest.mark.parametrize("operator", [":", ">", ">=", "<", "<="])
def test_every_operator_is_recognised_with_or_without_spaces(operator: str) -> None:
    expected = f"event.severity {operator} ['2']"
    assert shown(f"event.severity{operator}2") == expected
    if operator != ":":
        assert shown(f"event.severity {operator} 2") == expected


def test_space_after_the_colon_is_allowed() -> None:
    assert shown("process.name: cmd.exe") == "process.name : ['cmd.exe']"


def test_field_star_is_an_exists_test() -> None:
    assert shown("process.name:*") == "process.name:*"
    assert shown("NOT api.name:*") == "Not(api.name:*)"


def test_a_quoted_star_is_a_wildcard_value_not_an_exists_test() -> None:
    assert shown('process.name:"*"') == "process.name : ['*']"


def test_a_star_inside_a_group_is_an_ordinary_wildcard_value() -> None:
    assert shown("process.name:(* OR a)") == "process.name : ['*', 'a']"


@pytest.mark.parametrize(
    ("text", "value"),
    [
        (r'"a\\b"', "a\\b"),
        (r'"say \"hi\""', 'say "hi"'),
        (r'"C:\Windows\System32"', r"C:\Windows\System32"),
        (r'"\\\\server\\share"', r"\\server\share"),
        (r'"\\"', "\\"),
        ('""', ""),
        ('"has ( paren ) and OR"', "has ( paren ) and OR"),
        ('"unicode zażółć"', "unicode zażółć"),
    ],
)
def test_quoted_strings_unescape_backslash_pairs_and_quotes(text: str, value: str) -> None:
    node = parse(f"cmd:{text}")
    assert isinstance(node, Comparison)
    assert node.values[0].text == value


@pytest.mark.parametrize(
    ("text", "value"),
    [
        (r"C:\Windows\System32\cmd.exe", r"C:\Windows\System32\cmd.exe"),
        (r"C:\\Windows\\System32", r"C:\Windows\System32"),
        (r"*\\AppData\\Roaming\\*.exe", r"*\AppData\Roaming\*.exe"),
        (r"*\AppData\Roaming\*.exe", r"*\AppData\Roaming\*.exe"),
        (r"\\\\server\\share", r"\\server\share"),
        (r"HKLM\Software\*", r"HKLM\Software\*"),
        ("http://evil.com/a?b=c&d=e", "http://evil.com/a?b=c&d=e"),
        ("a-b_c.d/e", "a-b_c.d/e"),
        ("1.2.3.0/24", "1.2.3.0/24"),
        ("::1", "::1"),
        ("*.onion", "*.onion"),
        ("<tag>", "<tag>"),
    ],
)
def test_bare_values_take_paths_urls_and_wildcards_with_the_same_backslash_rule_as_quotes(
    text: str, value: str
) -> None:
    node = parse(f"cmd:{text}")
    assert isinstance(node, Comparison)
    assert node.values[0].text == value


def test_free_text_words_may_carry_dashes_slashes_dots_and_wildcards() -> None:
    assert shown("-enc /c cmd.exe *.dll a?b") == (
        "And(text '-enc', text '/c', text 'cmd.exe', text '*.dll', text 'a?b')"
    )


def test_a_free_text_word_with_a_colon_that_is_not_a_field_name_stays_a_word() -> None:
    assert shown("/srv/x:y") == "text '/srv/x:y'"


def test_a_quoted_phrase_is_one_free_text_term() -> None:
    assert shown('"cmd.exe /c ver"') == "text 'cmd.exe /c ver'"


def test_a_field_looking_word_before_a_colon_is_a_field_so_text_with_a_colon_needs_quotes() -> None:
    assert shown("http://evil.com") == "http : ['//evil.com']"
    assert shown('"http://evil.com"') == "text 'http://evil.com'"


def test_field_names_keep_their_case_and_aliases_are_not_resolved_by_the_parser() -> None:
    assert shown("PID:4 @timestamp>0 Process.Name:x") == (
        "And(PID : ['4'], @timestamp > ['0'], Process.Name : ['x'])"
    )


def test_a_negated_group_and_a_negated_comparison() -> None:
    assert shown("NOT (a OR b)") == "Not(Or(text 'a', text 'b'))"
    assert shown("NOT pid:4 AND lane:file") == "And(Not(pid : ['4']), lane : ['file'])"


def test_spans_are_character_offsets_in_the_query_text() -> None:
    text = "process.name:cmd.exe AND lane:network"
    node = parse(text)
    assert isinstance(node, And)
    first, second = node.terms
    assert node.span == (0, len(text))
    assert first.span == (0, 20)
    assert text[slice(*first.span)] == "process.name:cmd.exe"
    assert text[slice(*second.span)] == "lane:network"


def test_comparison_nodes_expose_the_field_and_value_spans() -> None:
    text = 'api:(NtWriteFile OR "x y") z'
    node = parse(text)
    assert isinstance(node, And)
    comparison, free = node.terms
    assert isinstance(comparison, Comparison)
    assert text[slice(*comparison.field.span)] == "api"
    assert [text[slice(*v.span)] for v in comparison.values] == ["NtWriteFile", '"x y"']
    assert text[slice(*comparison.span)] == 'api:(NtWriteFile OR "x y")'
    assert text[slice(*free.span)] == "z"


def test_a_comparison_with_spaces_around_the_operator_spans_field_to_value() -> None:
    text = "x AND destination.port  >=  1024"
    node = parse(text)
    assert isinstance(node, And)
    assert text[slice(*node.terms[1].span)] == "destination.port  >=  1024"


def test_not_spans_the_keyword_and_its_operand() -> None:
    text = 'a NOT process.name:"x y"'
    node = parse(text)
    assert isinstance(node, And)
    assert text[slice(*node.terms[1].span)] == 'NOT process.name:"x y"'


def test_a_parenthesised_group_keeps_the_span_of_its_content() -> None:
    text = "(a OR b) c"
    node = parse(text)
    assert isinstance(node, And)
    assert text[slice(*node.terms[0].span)] == "a OR b"


def test_exists_spans_field_to_star() -> None:
    text = "x NOT api.name:*"
    node = parse(text)
    assert isinstance(node, And)
    not_node = node.terms[1]
    assert isinstance(not_node, Not)
    assert text[slice(*not_node.term.span)] == "api.name:*"


def test_a_value_reports_whether_it_holds_a_wildcard() -> None:
    node = parse('cmd:(a OR b* OR "c?" OR "d")')
    assert isinstance(node, Comparison)
    assert [v.has_wildcard for v in node.values] == [False, True, True, False]


def test_a_very_nested_query_parses_without_hitting_the_recursion_limit() -> None:
    depth = 900
    node = parse("(" * depth + "a" + ")" * depth)
    assert show(node) == "text 'a'"
    assert show(parse("NOT " * 400 + "a")).count("Not(") == 400


@pytest.mark.parametrize(
    ("text", "start", "end", "message"),
    [
        ('a "unterminated', 2, 15, "unterminated quoted string"),
        ('api:"x', 4, 6, "unterminated quoted string"),
        ('a "x\\"', 2, 6, "unterminated quoted string"),
        ("a)", 1, 2, "unbalanced parenthesis: ')' has no matching '('"),
        ("(a OR b", 0, 1, "unbalanced parenthesis: '(' is never closed"),
        ("((a) b", 0, 1, "unbalanced parenthesis: '(' is never closed"),
        ("a AND", 2, 5, "AND needs a term after it"),
        ("a OR", 2, 4, "OR needs a term after it"),
        ("a NOT", 2, 5, "NOT needs a term after it"),
        ("NOT", 0, 3, "NOT needs a term after it"),
        ("AND a", 0, 3, "AND needs a term before it"),
        ("OR a", 0, 2, "OR needs a term before it"),
        ("a OR OR b", 5, 7, "OR needs a term before it"),
        ("a AND OR b", 6, 8, "OR needs a term before it"),
        ("(a OR)", 5, 6, "expected a term, found ')'"),
        ("()", 1, 2, "expected a term, found ')'"),
        ("process.name:", 0, 13, "expected a value after 'process.name:'"),
        ("pid >", 0, 5, "expected a value after 'pid >'"),
        ("pid >=", 0, 6, "expected a value after 'pid >='"),
        ("a pid:", 2, 6, "expected a value after 'pid:'"),
        ("api:()", 5, 6, "expected a value, found ')'"),
        ("api:(a OR)", 9, 10, "expected a value, found ')'"),
        ("api:(a b)", 7, 8, "expected OR or ')', found 'b'"),
        ("api:(a AND b)", 7, 10, "expected OR or ')', found 'AND'"),
        ("api:(or)", 5, 7, "expected a value, found 'or'"),
        ("api:(a OR b", 4, 5, "unbalanced parenthesis: '(' is never closed"),
        ("pid > 1 > 2", 8, 9, "'>' needs a field name before it"),
        ("<5", 0, 1, "'<' needs a field name before it"),
    ],
)
def test_a_syntax_error_has_the_span_and_message_of_what_is_wrong(
    text: str, start: int, end: int, message: str
) -> None:
    error = syntax_error(text).error
    assert (error.start, error.end, error.message) == (start, end, message)
    assert error.suggestion is None
