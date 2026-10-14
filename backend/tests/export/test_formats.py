import csv
import io
import json

import pytest

from app.export.formats import ExportFormat, export_filename, render
from app.schemas.views_findings import IocType
from tests.export.conftest import make_ioc
from tests.export.validation import misp_problems, parse_stix


def test_the_formats_are_stix_misp_and_csv() -> None:
    assert [format_.value for format_ in ExportFormat] == ["stix", "misp", "csv"]


@pytest.mark.parametrize(
    ("format_", "media_type", "filename"),
    [
        (ExportFormat.STIX, "application/stix+json;version=2.1", "tartarus-7-iocs.stix.json"),
        (ExportFormat.MISP, "application/json", "tartarus-7-iocs.misp.json"),
        (ExportFormat.CSV, "text/csv; charset=utf-8", "tartarus-7-iocs.csv"),
    ],
)
def test_each_format_has_its_media_type_and_file_name(
    format_: ExportFormat, media_type: str, filename: str
) -> None:
    assert format_.media_type == media_type
    assert export_filename(7, format_) == filename


def test_stix_renders_a_bundle_the_reference_parser_accepts(make_input) -> None:
    document = json.loads(render(ExportFormat.STIX, make_input()))

    parse_stix(document)


def test_misp_renders_an_event_that_passes_the_schema(make_input) -> None:
    document = json.loads(render(ExportFormat.MISP, make_input()))

    assert misp_problems(document) == []


def test_csv_renders_utf_8_that_parses_back(make_input) -> None:
    content = render(ExportFormat.CSV, make_input())

    rows = list(csv.reader(io.StringIO(content.decode("utf-8"), newline="")))
    assert rows[0] == ["type", "value", "context", "first_seen", "source_process"]
    assert len(rows) == 1 + 9


def test_json_keeps_unicode_readable(make_input) -> None:
    content = render(ExportFormat.MISP, make_input(iocs=(make_ioc(IocType.DOMAIN, "пример.рф"),)))

    assert "пример.рф".encode() in content


def test_every_format_renders_the_same_bytes_twice(make_input) -> None:
    for format_ in ExportFormat:
        assert render(format_, make_input()) == render(format_, make_input())
