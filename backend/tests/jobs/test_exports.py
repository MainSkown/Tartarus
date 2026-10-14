from pathlib import Path

import pytest

from app.jobs import exports


def test_an_analysis_has_a_directory_of_its_own_under_the_exports_root(tmp_path: Path) -> None:
    assert exports.analysis_exports_dir(tmp_path, 7) == tmp_path / "7"


def test_a_file_result_names_the_file_relative_to_the_exports_root(tmp_path: Path) -> None:
    produced = exports.analysis_exports_dir(tmp_path, 7) / "report.pdf"

    result = exports.file_result(tmp_path, produced, "tartarus-7.pdf", "application/pdf")

    assert result == {
        "file": "7/report.pdf",
        "filename": "tartarus-7.pdf",
        "media_type": "application/pdf",
    }


def test_a_file_result_outside_the_exports_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside"):
        exports.file_result(tmp_path / "exports", tmp_path / "other.pdf", "x.pdf", "text/plain")


def test_a_named_export_resolves_to_its_file(tmp_path: Path) -> None:
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "a.html").write_text("x")

    assert exports.resolve_export(tmp_path, "7/a.html") == (tmp_path / "7" / "a.html").resolve()


@pytest.mark.parametrize("name", ["../secret.txt", "7/../../secret.txt", "/etc/passwd", ""])
def test_a_name_that_leaves_the_exports_root_resolves_to_nothing(tmp_path: Path, name: str) -> None:
    root = tmp_path / "exports"
    (root / "7").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("x")

    assert exports.resolve_export(root, name) is None


def test_a_symlink_out_of_the_exports_root_resolves_to_nothing(tmp_path: Path) -> None:
    root = tmp_path / "exports"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("x")
    (root / "link.txt").symlink_to(tmp_path / "secret.txt")

    assert exports.resolve_export(root, "link.txt") is None


def test_a_missing_file_resolves_to_nothing(tmp_path: Path) -> None:
    assert exports.resolve_export(tmp_path, "7/gone.pdf") is None


def test_removing_an_analysis_exports_deletes_its_directory_only(tmp_path: Path) -> None:
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "a.pdf").write_text("x")
    (tmp_path / "8").mkdir()

    exports.remove_analysis_exports(tmp_path, 7)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["8"]


def test_removing_exports_that_never_existed_is_not_an_error(tmp_path: Path) -> None:
    exports.remove_analysis_exports(tmp_path / "no-such-root", 7)
