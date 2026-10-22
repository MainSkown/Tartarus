from pathlib import Path

import pytest

from app.ingest.json_file import JsonFileTooLargeError, load_json_file


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "data.json"
    path.write_text(text)
    return path


def test_valid_json_is_parsed(tmp_path: Path) -> None:
    assert load_json_file(write(tmp_path, '{"a": [1, 2.5, null]}'), 1000) == {"a": [1, 2.5, None]}


@pytest.mark.parametrize("text", ["Infinity", "-Infinity", "NaN", '{"a": [NaN]}'])
def test_constants_outside_the_json_grammar_are_refused(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        load_json_file(write(tmp_path, text), 1000)


def test_nesting_past_the_recursion_limit_is_a_value_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nested too deeply"):
        load_json_file(write(tmp_path, "[" * 200_000), 10**9)


def test_a_file_over_the_limit_is_refused_before_it_is_read(tmp_path: Path) -> None:
    with pytest.raises(JsonFileTooLargeError):
        load_json_file(write(tmp_path, '{"a": "xxxxxxxx"}'), 5)


def test_a_missing_file_stays_a_file_not_found_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_json_file(tmp_path / "nope.json", 5)
