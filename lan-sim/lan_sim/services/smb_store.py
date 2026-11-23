"""The shares' file store: a tree of nodes in memory, never the host file system.

A client chooses every name and every byte, so names are validated strictly (`normalize_path`), a
file keeps at most `FILE_CAP` bytes and a session at most `Budget.byte_cap`: anything beyond is
dropped by the caller after it is hashed. Nothing here imports `os` or `pathlib`.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from impacket import nt_errors

KIB = 1024
MIB = 1024 * KIB
FILE_CAP = 16 * MIB
SESSION_BYTE_CAP = 64 * MIB
SESSION_NODE_CAP = 4096
MAX_COMPONENT_CHARS = 255
MAX_DEPTH = 32
FIRST_PRINTABLE = 0x20
FORBIDDEN_IN_NAMES = frozenset(':*?<>"|/')

SUPERSEDE, OPEN, CREATE, OPEN_IF, OVERWRITE, OVERWRITE_IF = range(6)
_TRUNCATING = (SUPERSEDE, OVERWRITE, OVERWRITE_IF)

WINDOWS_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
FILETIME_TICKS_PER_SECOND = 10_000_000

README_TEXT = (
    b"This is a managed file share. Do not store personal files here.\r\n"
    b"Contact the service desk for access requests.\r\n"
)
_SEEDED_DIRECTORIES = {
    "C$": [
        ("Windows",),
        ("Windows", "System32"),
        ("Windows", "Temp"),
        ("Users",),
        ("Users", "Public"),
        ("Program Files",),
    ],
    "ADMIN$": [("System32",), ("Temp",)],
}


class StoreError(Exception):
    """A refusal that maps to an NT status the client is sent."""

    def __init__(self, status: int) -> None:
        super().__init__(f"{status:#x}")
        self.status = status


def filetime(moment: datetime) -> int:
    elapsed = moment - WINDOWS_EPOCH
    seconds = elapsed.days * 86400 + elapsed.seconds
    return seconds * FILETIME_TICKS_PER_SECOND + elapsed.microseconds * 10


def normalize_path(raw: str) -> tuple[str, ...]:
    """The components of a share-relative path; `StoreError` for anything that is not plainly one.

    Refused outright: `..` and `.`, a drive letter or alternate stream marker (any colon), NULs and
    other control characters, wildcards, forward slashes, empty components and over-long names.
    """
    invalid = StoreError(nt_errors.STATUS_OBJECT_NAME_INVALID)
    text = raw.removeprefix("\\").removesuffix("\\")
    if not text:
        return ()
    components = tuple(text.split("\\"))
    if len(components) > MAX_DEPTH or not all(_valid_component(item) for item in components):
        raise invalid
    return components


def _valid_component(name: str) -> bool:
    if not name or len(name) > MAX_COMPONENT_CHARS or set(name) == {"."}:
        return False
    return not any(ord(c) < FIRST_PRINTABLE or c in FORBIDDEN_IN_NAMES for c in name)


@dataclass(eq=False)
class Node:
    name: str
    is_dir: bool
    created: int
    modified: int
    data: bytearray = field(default_factory=bytearray)
    children: dict[str, "Node"] = field(default_factory=dict)
    seeded: bool = False


@dataclass
class Budget:
    """What one lan session may keep in memory, shared by every share of every host it sees."""

    byte_cap: int = SESSION_BYTE_CAP
    file_cap: int = FILE_CAP
    node_cap: int = SESSION_NODE_CAP
    used_bytes: int = 0
    used_nodes: int = 0

    def reserve_bytes(self, wanted: int) -> int:
        granted = max(0, min(wanted, self.byte_cap - self.used_bytes))
        self.used_bytes += granted
        return granted

    def release_bytes(self, count: int) -> None:
        self.used_bytes = max(0, self.used_bytes - count)

    def reserve_node(self) -> None:
        if self.used_nodes >= self.node_cap:
            raise StoreError(nt_errors.STATUS_DISK_FULL)
        self.used_nodes += 1

    def release_node(self) -> None:
        self.used_nodes = max(0, self.used_nodes - 1)


class VirtualShare:
    def __init__(self, name: str, root: Node, budget: Budget) -> None:
        self.name = name
        self.root = root
        self.budget = budget

    def resolve(self, parts: tuple[str, ...]) -> Node | None:
        node: Node | None = self.root
        for part in parts:
            if node is None or not node.is_dir:
                return None
            node = node.children.get(part.casefold())
        return node

    def children(self, directory: Node) -> list[Node]:
        return sorted(directory.children.values(), key=lambda node: node.name.casefold())

    def open(
        self, parts: tuple[str, ...], disposition: int, *, now: int, directory: bool = False
    ) -> tuple[Node, str]:
        """Applies a create disposition; returns the node and what happened to it."""
        if not SUPERSEDE <= disposition <= OVERWRITE_IF:
            raise StoreError(nt_errors.STATUS_INVALID_PARAMETER)
        existing = self.resolve(parts)
        if existing is None:
            return self._create_missing(parts, disposition, now, directory), "created"
        if disposition == CREATE:
            raise StoreError(nt_errors.STATUS_OBJECT_NAME_COLLISION)
        if disposition not in _TRUNCATING:
            return existing, "opened"
        if existing.is_dir:
            raise StoreError(nt_errors.STATUS_ACCESS_DENIED)
        self._empty(existing, now)
        return existing, "superseded" if disposition == SUPERSEDE else "overwritten"

    def make_directory(self, parts: tuple[str, ...], *, now: int) -> Node:
        return self.open(parts, CREATE, now=now, directory=True)[0]

    def read(self, node: Node, offset: int, length: int) -> bytes:
        return bytes(node.data[offset : offset + length])

    def write(self, node: Node, offset: int, data: bytes, *, now: int) -> int:
        """Stores what the caps allow of `data` at `offset`; returns how many bytes were kept."""
        if node.is_dir:
            raise StoreError(nt_errors.STATUS_FILE_IS_A_DIRECTORY)
        if offset >= self.budget.file_cap:
            return 0
        growth = max(0, min(offset + len(data), self.budget.file_cap) - len(node.data))
        granted = self.budget.reserve_bytes(growth)
        node.data.extend(bytes(granted))
        kept = max(0, min(offset + len(data), len(node.data)) - offset)
        node.data[offset : offset + kept] = data[:kept]
        node.modified = now
        return kept

    def remove(self, parts: tuple[str, ...]) -> None:
        if not parts:
            raise StoreError(nt_errors.STATUS_ACCESS_DENIED)
        parent = self._parent(parts)
        node = parent.children.get(parts[-1].casefold())
        if node is None:
            raise StoreError(nt_errors.STATUS_OBJECT_NAME_NOT_FOUND)
        if node.children:
            raise StoreError(nt_errors.STATUS_DIRECTORY_NOT_EMPTY)
        del parent.children[parts[-1].casefold()]
        self._release(node)

    def rename(
        self, old: tuple[str, ...], new: tuple[str, ...], *, replace: bool, now: int
    ) -> None:
        node = self.resolve(old)
        if node is None or not old or not new:
            raise StoreError(nt_errors.STATUS_OBJECT_NAME_NOT_FOUND)
        if _inside(new, old):
            raise StoreError(nt_errors.STATUS_ACCESS_DENIED)
        target_parent = self._parent(new)
        target = target_parent.children.get(new[-1].casefold())
        if target is not None and target is not node:
            self._replace_target(target_parent, target, new[-1], replace=replace)
        del self._parent(old).children[old[-1].casefold()]
        node.name = new[-1]
        node.modified = now
        target_parent.children[new[-1].casefold()] = node

    def _replace_target(self, parent: Node, target: Node, name: str, *, replace: bool) -> None:
        if not replace:
            raise StoreError(nt_errors.STATUS_OBJECT_NAME_COLLISION)
        if target.is_dir:
            raise StoreError(nt_errors.STATUS_ACCESS_DENIED)
        del parent.children[name.casefold()]
        self._release(target)

    def _create_missing(
        self, parts: tuple[str, ...], disposition: int, now: int, directory: bool
    ) -> Node:
        if not parts:
            raise StoreError(nt_errors.STATUS_OBJECT_NAME_NOT_FOUND)
        parent = self._parent(parts)
        if disposition in (OPEN, OVERWRITE):
            raise StoreError(nt_errors.STATUS_OBJECT_NAME_NOT_FOUND)
        self.budget.reserve_node()
        node = Node(parts[-1], directory, created=now, modified=now)
        parent.children[parts[-1].casefold()] = node
        return node

    def _parent(self, parts: tuple[str, ...]) -> Node:
        parent = self.resolve(parts[:-1])
        if parent is None or not parent.is_dir:
            raise StoreError(nt_errors.STATUS_OBJECT_PATH_NOT_FOUND)
        return parent

    def _empty(self, node: Node, now: int) -> None:
        self.budget.release_bytes(0 if node.seeded else len(node.data))
        node.data.clear()
        node.modified = now

    def _release(self, node: Node) -> None:
        if node.seeded:
            return
        self.budget.release_bytes(len(node.data))
        self.budget.release_node()


def new_share(name: str, budget: Budget, *, now: int) -> VirtualShare:
    root = Node("", True, created=now, modified=now, seeded=True)
    share = VirtualShare(name, root, budget)
    for parts in _SEEDED_DIRECTORIES.get(name.upper(), []):
        _seed(share, parts, now, is_dir=True)
    _seed(share, ("README.txt",), now, is_dir=False)
    return share


def _seed(share: VirtualShare, parts: tuple[str, ...], now: int, *, is_dir: bool) -> None:
    parent = share.resolve(parts[:-1])
    assert parent is not None  # noqa: S101 - the seed lists name parents before children
    node = Node(parts[-1], is_dir, created=now, modified=now, seeded=True)
    if not is_dir:
        node.data.extend(README_TEXT)
    parent.children[parts[-1].casefold()] = node


def _inside(path: tuple[str, ...], ancestor: tuple[str, ...]) -> bool:
    folded = tuple(part.casefold() for part in path)
    return len(path) > len(ancestor) and folded[: len(ancestor)] == tuple(
        part.casefold() for part in ancestor
    )
