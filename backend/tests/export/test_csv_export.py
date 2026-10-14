import csv
import io
from datetime import UTC, datetime

import pytest

from app.export.csv_export import COLUMNS, render_csv
from app.schemas.views_events import ProcessRef
from app.schemas.views_findings import IocType
from tests.export.conftest import EVERY_TYPE, make_ioc


def parse(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text, newline="")))


def test_the_columns_are_the_documented_ones() -> None:
    assert COLUMNS == ("type", "value", "context", "first_seen", "source_process")


def test_an_empty_ioc_set_is_just_the_header(make_input) -> None:
    text = render_csv(make_input(iocs=()))

    assert text == "type,value,context,first_seen,source_process\r\n"


def test_every_ioc_is_a_row_in_the_models_order(make_input) -> None:
    rows = parse(render_csv(make_input()))

    assert [(row["type"], row["value"]) for row in rows] == [
        (ioc.type.value, ioc.value) for ioc in EVERY_TYPE
    ]


def test_the_source_process_is_name_and_pid_or_empty(make_input) -> None:
    rows = {row["value"]: row for row in parse(render_csv(make_input()))}

    assert rows["evil.example"]["source_process"] == "invoice.exe (4242)"
    assert rows["Global\\Tartarus-Mutex"]["source_process"] == ""


def test_a_process_without_a_name_is_called_unknown(make_input) -> None:
    ioc = make_ioc(IocType.DOMAIN, "a.example", process=ProcessRef(pid=17, name=None))

    assert parse(render_csv(make_input(iocs=(ioc,))))[0]["source_process"] == "unknown (17)"


def test_first_seen_is_the_time_of_the_first_event_in_utc(make_input) -> None:
    ioc = make_ioc(IocType.DOMAIN, "a.example").model_copy(
        update={"first_seen": datetime(2026, 10, 13, 12, 12, 41, 383000, tzinfo=UTC)}
    )

    assert parse(render_csv(make_input(iocs=(ioc,))))[0]["first_seen"] == "2026-10-13T12:12:41.383Z"


def test_first_seen_is_blank_for_an_ioc_that_has_no_event(make_input) -> None:
    ioc = make_ioc(IocType.HASH, "a" * 64)

    assert parse(render_csv(make_input(iocs=(ioc,))))[0]["first_seen"] == ""


def test_commas_quotes_and_newlines_in_the_context_survive(make_input) -> None:
    context = 'Said "hello", then\nleft,\r\nagain'
    ioc = make_ioc(IocType.DOMAIN, "a.example", context)

    rows = parse(render_csv(make_input(iocs=(ioc,))))

    assert rows[0]["context"] == context


def test_unicode_is_kept(make_input) -> None:
    ioc = make_ioc(IocType.DOMAIN, "пример.рф", "Zażółć gęślą jaźń 日本語 😀")

    rows = parse(render_csv(make_input(iocs=(ioc,))))

    assert (rows[0]["value"], rows[0]["context"]) == ("пример.рф", "Zażółć gęślą jaźń 日本語 😀")


@pytest.mark.parametrize("lead", ["=", "+", "-", "@", "\t", "\r"])
def test_a_cell_a_spreadsheet_would_run_as_a_formula_is_prefixed_with_a_quote(
    make_input, lead: str
) -> None:
    ioc = make_ioc(IocType.FILE, f"{lead}cmd|' /C calc'!A0", f"{lead}HYPERLINK(1)")

    row = parse(render_csv(make_input(iocs=(ioc,))))[0]

    assert row["value"] == f"'{lead}cmd|' /C calc'!A0"
    assert row["context"] == f"'{lead}HYPERLINK(1)"


def test_a_cell_that_only_contains_a_formula_character_is_left_alone(make_input) -> None:
    ioc = make_ioc(IocType.URL, "http://a.example/?q=1+2", "a-b @c")

    row = parse(render_csv(make_input(iocs=(ioc,))))[0]

    assert (row["value"], row["context"]) == ("http://a.example/?q=1+2", "a-b @c")


def test_a_duplicate_ioc_is_one_row(make_input) -> None:
    twice = (make_ioc(IocType.DOMAIN, "a.example"), make_ioc(IocType.DOMAIN, "a.example"))

    assert len(parse(render_csv(make_input(iocs=twice)))) == 1
