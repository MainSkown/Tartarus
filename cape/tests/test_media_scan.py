import os
from pathlib import Path

import pytest
from test_media_support import ScriptedRunner, failed, ok

from guest_engine.media.errors import MESSAGES, Fault, MediaProblem
from guest_engine.media.scan import scan_media

DEVICE = "/dev/tartarus-test-loop3"
SCAN_KEYS = {
    "file",
    "size",
    "mtime",
    "profile",
    "kind",
    "variants",
    "version",
    "build",
    "language",
    "arch",
    "sha256",
}
ERROR_KEYS = {"file", "size", "mtime", "profile", "error"}


class LinuxLikeInspector:
    """Not mounted: recognises by the file's own first bytes."""

    needs_mount = False

    def inspect(self, path, context):
        if path.read_bytes()[:5] != b"LINUX":
            return None
        return {
            "kind": "installer",
            "variants": [{"index": 1, "name": "Server", "edition_id": "server"}],
            "version": "24.04",
            "build": None,
            "language": None,
            "arch": "x64",
        }


class MountedInspector:
    """Mounted: recognises by file name, and reads the mounted tree."""

    needs_mount = True

    def inspect(self, path, context):
        if not path.name.startswith("win"):
            return None
        if path.name.startswith("win-broken"):
            raise MediaProblem("the install image is damaged")
        with context.mounted(path) as root:
            assert root.is_dir()
            return {
                "kind": "installer",
                "variants": [{"index": 5, "name": "Pro", "edition_id": "Professional"}],
                "version": "10.0.26200",
                "build": 26200,
                "language": "pl-PL",
                "arch": "amd64",
            }


class UndeclaredMountInspector:
    def inspect(self, path, context):
        with context.mounted(path):
            return


class CrashingInspector:
    needs_mount = False

    def inspect(self, path, context):
        raise ZeroDivisionError


INSPECTORS = {"linux": LinuxLikeInspector(), "windows": MountedInspector()}


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "iso"
    directory.mkdir()
    return directory


@pytest.fixture
def runner():
    return ScriptedRunner((["losetup", "-f"], ok(DEVICE)), (["losetup", "--find"], ok(DEVICE)))


@pytest.fixture
def scan(media_dir, runner, tmp_path):
    def run(inspectors=None):
        return scan_media(media_dir, inspectors or INSPECTORS, runner, scan_root=tmp_path / "scan")

    return run


def by_file(entries):
    return {entry["file"]: entry for entry in entries}


def test_a_medium_recognised_by_a_mounting_inspector_has_the_documented_shape(
    media_dir, scan, runner
):
    image = media_dir / "win11.iso"
    image.write_bytes(b"x" * 100)
    os.utime(image, (1791852244, 1791852244))

    (entry,) = scan()

    assert set(entry) == SCAN_KEYS
    assert entry == {
        "file": "win11.iso",
        "size": 100,
        "mtime": 1791852244,
        "profile": "windows",
        "kind": "installer",
        "variants": [{"index": 5, "name": "Pro", "edition_id": "Professional"}],
        "version": "10.0.26200",
        "build": 26200,
        "language": "pl-PL",
        "arch": "amd64",
        "sha256": None,
    }
    assert runner.commands_named("mount")


def test_a_medium_recognised_without_a_mount_never_touches_a_loop_device(media_dir, scan, runner):
    (media_dir / "ubuntu.iso").write_bytes(b"LINUX server")

    (entry,) = scan()

    assert entry["profile"] == "linux"
    assert entry["language"] is None
    assert runner.calls == []


def test_an_unrecognised_file_is_reported_with_a_clean_message_and_no_profile(media_dir, scan):
    (media_dir / "notes.txt").write_bytes(b"hello")

    (entry,) = scan()

    assert set(entry) == ERROR_KEYS
    assert entry["profile"] is None
    assert entry["error"] == MESSAGES[Fault.UNRECOGNISED]


def test_a_broken_file_does_not_fail_the_scan(media_dir, scan):
    (media_dir / "win-broken.iso").write_bytes(b"x")
    (media_dir / "win11.iso").write_bytes(b"x")

    entries = by_file(scan())

    assert entries["win-broken.iso"]["profile"] is None
    assert entries["win-broken.iso"]["error"] == "the install image is damaged"
    assert entries["win11.iso"]["profile"] == "windows"


def test_a_failed_mount_message_reaches_the_entry(media_dir, tmp_path):
    (media_dir / "win-garbage.iso").write_bytes(b"x")
    runner = ScriptedRunner(
        (["losetup", "-f"], ok(DEVICE)),
        (["losetup", "--find"], ok(DEVICE)),
        (["mount"], failed(32, "can't read superblock")),
    )

    (entry,) = scan_media(media_dir, INSPECTORS, runner, scan_root=tmp_path / "scan")

    assert entry["error"] == MESSAGES[Fault.NOT_AN_ISO]
    assert runner.calls[-1][:2] == ["losetup", "-d"]


def test_an_inspector_that_crashes_is_reported_not_raised(media_dir, scan):
    (media_dir / "anything.bin").write_bytes(b"x")

    (entry,) = scan({"crashing": CrashingInspector()})

    assert entry["error"] == MESSAGES[Fault.INSPECTION_FAILED]


def test_an_inspector_that_did_not_declare_needs_mount_cannot_mount(media_dir, scan, runner):
    (media_dir / "anything.bin").write_bytes(b"x")

    (entry,) = scan({"sneaky": UndeclaredMountInspector()})

    assert entry["error"] == MESSAGES[Fault.INSPECTION_FAILED]
    assert runner.calls == []


def test_recognition_wins_over_another_inspectors_problem(media_dir, scan):
    (media_dir / "win-broken.iso").write_bytes(b"LINUX but also called win-broken")

    (entry,) = scan()

    assert entry["profile"] == "linux"


def test_every_profile_that_recognises_a_file_gets_an_entry(media_dir, scan):
    (media_dir / "win-and-linux.iso").write_bytes(b"LINUX")

    entries = scan()

    assert sorted(entry["profile"] for entry in entries) == ["linux", "windows"]


def test_files_are_listed_in_name_order(media_dir, scan):
    for name in ("c.iso", "a.iso", "b.iso"):
        (media_dir / name).write_bytes(b"LINUX")

    assert [entry["file"] for entry in scan()] == ["a.iso", "b.iso", "c.iso"]


def test_dotfiles_directories_and_special_files_are_ignored(media_dir, scan):
    (media_dir / ".hidden.iso").write_bytes(b"LINUX")
    (media_dir / "folder.iso").mkdir()
    (media_dir / "folder.iso" / "inside.iso").write_bytes(b"LINUX")
    os.mkfifo(media_dir / "pipe.iso")
    (media_dir / "real.iso").write_bytes(b"LINUX")

    assert [entry["file"] for entry in scan()] == ["real.iso"]


def test_a_symlink_to_a_file_inside_the_directory_is_followed(media_dir, scan):
    (media_dir / "real.iso").write_bytes(b"LINUX")
    (media_dir / "alias.iso").symlink_to("real.iso")

    entries = by_file(scan())

    assert set(entries) == {"real.iso", "alias.iso"}
    assert entries["alias.iso"]["profile"] == "linux"


def test_a_symlink_leaving_the_directory_is_ignored(media_dir, scan, tmp_path):
    outside = tmp_path / "secret.iso"
    outside.write_bytes(b"LINUX")
    (media_dir / "escape.iso").symlink_to(outside)
    (media_dir / "up.iso").symlink_to("../secret.iso")

    assert scan() == []


def test_a_dangling_symlink_is_ignored(media_dir, scan):
    (media_dir / "dangling.iso").symlink_to("nowhere.iso")

    assert scan() == []


def test_an_empty_directory_and_a_missing_one_give_an_empty_list(media_dir, scan, runner, tmp_path):
    assert scan() == []
    assert scan_media(tmp_path / "missing", INSPECTORS, runner) == []
    assert runner.calls == []


def test_nothing_stays_mounted_after_a_scan(media_dir, scan, runner, tmp_path):
    (media_dir / "win11.iso").write_bytes(b"x")
    (media_dir / "win-broken.iso").write_bytes(b"x")

    scan()

    assert len(runner.commands_named("mount")) == len(runner.commands_named("umount")) == 1
    assert len(runner.commands_named("losetup")) == 3
    assert list((tmp_path / "scan").iterdir()) == []
