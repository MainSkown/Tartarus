import importlib.util
from functools import partial
from pathlib import Path

import pytest
from fixtures.iso_images import (
    HEADER_FLAG_COMPRESSION,
    RESOURCE_FLAG_COMPRESSED,
    RESOURCE_FLAG_METADATA,
    WINDOWS_HOME,
    WINDOWS_PRO,
    disc_image,
    wim_file,
    windows_image_xml,
    windows_media,
)
from test_media_support import ScriptedRunner, ok

from guest_engine.media.commands import run_command
from guest_engine.media.errors import Fault, MediaProblem
from guest_engine.media.inspector import MediaContext
from guest_engine.media.reading import read_inside

INSPECTOR_PATH = Path(__file__).parents[2] / "guest" / "profiles" / "windows" / "inspector.py"


def load_inspector():
    spec = importlib.util.spec_from_file_location("windows_inspector", INSPECTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inspector = load_inspector()

TWO_EDITIONS = windows_image_xml(WINDOWS_PRO, WINDOWS_HOME)


def real_context(runner=run_command) -> MediaContext:
    return MediaContext(runner, partial(read_inside, runner))


def inspect_image(image: Path, context: MediaContext | None = None):
    return inspector.inspect(image, context or real_context())


def context_answering(answer) -> MediaContext:
    """A context whose child already answered `answer`, to test what the inspector makes of it."""
    return MediaContext(ScriptedRunner(), lambda _image, _reader: answer)


def problem_of(image: Path, context: MediaContext | None = None) -> MediaProblem:
    with pytest.raises(MediaProblem) as problem:
        inspect_image(image, context)
    return problem.value


class TestInspectReadingARealImage:
    def test_two_editions_give_the_documented_result(self, tmp_path):
        image = windows_media(tmp_path / "win11.iso", wim_file(TWO_EDITIONS))

        assert inspect_image(image) == {
            "kind": "installer",
            "variants": [
                {
                    "index": 1,
                    "name": "Windows 11 Pro",
                    "edition_id": "Professional",
                    "arch": "amd64",
                    "languages": ["pl-PL"],
                    "default_language": "pl-PL",
                    "build": 26200,
                    "installation_type": "Client",
                },
                {
                    "index": 2,
                    "name": "Windows 11 Home",
                    "edition_id": "Core",
                    "arch": "amd64",
                    "languages": ["pl-PL"],
                    "default_language": "pl-PL",
                    "build": 26200,
                    "installation_type": "Client",
                },
            ],
            "version": "10.0.26200",
            "build": 26200,
            "language": "pl-PL",
            "arch": "amd64",
            "compression": "LZX",
        }

    def test_another_build_language_and_architecture_are_read_just_as_well(self, tmp_path):
        older = {
            **WINDOWS_PRO,
            "build": 19041,
            "arch": 0,
            "languages": ["en-GB"],
            "default_language": "en-GB",
        }
        image = windows_media(tmp_path / "win10.iso", wim_file(windows_image_xml(older)))

        found = inspect_image(image)

        assert (found["version"], found["build"], found["language"], found["arch"]) == (
            "10.0.19041",
            19041,
            "en-GB",
            "x86",
        )

    def test_install_esd_is_read_when_there_is_no_wim(self, tmp_path):
        esd = wim_file(TWO_EDITIONS, header_flags=HEADER_FLAG_COMPRESSION | 0x80000)
        image = windows_media(tmp_path / "esd.iso", esd, name="install.esd")

        found = inspect_image(image)

        assert found["compression"] == "LZMS"
        assert len(found["variants"]) == 2

    def test_install_wim_is_preferred_over_install_esd(self, tmp_path):
        image = disc_image(
            tmp_path / "both.iso",
            {
                "sources/install.wim": wim_file(windows_image_xml(WINDOWS_PRO)),
                "sources/install.esd": wim_file(TWO_EDITIONS),
            },
        )

        assert len(inspect_image(image)["variants"]) == 1

    @pytest.mark.parametrize("filesystem", ["udf", "joliet", "iso9660"])
    def test_media_is_recognised_by_content_in_every_filesystem(self, tmp_path, filesystem):
        image = windows_media(
            tmp_path / "whatever.bin", wim_file(TWO_EDITIONS), filesystem=filesystem
        )

        assert inspect_image(image)["build"] == 26200

    def test_an_image_that_is_not_windows_media_is_not_claimed(self, tmp_path):
        image = disc_image(
            tmp_path / "linux.iso", {"boot/grub/grub.cfg": b"x", "casper/vmlinuz": b"x"}
        )

        assert inspect_image(image) is None

    def test_windows_media_without_an_install_image_is_a_problem(self, tmp_path):
        image = disc_image(tmp_path / "pe.iso", {"sources/boot.wim": b"x", "setup.exe": b"x"})

        assert str(problem_of(image)) == inspector.NO_INSTALL_IMAGE
        assert "install.wim or install.esd" in inspector.NO_INSTALL_IMAGE

    def test_a_wim_without_windows_metadata_is_a_problem(self, tmp_path):
        xml = '<WIM><IMAGE INDEX="1"><NAME>backup</NAME></IMAGE></WIM>'
        image = windows_media(tmp_path / "backup.iso", wim_file(xml))

        assert "no Windows version information" in str(problem_of(image))

    def test_a_file_that_is_not_an_iso_is_not_an_iso(self, tmp_path):
        garbage = tmp_path / "notes.iso"
        garbage.write_bytes(b"hello" * 50_000)

        assert problem_of(garbage).fault is Fault.NOT_AN_ISO

    def test_an_empty_file_is_empty(self, tmp_path):
        empty = tmp_path / "empty.iso"
        empty.touch()

        assert problem_of(empty).fault is Fault.EMPTY

    @pytest.mark.parametrize(
        ("wim", "failure"),
        [
            (b"PK\x03\x04" + b"\0" * 400, "not_a_wim"),
            (wim_file(TWO_EDITIONS)[:100], "incomplete"),
            (wim_file(TWO_EDITIONS, xml_offset=10**12), "incomplete"),
            (wim_file(TWO_EDITIONS, stored_size=10**9, original_size=10**9), "damaged"),
            (
                wim_file(
                    TWO_EDITIONS, resource_flags=RESOURCE_FLAG_METADATA | RESOURCE_FLAG_COMPRESSED
                ),
                "unreadable",
            ),
            (wim_file('<!DOCTYPE WIM [<!ENTITY a "b">]><WIM/>'), "damaged"),
        ],
    )
    def test_a_wim_that_cannot_be_read_gets_the_message_of_its_failure(
        self, tmp_path, wim, failure
    ):
        image = windows_media(tmp_path / "broken.iso", wim)

        assert str(problem_of(image)) == inspector.IMAGE_FAILURES[failure].format(
            file="install.wim"
        )

    def test_the_message_names_the_esd_when_it_is_the_esd(self, tmp_path):
        image = windows_media(tmp_path / "esd.iso", wim_file(b""), name="install.esd")

        assert "install.esd" in str(problem_of(image))


class TestWhatTheInspectorMakesOfTheChildsAnswer:
    def test_it_declares_no_mount_because_it_asks_the_context_to_read_inside_the_image(self):
        assert not hasattr(inspector, "needs_mount")
        assert inspector.READER.name == "wim_reader.py"
        assert inspector.READER.is_file()

    def test_the_reader_that_runs_in_the_child_is_the_one_next_to_the_inspector(self, tmp_path):
        asked = []

        def read(image, reader):
            asked.append((image, reader))
            return {"file": None, "boot_wim": False}

        inspect_image(Path("disc.iso"), MediaContext(ScriptedRunner(), read))

        assert asked == [(Path("disc.iso"), inspector.READER)]

    def test_a_failure_the_table_does_not_know_still_gets_a_readable_message(self):
        answer = {"file": "install.esd", "failure": "something new"}

        assert str(problem_of(Path("d.iso"), context_answering(answer))) == (
            "install.esd could not be read."
        )

    def test_the_table_has_the_failures_the_reader_can_name(self):
        assert set(inspector.IMAGE_FAILURES) == {"not_a_wim", "incomplete", "damaged", "unreadable"}

    def test_a_timeout_the_runner_reports_reaches_the_scan(self, tmp_path):
        image = windows_media(tmp_path / "win.iso", wim_file(TWO_EDITIONS))
        runner = ScriptedRunner(([], MediaProblem(Fault.TIMED_OUT)))

        assert problem_of(image, real_context(runner)).fault is Fault.TIMED_OUT

    def test_a_child_that_prints_garbage_is_an_inspection_failure(self, tmp_path):
        image = windows_media(tmp_path / "win.iso", wim_file(TWO_EDITIONS))
        runner = ScriptedRunner(([], ok("\x00garbage")))

        assert problem_of(image, real_context(runner)).fault is Fault.INSPECTION_FAILED
