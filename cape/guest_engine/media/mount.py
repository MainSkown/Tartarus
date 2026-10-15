import logging
import os
import stat
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from guest_engine.media.commands import CommandResult, Runner
from guest_engine.media.errors import Fault, MediaProblem

SCAN_ROOT = Path("/run/scan")
LOOP_MAJOR = 7
LOOP_PREFIX = "/dev/loop"

log = logging.getLogger(__name__)

# Finding the next free index and attaching are two commands; two scans interleaving them
# would be handed the same free index, and the second would attach to a device with no node.
_attach_lock = threading.Lock()


def is_block_device(path: str) -> bool:
    try:
        return stat.S_ISBLK(os.stat(path).st_mode)
    except OSError:
        return False


def _fault_of_mount_failure(result: CommandResult) -> Fault:
    if "unknown filesystem type" in result.stderr:
        return Fault.UNSUPPORTED_FILESYSTEM
    return Fault.NOT_AN_ISO


def _is_busy(result: CommandResult) -> bool:
    return "target is busy" in result.stderr


class LoopMounter:
    """Read-only loop mounts of disc images, as proved in S0a."""

    def __init__(
        self,
        runner: Runner,
        scan_root: Path = SCAN_ROOT,
        device_exists: Callable[[str], bool] = is_block_device,
    ) -> None:
        self._run = runner
        self._scan_root = scan_root
        self._device_exists = device_exists

    @contextmanager
    def mounted(self, image: Path) -> Iterator[Path]:
        self._require_readable_file(image)
        with ExitStack() as release:
            mountpoint = self._make_mountpoint()
            release.callback(remove_directory, mountpoint)
            device = self._attach(image)
            release.callback(self._detach, device)
            self._mount(device, mountpoint)
            release.callback(self._unmount, mountpoint)
            yield mountpoint

    def _require_readable_file(self, image: Path) -> None:
        if not image.is_file():
            raise MediaProblem(Fault.NOT_A_FILE)
        if image.stat().st_size == 0:
            raise MediaProblem(Fault.EMPTY)

    def _make_mountpoint(self) -> Path:
        self._scan_root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(dir=self._scan_root))

    def _attach(self, image: Path) -> str:
        with _attach_lock:
            free = self._run(["losetup", "-f"])
            if free.returncode != 0:
                raise MediaProblem(Fault.ATTACH_FAILED, detail=free.stderr)
            self._ensure_node(free.stdout.strip())
            attached = self._run(["losetup", "--find", "--show", "--read-only", str(image)])
        if attached.returncode != 0:
            raise MediaProblem(Fault.ATTACH_FAILED, detail=attached.stderr)
        return attached.stdout.strip()

    def _ensure_node(self, device: str) -> None:
        # The container starts with only /dev/loop-control, so the node for the next free
        # index has to be created here; a fixed loop0..7 is not enough on a host that uses loop.
        if self._device_exists(device):
            return
        index = device.removeprefix(LOOP_PREFIX)
        created = self._run(["mknod", device, "b", str(LOOP_MAJOR), index])
        if created.returncode != 0 and not self._device_exists(device):
            raise MediaProblem(Fault.ATTACH_FAILED, detail=created.stderr)

    def _mount(self, device: str, mountpoint: Path) -> None:
        # No -t: the filesystem is UDF for Microsoft's images and iso9660 for plain ones.
        mounted = self._run(["mount", "-o", "ro", device, str(mountpoint)])
        if mounted.returncode != 0:
            raise MediaProblem(_fault_of_mount_failure(mounted), detail=mounted.stderr)

    def _unmount(self, mountpoint: Path) -> None:
        unmount_with_fallback(self._run, mountpoint)

    def _detach(self, device: str) -> None:
        detached = self._run(["losetup", "-d", device])
        if detached.returncode != 0:
            log.warning("could not detach %s: %s", device, detached.stderr.strip())


def unmount_with_fallback(runner: Runner, mountpoint: Path) -> None:
    result = runner(["umount", str(mountpoint)])
    if result.returncode == 0:
        return
    if _is_busy(result):
        result = runner(["umount", "-l", str(mountpoint)])
    if result.returncode != 0:
        log.warning("could not unmount %s: %s", mountpoint, result.stderr.strip())


def remove_directory(directory: Path) -> None:
    try:
        directory.rmdir()
    except OSError as error:
        log.warning("could not remove %s: %s", directory, error)


def cleanup_stale_mounts(runner: Runner, scan_root: Path = SCAN_ROOT) -> list[str]:
    """Undo what a killed control service left behind; call it once, at start.

    Returns the mount point directories that were cleaned.
    """
    if not scan_root.is_dir():
        return []
    for target, source in reversed(_mounts_under(runner, scan_root)):
        unmount_with_fallback(runner, Path(target))
        if source.startswith(LOOP_PREFIX):
            runner(["losetup", "-d", source])
    leftovers = sorted(scan_root.iterdir())
    for directory in leftovers:
        remove_directory(directory)
    return [str(directory) for directory in leftovers]


def _mounts_under(runner: Runner, scan_root: Path) -> list[tuple[str, str]]:
    listing = runner(["findmnt", "-rno", "TARGET,SOURCE"])
    if listing.returncode != 0:
        return []
    prefix = f"{scan_root}/"
    mounts = []
    for line in listing.stdout.splitlines():
        target, _, source = line.partition(" ")
        if target.startswith(prefix):
            mounts.append((target, source))
    return sorted(mounts)
