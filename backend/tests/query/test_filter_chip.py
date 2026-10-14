from app.query.compiler import compile_filter_chip, compile_query
from app.query.errors import QueryError


def test_a_chip_is_the_query_field_colon_value() -> None:
    chip = compile_filter_chip("process.name", "cmd.exe")

    assert chip.errors == []
    assert chip.query == compile_query("process.name:cmd.exe").query


def test_a_chip_resolves_aliases_like_the_query_does() -> None:
    assert compile_filter_chip("PROC", "Cmd.EXE").query == compile_query("proc:Cmd.EXE").query


def test_a_composite_alias_reaches_all_its_members() -> None:
    assert (
        compile_filter_chip("domain", "a.example").query == compile_query("domain:a.example").query
    )


def test_a_chip_value_is_taken_whole_so_spaces_colons_and_quotes_need_no_escaping() -> None:
    value = 'C:\\Program Files\\a "b".exe'

    chip = compile_filter_chip("file.path", value)

    assert chip.errors == []
    assert chip.query == compile_query('file.path:"C:\\\\Program Files\\\\a \\"b\\".exe"').query


def test_an_unknown_field_is_an_error_with_a_suggestion_spanning_the_field() -> None:
    chip = compile_filter_chip("procss.name", "x")

    assert chip.query is None
    assert chip.errors == [
        QueryError(
            0, 11, "unknown field 'procss.name'; did you mean 'process.name'?", "process.name"
        )
    ]


def test_a_value_the_field_cannot_hold_is_an_error_spanning_the_value() -> None:
    chip = compile_filter_chip("process.pid", "abc")

    assert chip.query is None
    assert chip.errors == [QueryError(12, 15, "'abc' is not a whole number")]


def test_an_empty_value_is_an_error() -> None:
    assert compile_filter_chip("process.name", "").errors[0].message == "empty value"
