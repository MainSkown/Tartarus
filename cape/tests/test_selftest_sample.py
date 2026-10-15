"""The cache of the self-test's benign sample: built by the profile's own command, rebuilt only when
the source or the command changed, never half-written."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from fixtures.profile_samples import sample_profile

from guest_engine.errors import Conflict
from guest_engine.media import CommandResult, Fault, MediaProblem
from guest_engine.selftest import SampleBuilder, SampleBuildFailed

SOURCE = "selftest/benign.c"


class FakeCompiler:
    """Stands in for the profile's compiler: writes the file `-o` names, or fails as scripted."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.timeouts: list[float | None] = []
        self.result = CommandResult(0, "", "")
        self.writes_output = True
        self.raises: MediaProblem | None = None

    def __call__(self, args, timeout=None) -> CommandResult:
        self.calls.append(list(args))
        self.timeouts.append(timeout)
        if self.raises:
            raise self.raises
        if self.writes_output and self.result.returncode == 0:
            output = Path(args[args.index("-o") + 1])
            output.write_bytes(b"MZ" + hashlib.sha256(str(args).encode()).digest())
        return self.result

    @property
    def output_paths(self) -> list[Path]:
        return [Path(call[call.index("-o") + 1]) for call in self.calls]


@pytest.fixture
def profile(tmp_path):
    directory = tmp_path / "profiles" / "windows"
    (directory / "selftest").mkdir(parents=True)
    (directory / SOURCE).write_text("int main(void) { return 0; }\n")
    return replace(sample_profile("windows"), directory=directory)


@pytest.fixture
def compiler():
    return FakeCompiler()


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "cache" / "selftest"


@pytest.fixture
def builder(cache, compiler):
    return SampleBuilder(cache, compiler)


def with_build(profile, build):
    sample = replace(profile.selftest.sample, build=build)
    return replace(profile, selftest=replace(profile.selftest, sample=sample))


def test_the_sample_is_built_by_the_profiles_own_command_with_its_source_and_output_filled_in(
    builder, compiler, profile, cache
):
    built = builder.sample(profile, profile.directory)

    [call] = compiler.calls
    assert call[:2] == ["x86_64-w64-mingw32-gcc", "-O1"]
    assert str(profile.directory / SOURCE) in call
    assert built.filename == "benign.exe"
    assert built.path == cache / "windows" / "benign.exe"
    assert built.path.read_bytes().startswith(b"MZ")


def test_the_command_is_an_argument_list_in_the_order_the_profile_wrote_it(
    builder, compiler, profile
):
    builder.sample(profile, profile.directory)

    [call] = compiler.calls
    output = compiler.output_paths[0]
    assert call == [
        "x86_64-w64-mingw32-gcc",
        "-O1",
        str(profile.directory / SOURCE),
        "-o",
        str(output),
    ]


def test_the_build_runs_in_a_fresh_directory_under_the_cache_that_is_gone_afterwards(
    builder, compiler, profile, cache
):
    builder.sample(profile, profile.directory)

    scratch = compiler.output_paths[0].parent
    assert scratch.parent == cache / "windows"
    assert not scratch.exists()


def test_an_unchanged_sample_is_not_built_again(builder, compiler, profile):
    first = builder.sample(profile, profile.directory)
    second = builder.sample(profile, profile.directory)

    assert len(compiler.calls) == 1
    assert second == first


def test_a_second_builder_over_the_same_cache_finds_the_sample_too(cache, compiler, profile):
    SampleBuilder(cache, compiler).sample(profile, profile.directory)

    SampleBuilder(cache, compiler).sample(profile, profile.directory)

    assert len(compiler.calls) == 1


def test_a_changed_source_is_built_again(builder, compiler, profile):
    builder.sample(profile, profile.directory)
    (profile.directory / SOURCE).write_text("int main(void) { return 1; }\n")

    builder.sample(profile, profile.directory)

    assert len(compiler.calls) == 2


def test_a_changed_command_is_built_again(builder, compiler, profile):
    builder.sample(profile, profile.directory)

    builder.sample(
        with_build(profile, ["x86_64-w64-mingw32-gcc", "-O2", "{source}", "-o", "{output}"]),
        profile.directory,
    )

    assert len(compiler.calls) == 2


def test_a_sample_whose_key_could_not_be_written_is_not_taken_for_the_older_one(
    builder, compiler, profile, monkeypatch
):
    original_source = (profile.directory / SOURCE).read_text()
    builder.sample(profile, profile.directory)
    (profile.directory / SOURCE).write_text("int main(void) { return 3; }\n")
    real_write_text = Path.write_text

    def failing_for_keys(self, *arguments, **options):
        if self.name.endswith(".key"):
            raise OSError("disk full")
        return real_write_text(self, *arguments, **options)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "write_text", failing_for_keys)
        with pytest.raises(OSError, match="disk full"):
            builder.sample(profile, profile.directory)
    (profile.directory / SOURCE).write_text(original_source)

    builder.sample(profile, profile.directory)

    assert len(compiler.calls) == 3


def test_a_cached_file_that_was_deleted_is_built_again(builder, compiler, profile):
    built = builder.sample(profile, profile.directory)
    built.path.unlink()

    assert builder.sample(profile, profile.directory).path.exists()
    assert len(compiler.calls) == 2


def test_a_failed_build_names_the_last_lines_of_the_compilers_output(builder, compiler, profile):
    compiler.result = CommandResult(1, "", "\n".join(f"error line {n}" for n in range(30)))

    with pytest.raises(SampleBuildFailed) as raised:
        builder.sample(profile, profile.directory)

    message = str(raised.value)
    assert "exit code 1" in message
    assert "error line 29" in message
    assert "error line 5" not in message


def test_the_compilers_standard_output_counts_as_its_output_too(builder, compiler, profile):
    compiler.result = CommandResult(2, "note from stdout", "")

    with pytest.raises(SampleBuildFailed, match="note from stdout"):
        builder.sample(profile, profile.directory)


def test_a_failed_build_leaves_nothing_behind_and_is_tried_again(builder, compiler, profile, cache):
    compiler.result = CommandResult(1, "", "boom")
    with pytest.raises(SampleBuildFailed):
        builder.sample(profile, profile.directory)
    assert list((cache / "windows").iterdir()) == []

    compiler.result = CommandResult(0, "", "")
    assert builder.sample(profile, profile.directory).path.is_file()


def test_a_rebuild_that_fails_does_not_serve_the_older_sample(builder, compiler, profile):
    builder.sample(profile, profile.directory)
    (profile.directory / SOURCE).write_text("int main(void) { return 2; }\n")
    compiler.result = CommandResult(1, "", "boom")

    with pytest.raises(SampleBuildFailed):
        builder.sample(profile, profile.directory)


def test_a_compiler_that_succeeds_without_writing_the_file_is_a_failed_build(
    builder, compiler, profile
):
    compiler.writes_output = False

    with pytest.raises(SampleBuildFailed, match="produced no file"):
        builder.sample(profile, profile.directory)


@pytest.mark.parametrize(
    ("fault", "words"),
    [(Fault.TOOL_MISSING, "not installed"), (Fault.TIMED_OUT, "too long")],
)
def test_a_compiler_that_cannot_run_is_a_failed_build_that_says_why(
    builder, compiler, profile, fault, words
):
    compiler.raises = MediaProblem(fault, detail="x86_64-w64-mingw32-gcc")

    with pytest.raises(SampleBuildFailed, match=words) as raised:
        builder.sample(profile, profile.directory)

    assert "x86_64-w64-mingw32-gcc" in str(raised.value)


def test_a_profile_without_a_sample_is_refused_as_a_conflict(builder, profile):
    bare = replace(profile, selftest=replace(profile.selftest, sample=None))

    with pytest.raises(Conflict, match="no self-test sample"):
        builder.sample(bare, profile.directory)


def test_the_build_is_given_a_generous_time_limit(builder, compiler, profile):
    builder.sample(profile, profile.directory)

    assert compiler.timeouts[0] is not None
    assert compiler.timeouts[0] >= 60


def test_a_source_that_has_gone_missing_is_a_failed_build_not_a_crash(builder, profile):
    (profile.directory / SOURCE).unlink()

    with pytest.raises(SampleBuildFailed, match="cannot read the sample source"):
        builder.sample(profile, profile.directory)
