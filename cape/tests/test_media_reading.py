import importlib.util
import os
import re
import textwrap
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
from fixtures.iso_images import disc_image
from test_media_support import ScriptedRunner, failed, ok

from guest_engine.media import reading
from guest_engine.media.commands import run_command
from guest_engine.media.errors import MESSAGES, Fault, MediaProblem
from guest_engine.media.reading import read_inside

FILES = {"Sources/Install.WIM": b"the install image", "boot/readme.txt": b"hello"}


def reader_module(directory: Path, body: str) -> Path:
    path = directory / "reader.py"
    path.write_text(textwrap.dedent(body))
    return path


@pytest.fixture
def lookup(tmp_path) -> Path:
    return reader_module(
        tmp_path,
        """
        def read(image):
            found = image.open("sources", "install.wim")
            return {"content": found.read().decode() if found else None}
        """,
    )


@pytest.fixture
def udf_image(tmp_path) -> Path:
    return disc_image(tmp_path / "disc.iso", FILES)


def fault_of(image: Path, reader: Path, **kwargs) -> Fault | str:
    with pytest.raises(MediaProblem) as problem:
        read_inside(run_command, image, reader, **kwargs)
    return problem.value.fault


class TestReadingThroughARealChild:
    @pytest.mark.parametrize("filesystem", ["udf", "joliet", "iso9660"])
    def test_a_file_is_found_by_any_case_of_its_path_in_each_filesystem(
        self, tmp_path, lookup, filesystem
    ):
        image = disc_image(tmp_path / "disc.iso", FILES, filesystem)

        assert read_inside(run_command, image, lookup) == {"content": "the install image"}

    def test_a_path_that_is_not_on_the_disc_is_none(self, tmp_path):
        image = disc_image(tmp_path / "disc.iso", {"other.txt": b"x"})
        reader = reader_module(
            tmp_path,
            """
            def read(image):
                return {"file": image.open("sources", "install.wim"), "dir": image.open("sources")}
            """,
        )

        assert read_inside(run_command, image, reader) == {"file": None, "dir": None}

    def test_exists_tells_files_from_directories_and_from_nothing(self, tmp_path, udf_image):
        reader = reader_module(
            tmp_path,
            """
            def read(image):
                return [
                    image.exists("Sources", "install.wim"),
                    image.exists("sources"),
                    image.exists("sources", "nothing"),
                    image.exists("sources", "install.wim", "deeper"),
                ]
            """,
        )

        assert read_inside(run_command, udf_image, reader) == [True, False, False, False]

    def test_a_file_in_a_subdirectory_can_be_measured_and_read(self, tmp_path, udf_image):
        reader = reader_module(
            tmp_path,
            """
            def read(image):
                found = image.open("boot", "README.TXT")
                size = found.seek(0, 2)
                found.seek(0)
                return {"size": size, "text": found.read().decode()}
            """,
        )

        assert read_inside(run_command, udf_image, reader) == {"size": 5, "text": "hello"}

    def test_a_file_that_is_not_a_disc_image_is_not_an_iso(self, tmp_path, lookup):
        garbage = tmp_path / "notes.iso"
        garbage.write_bytes(os.urandom(200_000))

        assert fault_of(garbage, lookup) is Fault.NOT_AN_ISO

    def test_a_disc_image_cut_short_is_not_an_iso(self, tmp_path, lookup, udf_image):
        cut = tmp_path / "cut.iso"
        cut.write_bytes(udf_image.read_bytes()[:40_000])

        assert fault_of(cut, lookup) is Fault.NOT_AN_ISO

    def test_an_empty_file_is_reported_as_empty(self, tmp_path, lookup):
        empty = tmp_path / "empty.iso"
        empty.touch()

        assert fault_of(empty, lookup) is Fault.EMPTY

    @pytest.mark.parametrize("make", [lambda p: p, lambda p: p / "missing"])
    def test_a_folder_or_a_missing_file_is_not_a_file(self, tmp_path, lookup, make):
        assert fault_of(make(tmp_path), lookup) is Fault.NOT_A_FILE

    def test_a_reader_that_raises_is_an_inspection_failure(self, tmp_path, udf_image):
        reader = reader_module(tmp_path, "def read(image):\n    raise ZeroDivisionError\n")

        assert fault_of(udf_image, reader) is Fault.INSPECTION_FAILED

    def test_a_reader_that_does_not_exist_is_an_inspection_failure(self, tmp_path, udf_image):
        assert fault_of(udf_image, tmp_path / "nothing.py") is Fault.INSPECTION_FAILED

    def test_a_reader_whose_answer_is_not_json_is_an_inspection_failure(self, tmp_path, udf_image):
        reader = reader_module(tmp_path, "def read(image):\n    return {1, 2}\n")

        assert fault_of(udf_image, reader) is Fault.INSPECTION_FAILED

    def test_a_reader_that_runs_too_long_is_stopped(self, tmp_path, udf_image):
        reader = reader_module(tmp_path, "import time\n\ndef read(image):\n    time.sleep(30)\n")

        assert fault_of(udf_image, reader, timeout_s=1) is Fault.TIMED_OUT

    def test_a_reader_that_wants_gigabytes_is_stopped_by_the_memory_limit(
        self, tmp_path, udf_image
    ):
        reader = reader_module(tmp_path, "def read(image):\n    return len(bytearray(4 << 30))\n")

        assert fault_of(udf_image, reader) is Fault.INSPECTION_FAILED

    def test_the_child_runs_with_the_limits_it_promises(self, tmp_path, udf_image):
        reader = reader_module(
            tmp_path,
            """
            import resource

            def read(image):
                return {
                    "address_space": resource.getrlimit(resource.RLIMIT_AS),
                    "cpu": resource.getrlimit(resource.RLIMIT_CPU),
                    "file_size": resource.getrlimit(resource.RLIMIT_FSIZE),
                    "core": resource.getrlimit(resource.RLIMIT_CORE),
                }
            """,
        )

        limits = read_inside(run_command, udf_image, reader)

        assert limits == {
            "address_space": [reading.ADDRESS_SPACE_LIMIT_BYTES] * 2,
            "cpu": [reading.CPU_LIMIT_S] * 2,
            "file_size": [0, 0],
            "core": [0, 0],
        }

    def test_the_child_cannot_import_the_engine(self, tmp_path, udf_image):
        reader = reader_module(tmp_path, "def read(image):\n    import guest_engine\n")

        assert fault_of(udf_image, reader) is Fault.INSPECTION_FAILED


class TestWhatTheParentDoes:
    @pytest.fixture
    def image(self, tmp_path) -> Path:
        path = tmp_path / "disc.iso"
        path.write_bytes(b"x" * 100)
        return path

    def read(self, runner, image, **kwargs):
        return read_inside(runner, image, Path("/reader.py"), **kwargs)

    def test_the_child_is_given_the_image_on_stdin_and_the_reader_as_its_argument(self, image):
        runner = ScriptedRunner(([], ok('{"result": {"a": 1}}')))

        assert self.read(runner, image) == {"a": 1}

        (command,) = runner.calls
        assert command[-6:] == [
            reading.sys.executable,
            "-I",
            str(reading.CHILD_PROGRAM),
            "/reader.py",
            str(reading.ADDRESS_SPACE_LIMIT_BYTES),
            str(reading.CPU_LIMIT_S),
        ]
        assert runner.stdin_names == [str(image)]

    def test_the_whole_run_is_bounded_by_the_timeout(self, image):
        runner = ScriptedRunner(([], ok('{"result": 1}')))

        self.read(runner, image, timeout_s=7)

        assert runner.timeouts == [7]

    def test_nothing_drops_privileges_when_the_service_is_not_root(self, image, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: 1000)
        runner = ScriptedRunner(([], ok('{"result": 1}')))

        self.read(runner, image)

        assert runner.calls[0][0] != "setpriv"

    def test_the_child_runs_as_nobody_when_the_service_is_root(self, image, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: 0)
        runner = ScriptedRunner(([], ok('{"result": 1}')))

        self.read(runner, image)

        command = runner.calls[0]
        assert command[:7] == [
            "setpriv",
            "--reuid",
            "nobody",
            "--regid",
            "nogroup",
            "--clear-groups",
            "--no-new-privs",
        ]
        assert command[7:9] == [reading.sys.executable, "-I"]

    def test_the_image_is_closed_again_after_the_child_ran(self, image):
        seen = []

        def runner(args, timeout=None, stdin=None):
            seen.append(stdin)
            return ok('{"result": 1}')

        self.read(runner, image)

        assert seen[0].closed

    @pytest.mark.parametrize(
        "answer",
        [
            ok("not json at all"),
            ok(""),
            ok("[1, 2]"),
            ok('{"neither": 1}'),
            ok('{"fault": "no_such_fault"}'),
            ok('{"fault": 7}'),
            ok('{"result": "' + "x" * 2_000_000 + '"}'),
            failed(1, "Traceback ..."),
            failed(-9),
            failed(3, stdout='{"result": 1}'),
        ],
    )
    def test_whatever_the_child_prints_when_it_goes_wrong_is_an_inspection_failure(
        self, image, answer
    ):
        with pytest.raises(MediaProblem) as problem:
            self.read(ScriptedRunner(([], answer)), image)

        assert problem.value.fault is Fault.INSPECTION_FAILED
        assert str(problem.value) == MESSAGES[Fault.INSPECTION_FAILED]

    def test_the_childs_stderr_is_kept_as_detail_for_the_log(self, image):
        with pytest.raises(MediaProblem) as problem:
            self.read(ScriptedRunner(([], failed(1, "Traceback: boom"))), image)

        assert problem.value.detail == "Traceback: boom"

    @pytest.mark.parametrize("fault", [Fault.NOT_AN_ISO, Fault.UNSUPPORTED_FILESYSTEM])
    def test_a_fault_the_child_names_becomes_that_fault(self, image, fault):
        runner = ScriptedRunner(([], ok(f'{{"fault": "{fault.value}"}}')))

        with pytest.raises(MediaProblem) as problem:
            self.read(runner, image)

        assert problem.value.fault is fault

    def test_a_child_that_cannot_import_its_library_is_a_missing_tool(self, image):
        runner = ScriptedRunner(([], ok('{"fault": "tool_missing"}')))

        with pytest.raises(MediaProblem) as problem:
            self.read(runner, image)

        assert problem.value.fault is Fault.TOOL_MISSING

    def test_a_timeout_the_runner_reports_reaches_the_caller_unchanged(self, image):
        runner = ScriptedRunner(([], MediaProblem(Fault.TIMED_OUT, detail="python3")))

        with pytest.raises(MediaProblem) as problem:
            self.read(runner, image)

        assert problem.value.fault is Fault.TIMED_OUT

    def test_the_faults_the_child_can_name_are_the_ones_the_parent_accepts(self):
        spec = importlib.util.spec_from_file_location("reader_child", reading.CHILD_PROGRAM)
        child = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(child)

        named_by_child = {child.NOT_AN_ISO, child.UNSUPPORTED_FILESYSTEM, child.TOOL_MISSING}

        assert named_by_child == {fault.value for fault in reading.CHILD_FAULTS}


def test_the_read_function_is_ready_to_hand_to_an_inspector(udf_image, lookup):
    read = partial(read_inside, run_command)

    assert read(udf_image, lookup) == {"content": "the install image"}


def test_nothing_in_the_engine_runs_a_mounting_command():
    engine = Path(reading.__file__).parents[1]
    sources = [path for path in engine.rglob("*.py") if "__pycache__" not in path.parts]

    mentioned = [
        path.name
        for path in sources
        if re.search(r"""["'](mount|umount|losetup|mknod|findmnt)["']""", path.read_text())
    ]

    assert mentioned == []


class TestNamesAsRealUdfWritesThem:
    """Microsoft's images store ASCII names as 16-bit characters; pycdlib gives the raw bytes."""

    def child(self):
        spec = importlib.util.spec_from_file_location("reader_child", reading.CHILD_PROGRAM)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    class Entry:
        def __init__(self, name: str, encoding: str, *, directory: bool = False) -> None:
            self.raw = name.encode(encoding)
            self.file_ident = type("Descriptor", (), {"encoding": encoding})()
            self.directory = directory

        def file_identifier(self) -> bytes:
            return self.raw

        def is_dir(self) -> bool:
            return self.directory

    class FakeUdf:
        def __init__(self, tree) -> None:
            self.tree = tree

        def has_udf(self):
            return True

        def has_joliet(self):
            return False

        def list_children(self, **paths):
            return self.tree[paths["udf_path"]]

        def open_file_from_iso(self, **paths):
            return SimpleNamespace(__enter__=lambda: paths)

    @pytest.mark.parametrize("encoding", ["utf-16-be", "latin-1"])
    def test_a_path_is_found_whichever_encoding_the_names_use(self, encoding):
        entry = self.Entry
        tree = {
            "/": [entry("sources", encoding, directory=True), entry("setup.exe", encoding)],
            "/sources": [entry("install.wim", encoding)],
        }
        image = self.child().IsoImage(self.FakeUdf(tree))

        assert image.open("Sources", "INSTALL.WIM") == {"udf_path": "/sources/install.wim"}
        assert image.exists("setup.exe")
        assert not image.exists("sources", "install.esd")
