import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_media_support import ScriptedRunner, failed, ok

from guest_engine.media.errors import MediaProblem
from guest_engine.media.inspector import MediaContext

INSPECTOR_PATH = Path(__file__).parents[2] / "guest" / "profiles" / "windows" / "inspector.py"
FIXTURES = Path(__file__).parent / "fixtures"


def load_inspector():
    spec = importlib.util.spec_from_file_location("windows_inspector", INSPECTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inspector = load_inspector()


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParseWiminfo:
    """The first fixture is the real output for Win11_25H2_Polish_x64_v2.iso (S0a); the
    multi-language and ESD ones are derived from it by changing only the fields their tests name."""

    @pytest.fixture
    def real(self):
        return inspector.parse_wiminfo(fixture_text("wiminfo_win11_25h2_pl_x64.txt"))

    def test_real_iso_has_ten_editions_with_their_index_numbers(self, real):
        assert real["image_count"] == 10
        assert [(image["index"], image["edition_id"]) for image in real["images"]] == [
            (1, "Core"),
            (2, "CoreN"),
            (3, "Education"),
            (4, "EducationN"),
            (5, "Professional"),
            (6, "ProfessionalN"),
            (7, "ProfessionalEducation"),
            (8, "ProfessionalEducationN"),
            (9, "ProfessionalWorkstation"),
            (10, "ProfessionalWorkstationN"),
        ]

    def test_real_iso_pro_is_index_five(self, real):
        pro = real["images"][4]

        assert pro["name"] == "Windows 11 Pro"
        assert pro["index"] == 5

    def test_real_iso_build_language_and_architecture(self, real):
        assert {image["build"] for image in real["images"]} == {26200}
        assert {image["version"] for image in real["images"]} == {"10.0.26200"}
        assert {tuple(image["languages"]) for image in real["images"]} == {("pl-PL",)}
        assert {image["default_language"] for image in real["images"]} == {"pl-PL"}
        assert {image["arch"] for image in real["images"]} == {"amd64"}
        assert real["compression"] == "LZX"

    def test_several_languages_and_other_architectures_are_accepted(self):
        parsed = inspector.parse_wiminfo(fixture_text("wiminfo_multilang_two_arch.txt"))

        first, second = parsed["images"]
        assert first["languages"] == ["en-US", "de-DE"]
        assert first["default_language"] == "en-US"
        assert first["build"] == 26100
        assert (first["arch"], second["arch"]) == ("amd64", "arm64")

    def test_a_solid_esd_reports_lzms_compression(self):
        parsed = inspector.parse_wiminfo(fixture_text("wiminfo_solid_esd_lzms.txt"))

        assert parsed["compression"] == "LZMS"
        assert [image["index"] for image in parsed["images"]] == [1, 2, 3]

    def test_an_image_without_windows_metadata_has_none_for_it(self):
        parsed = inspector.parse_wiminfo(fixture_text("wiminfo_non_windows.txt"))

        (image,) = parsed["images"]
        assert image["name"] == "backup"
        assert image["edition_id"] is None
        assert image["build"] is None
        assert image["arch"] is None
        assert image["languages"] == []

    def test_text_without_images_parses_to_no_images(self):
        assert inspector.parse_wiminfo("")["images"] == []

    def test_an_unknown_architecture_keeps_its_own_name_lowercased(self):
        text = fixture_text("wiminfo_win11_25h2_pl_x64.txt").replace("x86_64", "RISCV64")

        assert inspector.parse_wiminfo(text)["images"][0]["arch"] == "riscv64"


def tree(root: Path, *files: str) -> Path:
    for relative in files:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
    return root


def context_for(root: Path, runner) -> MediaContext:
    @contextmanager
    def mounted(_image):
        yield root

    return MediaContext(runner, mounted)


def run_inspect(root, runner, name="disc.iso"):
    return inspector.inspect(Path(name), context_for(root, runner))


class TestInspect:
    def test_it_declares_that_it_needs_a_mount(self):
        assert inspector.needs_mount is True

    def test_real_iso_result(self, tmp_path):
        root = tree(tmp_path, "sources/install.wim", "sources/boot.wim")
        runner = ScriptedRunner((["wiminfo"], ok(fixture_text("wiminfo_win11_25h2_pl_x64.txt"))))

        found = run_inspect(root, runner)

        assert runner.calls == [["wiminfo", str(root / "sources" / "install.wim")]]
        assert found["kind"] == "installer"
        assert found["build"] == 26200
        assert found["version"] == "10.0.26200"
        assert found["language"] == "pl-PL"
        assert found["arch"] == "amd64"
        assert found["compression"] == "LZX"
        assert len(found["variants"]) == 10
        assert found["variants"][4] == {
            "index": 5,
            "name": "Windows 11 Pro",
            "edition_id": "Professional",
            "arch": "amd64",
            "languages": ["pl-PL"],
            "default_language": "pl-PL",
            "build": 26200,
            "installation_type": "Client",
        }

    def test_it_falls_back_to_install_esd(self, tmp_path):
        root = tree(tmp_path, "sources/install.esd")
        runner = ScriptedRunner((["wiminfo"], ok(fixture_text("wiminfo_solid_esd_lzms.txt"))))

        found = run_inspect(root, runner)

        assert runner.calls == [["wiminfo", str(root / "sources" / "install.esd")]]
        assert found["compression"] == "LZMS"

    def test_install_wim_is_preferred_over_install_esd(self, tmp_path):
        root = tree(tmp_path, "sources/install.wim", "sources/install.esd")
        runner = ScriptedRunner((["wiminfo"], ok(fixture_text("wiminfo_win11_25h2_pl_x64.txt"))))

        run_inspect(root, runner)

        assert runner.calls[0][1].endswith("install.wim")

    def test_media_is_recognised_by_content_not_by_file_name(self, tmp_path):
        root = tree(tmp_path, "sources/install.wim")
        runner = ScriptedRunner((["wiminfo"], ok(fixture_text("wiminfo_win11_25h2_pl_x64.txt"))))

        assert run_inspect(root, runner, name="whatever.bin") is not None

    def test_an_image_that_is_not_windows_media_is_not_claimed(self, tmp_path):
        root = tree(tmp_path, "boot/grub/grub.cfg", "casper/vmlinuz")
        runner = ScriptedRunner()

        assert run_inspect(root, runner) is None
        assert runner.calls == []

    def test_windows_media_without_an_install_image_is_a_problem(self, tmp_path):
        root = tree(tmp_path, "sources/boot.wim", "setup.exe")

        with pytest.raises(MediaProblem, match=r"install\.wim or install\.esd"):
            run_inspect(root, ScriptedRunner())

    def test_a_wim_without_windows_metadata_is_a_problem(self, tmp_path):
        root = tree(tmp_path, "sources/install.wim")
        runner = ScriptedRunner((["wiminfo"], ok(fixture_text("wiminfo_non_windows.txt"))))

        with pytest.raises(MediaProblem, match="no Windows version information"):
            run_inspect(root, runner)

    @pytest.mark.parametrize(("exit_code", "message"), sorted(inspector.WIMINFO_FAILURES.items()))
    def test_every_row_of_the_wiminfo_error_table(self, tmp_path, exit_code, message):
        root = tree(tmp_path, "sources/install.wim")
        runner = ScriptedRunner((["wiminfo"], failed(exit_code, "raw stderr that is for the log")))

        with pytest.raises(MediaProblem) as problem:
            run_inspect(root, runner)

        assert str(problem.value) == message.format(file="install.wim")
        assert "raw stderr" not in str(problem.value)

    def test_the_table_has_the_three_codes_s0a_saw(self):
        assert set(inspector.WIMINFO_FAILURES) == {43, 50, 65}

    def test_an_unlisted_wiminfo_failure_still_gets_a_readable_message(self, tmp_path):
        root = tree(tmp_path, "sources/install.wim")
        runner = ScriptedRunner((["wiminfo"], failed(99, "who knows")))

        with pytest.raises(MediaProblem, match=r"install\.wim could not be read"):
            run_inspect(root, runner)

    def test_the_message_names_the_esd_when_it_is_the_esd(self, tmp_path):
        root = tree(tmp_path, "sources/install.esd")
        runner = ScriptedRunner((["wiminfo"], failed(43)))

        with pytest.raises(MediaProblem, match=r"install\.esd"):
            run_inspect(root, runner)
