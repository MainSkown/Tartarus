import threading
import time
from pathlib import Path

import pytest
from test_media_support import ScriptedRunner, failed, ok

from guest_engine.media.errors import Fault, MediaProblem
from guest_engine.media.mount import LoopMounter, cleanup_stale_mounts

DEVICE = "/dev/loop9"


@pytest.fixture
def image(tmp_path: Path) -> Path:
    path = tmp_path / "disc.iso"
    path.write_bytes(b"x" * 4096)
    return path


@pytest.fixture
def scan_root(tmp_path: Path) -> Path:
    return tmp_path / "scan"


def attach_rules(*extra):
    return [
        (["losetup", "-f"], ok(DEVICE + "\n")),
        (["losetup", "--find"], ok(DEVICE + "\n")),
        *extra,
    ]


def mounter(runner, scan_root, device_exists=False) -> LoopMounter:
    return LoopMounter(runner, scan_root, device_exists=lambda _: device_exists)


def fault_of(problem: pytest.ExceptionInfo[MediaProblem]) -> Fault:
    return problem.value.fault


def test_command_sequence_matches_the_proven_flow(image, scan_root):
    runner = ScriptedRunner(*attach_rules())

    with mounter(runner, scan_root).mounted(image) as mountpoint:
        assert runner.calls[-1] == ["mount", "-o", "ro", DEVICE, str(mountpoint)]
        assert mountpoint.parent == scan_root

    assert runner.calls == [
        ["losetup", "-f"],
        ["mknod", DEVICE, "b", "7", "9"],
        ["losetup", "--find", "--show", "--read-only", str(image)],
        ["mount", "-o", "ro", DEVICE, str(mountpoint)],
        ["umount", str(mountpoint)],
        ["losetup", "-d", DEVICE],
    ]


def test_the_node_is_not_created_when_it_exists(image, scan_root):
    runner = ScriptedRunner(*attach_rules())

    with mounter(runner, scan_root, device_exists=True).mounted(image):
        pass

    assert runner.commands_named("mknod") == []


def test_mount_is_not_told_the_filesystem_type(image, scan_root):
    runner = ScriptedRunner(*attach_rules())

    with mounter(runner, scan_root).mounted(image):
        pass

    (mount_call,) = runner.commands_named("mount")
    assert "-t" not in mount_call


def test_the_mount_point_is_removed_and_each_mount_gets_its_own(image, scan_root):
    runner = ScriptedRunner(*attach_rules())
    loop_mounter = mounter(runner, scan_root)

    with loop_mounter.mounted(image) as first:
        assert first.is_dir()
    with loop_mounter.mounted(image) as second:
        pass

    assert first != second
    assert not first.exists()
    assert not second.exists()


def test_busy_unmount_falls_back_to_a_lazy_unmount(image, scan_root):
    runner = ScriptedRunner(
        *attach_rules(
            (["umount", "-l"], ok()),
            (["umount"], failed(32, "umount: /run/scan/x: target is busy.")),
        )
    )

    with mounter(runner, scan_root).mounted(image) as mountpoint:
        pass

    assert runner.calls[-3:] == [
        ["umount", str(mountpoint)],
        ["umount", "-l", str(mountpoint)],
        ["losetup", "-d", DEVICE],
    ]


def test_an_unmount_failing_for_another_reason_is_not_retried_lazily(image, scan_root):
    runner = ScriptedRunner(*attach_rules((["umount"], failed(32, "umount: not mounted"))))

    with mounter(runner, scan_root).mounted(image):
        pass

    assert ["umount", "-l"] not in [call[:2] for call in runner.calls]
    assert runner.calls[-1][:2] == ["losetup", "-d"]


def test_everything_is_released_when_the_body_raises(image, scan_root):
    runner = ScriptedRunner(*attach_rules())
    created = []

    def body_that_fails():
        with mounter(runner, scan_root).mounted(image) as mountpoint:
            created.append(mountpoint)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        body_that_fails()

    assert [call[0] for call in runner.calls[-2:]] == ["umount", "losetup"]
    assert not created[0].exists()


def test_a_cleanup_failure_does_not_replace_the_error_from_the_body(image, scan_root):
    runner = ScriptedRunner(
        *attach_rules((["umount"], failed(1, "oops")), (["losetup", "-d"], failed(1, "oops")))
    )

    with pytest.raises(RuntimeError, match="boom"), mounter(runner, scan_root).mounted(image):
        raise RuntimeError("boom")


def test_a_mount_that_fails_releases_the_loop_device_and_the_directory(image, scan_root):
    runner = ScriptedRunner(
        *attach_rules(
            (["mount"], failed(32, "mount: /dev/loop9: can't read superblock on /dev/loop9."))
        )
    )

    with pytest.raises(MediaProblem) as problem, mounter(runner, scan_root).mounted(image):
        pass

    assert fault_of(problem) is Fault.NOT_AN_ISO
    assert runner.commands_named("umount") == []
    assert runner.calls[-1] == ["losetup", "-d", DEVICE]
    assert list(scan_root.iterdir()) == []


@pytest.mark.parametrize(
    ("stderr", "fault"),
    [
        ("mount: /dev/loop9: can't read superblock on /dev/loop9.", Fault.NOT_AN_ISO),
        (
            "mount: /mp: wrong fs type, bad option, bad superblock on /dev/loop9, missing",
            Fault.NOT_AN_ISO,
        ),
        ("mount: /mp: unknown filesystem type 'udf'.", Fault.UNSUPPORTED_FILESYSTEM),
        ("mount: something nobody has seen", Fault.NOT_AN_ISO),
    ],
)
def test_mount_failures_are_classified(image, scan_root, stderr, fault):
    runner = ScriptedRunner(*attach_rules((["mount"], failed(32, stderr))))

    with pytest.raises(MediaProblem) as problem, mounter(runner, scan_root).mounted(image):
        pass

    assert fault_of(problem) is fault


def test_a_loop_device_that_cannot_be_attached_is_an_infrastructure_fault(image, scan_root):
    runner = ScriptedRunner(
        (["losetup", "-f"], ok(DEVICE)),
        (["losetup", "--find"], failed(1, "losetup: cannot find an unused loop device")),
    )

    with pytest.raises(MediaProblem) as problem, mounter(runner, scan_root).mounted(image):
        pass

    assert fault_of(problem) is Fault.ATTACH_FAILED
    assert runner.commands_named("mount") == []


def test_no_free_loop_device_is_an_infrastructure_fault(image, scan_root):
    runner = ScriptedRunner((["losetup", "-f"], failed(1, "losetup: cannot find an unused loop")))

    with pytest.raises(MediaProblem) as problem, mounter(runner, scan_root).mounted(image):
        pass

    assert fault_of(problem) is Fault.ATTACH_FAILED


def test_a_node_that_cannot_be_created_is_an_infrastructure_fault(image, scan_root):
    runner = ScriptedRunner(
        (["losetup", "-f"], ok(DEVICE)), (["mknod"], failed(1, "mknod: Operation not permitted"))
    )

    with pytest.raises(MediaProblem) as problem, mounter(runner, scan_root).mounted(image):
        pass

    assert fault_of(problem) is Fault.ATTACH_FAILED


@pytest.mark.parametrize("kind", ["missing", "directory", "dangling_symlink"])
def test_what_is_not_a_file_is_refused_before_any_command_runs(tmp_path, scan_root, kind):
    target = tmp_path / "x.iso"
    if kind == "directory":
        target.mkdir()
    elif kind == "dangling_symlink":
        target.symlink_to(tmp_path / "nowhere")
    runner = ScriptedRunner()

    with pytest.raises(MediaProblem) as problem, mounter(runner, scan_root).mounted(target):
        pass

    assert fault_of(problem) is Fault.NOT_A_FILE
    assert runner.calls == []


def test_an_empty_file_is_refused_before_any_command_runs(tmp_path, scan_root):
    empty = tmp_path / "empty.iso"
    empty.touch()
    runner = ScriptedRunner()

    with pytest.raises(MediaProblem) as problem, mounter(runner, scan_root).mounted(empty):
        pass

    assert fault_of(problem) is Fault.EMPTY
    assert runner.calls == []


def test_two_threads_never_interleave_finding_and_attaching_a_loop_device(image, scan_root):
    # Without the lock both threads would be handed the same free index and one of them
    # would then attach to a device whose node was never created.
    finding = 0
    overlaps = []
    guard = threading.Lock()

    def find_free(_):
        nonlocal finding
        with guard:
            finding += 1
            overlaps.append(finding)
        time.sleep(0.02)
        return ok(DEVICE)

    def attach(_):
        nonlocal finding
        with guard:
            finding -= 1
        return ok(DEVICE)

    runner = ScriptedRunner((["losetup", "-f"], find_free), (["losetup", "--find"], attach))
    loop_mounter = mounter(runner, scan_root)

    def scan():
        with loop_mounter.mounted(image):
            pass

    threads = [threading.Thread(target=scan) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max(overlaps) == 1


class TestCleanupStaleMounts:
    @pytest.fixture
    def leftovers(self, scan_root):
        scan_root.mkdir()
        first, second, empty = (scan_root / name for name in ("a1", "b2", "c3"))
        for directory in (first, second, empty):
            directory.mkdir()
        return first, second, empty

    def findmnt(self, scan_root, first, second):
        return "\n".join(
            [
                "/ /dev/nvme0n1p2",
                f"{first} /dev/loop4",
                "/run/other /dev/loop5",
                f"{second} /dev/loop6",
            ]
        )

    def test_unmounts_only_what_is_under_the_scan_root_and_detaches_its_devices(
        self, scan_root, leftovers
    ):
        first, second, _ = leftovers
        runner = ScriptedRunner((["findmnt"], ok(self.findmnt(scan_root, first, second))))

        cleaned = cleanup_stale_mounts(runner, scan_root)

        assert runner.commands_named("umount") == [["umount", str(second)], ["umount", str(first)]]
        assert runner.commands_named("losetup") == [
            ["losetup", "-d", "/dev/loop6"],
            ["losetup", "-d", "/dev/loop4"],
        ]
        assert sorted(cleaned) == sorted(str(path) for path in leftovers)

    def test_removes_the_mount_point_directories(self, scan_root, leftovers):
        runner = ScriptedRunner(
            (["findmnt"], ok(self.findmnt(scan_root, leftovers[0], leftovers[1])))
        )

        cleanup_stale_mounts(runner, scan_root)

        assert list(scan_root.iterdir()) == []

    def test_a_busy_leftover_is_unmounted_lazily(self, scan_root, leftovers):
        first = leftovers[0]
        runner = ScriptedRunner(
            (["findmnt"], ok(f"{first} /dev/loop4")),
            (["umount", "-l"], ok()),
            (["umount"], failed(32, "target is busy")),
        )

        cleanup_stale_mounts(runner, scan_root)

        assert ["umount", "-l", str(first)] in runner.calls

    def test_nothing_to_do_when_the_scan_root_does_not_exist(self, scan_root):
        runner = ScriptedRunner()

        assert cleanup_stale_mounts(runner, scan_root) == []
        assert runner.calls == []

    def test_a_failing_findmnt_cleans_directories_and_does_not_raise(self, scan_root, leftovers):
        runner = ScriptedRunner((["findmnt"], failed(1, "")))

        cleanup_stale_mounts(runner, scan_root)

        assert runner.commands_named("umount") == []
