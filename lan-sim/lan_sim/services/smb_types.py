"""The state an SMB connection keeps: sessions, trees, open handles, and a command's reply."""

import hashlib
import struct
from dataclasses import dataclass, field
from typing import Protocol

from impacket import nt_errors

from lan_sim.services.smb_signing import PreauthHash
from lan_sim.services.smb_store import Node, VirtualShare
from lan_sim.services.smb_wire import Header

FILE_ID_STRUCT = struct.Struct("<QQ")


class RefusalError(Exception):
    """A command that fails with an NT status; the client gets an error reply, nothing more."""

    def __init__(self, status: int) -> None:
        super().__init__(f"{status:#x}")
        self.status = status


@dataclass
class Reply:
    status: int = nt_errors.STATUS_SUCCESS
    body: bytes = b""
    session_id: int | None = None
    tree_id: int | None = None
    file_id: bytes | None = None
    transcript: PreauthHash | None = None


class Pipe(Protocol):
    """One open named pipe: DCERPC PDUs go in with `write` or `transceive`, come out of `read`."""

    def write(self, data: bytes) -> None: ...

    def read(self, size: int) -> tuple[bytes, bool]:
        """Up to `size` bytes of the next reply, and whether more of that reply is left."""
        ...

    def transceive(self, data: bytes, size: int) -> tuple[bytes, bool]: ...


@dataclass(eq=False)
class Tree:
    tree_id: int
    share_name: str
    share: VirtualShare | None

    @property
    def is_pipe(self) -> bool:
        return self.share is None


@dataclass(eq=False)
class Session:
    session_id: int
    challenge: bytes
    preauth: PreauthHash
    user: str = ""
    signing_key: bytes | None = None
    trees: dict[int, Tree] = field(default_factory=dict)
    next_tree_id: int = 1

    @property
    def active(self) -> bool:
        return self.signing_key is not None


class WriteRecord:
    """Hashes what a client writes as it arrives, so a file over the cap still has its sha256."""

    def __init__(self) -> None:
        self._sha = hashlib.sha256()
        self.sent = 0
        self.dropped = False
        self.sequential = True

    def feed(self, offset: int, data: bytes, kept: int) -> None:
        if offset != self.sent:
            self.sequential = False
        self._sha.update(data)
        self.sent += len(data)
        self.dropped = self.dropped or kept < len(data)

    def digest(self, node: Node) -> tuple[int, str]:
        """(size, sha256): the stream's when writes came in order, else the stored content's."""
        if self.sequential:
            return self.sent, self._sha.hexdigest()
        return len(node.data), hashlib.sha256(node.data).hexdigest()


@dataclass(eq=False)
class OpenFile:
    file_id: int
    session_id: int
    tree: Tree
    parts: tuple[str, ...]
    node: Node | None = None
    pipe: Pipe | None = None
    delete_on_close: bool = False
    writes: WriteRecord | None = None
    listing: list | None = None
    listing_position: int = 0
    read_logged: bool = False

    @property
    def wire_id(self) -> bytes:
        return FILE_ID_STRUCT.pack(self.file_id, self.file_id)

    @property
    def path(self) -> str:
        return "\\" + "\\".join(self.parts)


@dataclass
class Request:
    header: Header
    body: bytes
    raw: bytes
    session: Session | None = None
    tree: Tree | None = None
