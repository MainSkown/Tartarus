"""The file commands of SMB2 on open handles: create, read, write, query, set info, close.

Shares are served from the in-memory store only; no client-supplied name is ever turned into a host
path. Every write is hashed as it arrives and logged as one `file-write` when its handle closes.
"""

import struct
from collections.abc import Callable
from contextlib import suppress

from impacket import nt_errors

from lan_sim.services import smb_info as info
from lan_sim.services import smb_messages as messages
from lan_sim.services.smb_pipes import PipeContext, open_pipe
from lan_sim.services.smb_store import StoreError, VirtualShare, normalize_path
from lan_sim.services.smb_types import OpenFile, RefusalError, Reply, Request, WriteRecord
from lan_sim.session_log import ConnectionLog

MAX_HANDLES = 256
MAX_IO_BYTES = 65536

OPTION_DIRECTORY_FILE = 0x1
OPTION_NON_DIRECTORY_FILE = 0x40
OPTION_DELETE_ON_CLOSE = 0x1000
FLAG_RESTART_SCANS = 0x1
FLAG_SINGLE_ENTRY = 0x2
CLOSE_QUERY_ATTRIBUTES = 0x1

SET_BASIC, SET_RENAME, SET_DISPOSITION, SET_ALLOCATION, SET_END_OF_FILE = 4, 10, 13, 19, 20
SET_DISPOSITION_EX, SET_RENAME_EX = 64, 65
_ACCEPTED_AND_IGNORED = (SET_BASIC, SET_ALLOCATION, SET_END_OF_FILE)
_RENAME_HEADER = struct.Struct("<B7xQI")
_CREATE_ACTIONS = {"superseded": 0, "opened": 1, "created": 2, "overwritten": 3}
_VARIABLE_CLASSES = (info.FILE_ALL, info.FILE_NAME, info.FILE_STREAM)
_VARIABLE_FS_CLASSES = (info.FS_VOLUME, info.FS_ATTRIBUTE)
_ZERO_TIMES = (0, 0, 0, 0)


class FileHandler:
    """The open handles of one connection and the commands that act on them."""

    def __init__(self, log: ConnectionLog, now: Callable[[], int], pipes: PipeContext) -> None:
        self._log = log
        self._now = now
        self._pipes = pipes
        self.handles: dict[int, OpenFile] = {}
        self._next_id = 1

    def create(self, request: Request) -> Reply:
        parsed = messages.parse_create(request.body)
        if len(self.handles) >= MAX_HANDLES:
            raise RefusalError(nt_errors.STATUS_TOO_MANY_OPENED_FILES)
        tree, session = _bound(request)
        handle = OpenFile(self._next_id, session.session_id, tree, ())
        if tree.share is None:
            handle.parts = _pipe_parts(parsed.name)
            handle.pipe = open_pipe(handle.parts[-1], self._pipes)
            action = "opened"
        else:
            action = self._open_node(handle, tree.share, parsed)
        self._next_id += 1
        self.handles[handle.file_id] = handle
        return Reply(body=self._create_body(handle, action), file_id=handle.wire_id)

    def close(self, request: Request) -> Reply:
        handle = self._handle(request, messages.parse_close(request.body))
        body = messages.close_response(
            times=info.times_of(handle.node) if handle.node else _ZERO_TIMES,
            allocation=info.allocation_of(handle.node) if handle.node else 0,
            size=info.size_of(handle.node) if handle.node else 0,
            attributes=info.attributes_of(handle.node) if handle.node else 0,
        )
        self.release(handle)
        return Reply(body=body)

    def flush(self, request: Request) -> Reply:
        self._handle(request, messages.parse_file_id_only(request.body, 24))
        return Reply(body=messages.empty_response())

    def lock(self, request: Request) -> Reply:
        self._handle(request, messages.parse_file_id_only(request.body, 48))
        return Reply(body=messages.empty_response())

    def read(self, request: Request) -> Reply:
        parsed = messages.parse_read(request.body)
        handle = self._handle(request, parsed.file_id)
        if parsed.length > MAX_IO_BYTES:
            raise RefusalError(nt_errors.STATUS_INVALID_PARAMETER)
        if handle.pipe is not None:
            return _pipe_read(handle.pipe, parsed.length)
        node, share = _file_of(handle)
        if parsed.offset >= len(node.data):
            raise RefusalError(nt_errors.STATUS_END_OF_FILE)
        self._log_once_read(handle)
        return Reply(body=messages.read_response(share.read(node, parsed.offset, parsed.length)))

    def write(self, request: Request) -> Reply:
        parsed = messages.parse_write(request.body, MAX_IO_BYTES)
        handle = self._handle(request, parsed.file_id)
        if handle.pipe is not None:
            handle.pipe.write(parsed.data)
            return Reply(body=messages.write_response(len(parsed.data)))
        node, share = _file_of(handle)
        try:
            kept = share.write(node, parsed.offset, parsed.data, now=self._now())
        except StoreError as error:
            raise RefusalError(error.status) from error
        handle.writes = handle.writes or WriteRecord()
        handle.writes.feed(parsed.offset, parsed.data, kept)
        return Reply(body=messages.write_response(len(parsed.data)))

    def transceive(self, request: Request, data: bytes, max_output: int, file_id: bytes) -> bytes:
        handle = self._handle(request, file_id)
        if handle.pipe is None:
            raise RefusalError(nt_errors.STATUS_NOT_SUPPORTED)
        output, more = handle.pipe.transceive(data, max_output)
        if more:
            raise PipeOverflowError(output)
        return output

    def query_directory(self, request: Request) -> Reply:
        parsed = messages.parse_query_directory(request.body)
        handle = self._handle(request, parsed.file_id)
        node, share = _file_of(handle)
        if not node.is_dir:
            raise RefusalError(nt_errors.STATUS_INVALID_PARAMETER)
        if not info.supports_directory_class(parsed.info_class):
            raise RefusalError(nt_errors.STATUS_INVALID_INFO_CLASS)
        if handle.listing is None or parsed.flags & FLAG_RESTART_SCANS:
            handle.listing = self._listing(handle, share, parsed.pattern)
            handle.listing_position = 0
        return _directory_page(handle, parsed)

    def query_info(self, request: Request) -> Reply:
        parsed = messages.parse_query_info(request.body)
        handle = self._handle(request, parsed.file_id)
        node, _ = _file_of(handle)
        if parsed.info_type == info.INFO_FILE:
            data = info.file_info(parsed.info_class, node, "\\".join(handle.parts), handle.file_id)
            variable = parsed.info_class in _VARIABLE_CLASSES
        elif parsed.info_type == info.INFO_FILESYSTEM:
            data = info.filesystem_info(parsed.info_class)
            variable = parsed.info_class in _VARIABLE_FS_CLASSES
        else:
            raise RefusalError(nt_errors.STATUS_NOT_SUPPORTED)
        if data is None:
            raise RefusalError(nt_errors.STATUS_INVALID_INFO_CLASS)
        if len(data) > parsed.output_length:
            if not variable:
                raise RefusalError(nt_errors.STATUS_INFO_LENGTH_MISMATCH)
            return Reply(
                nt_errors.STATUS_BUFFER_OVERFLOW,
                messages.output_response(data[: parsed.output_length]),
            )
        return Reply(body=messages.output_response(data))

    def set_info(self, request: Request) -> Reply:
        parsed = messages.parse_set_info(request.body)
        handle = self._handle(request, parsed.file_id)
        node, share = _file_of(handle)
        if parsed.info_type != info.INFO_FILE:
            raise RefusalError(nt_errors.STATUS_NOT_SUPPORTED)
        if parsed.info_class in (SET_RENAME, SET_RENAME_EX):
            self._rename(handle, share, parsed.buffer)
        elif parsed.info_class in (SET_DISPOSITION, SET_DISPOSITION_EX):
            self._mark_for_deletion(handle, node, parsed.buffer)
        elif parsed.info_class not in _ACCEPTED_AND_IGNORED:
            raise RefusalError(nt_errors.STATUS_INVALID_INFO_CLASS)
        return Reply(body=messages.set_info_response())

    def release(self, handle: OpenFile) -> None:
        """Logs the handle's writes, applies a pending delete and forgets it."""
        self._log_writes(handle)
        if handle.delete_on_close and handle.tree.share is not None:
            with suppress(StoreError):
                handle.tree.share.remove(handle.parts)
        self.handles.pop(handle.file_id, None)

    def release_matching(self, session_id: int, tree_id: int | None = None) -> None:
        for handle in list(self.handles.values()):
            if handle.session_id == session_id and tree_id in (None, handle.tree.tree_id):
                self.release(handle)

    def release_all(self) -> None:
        for handle in list(self.handles.values()):
            self.release(handle)

    def _handle(self, request: Request, wire_id: bytes) -> OpenFile:
        tree, session = _bound(request)
        persistent, volatile = struct.unpack("<QQ", wire_id)
        handle = self.handles.get(volatile)
        if handle is None or persistent != volatile:
            raise RefusalError(nt_errors.STATUS_FILE_CLOSED)
        if handle.session_id != session.session_id or handle.tree is not tree:
            raise RefusalError(nt_errors.STATUS_FILE_CLOSED)
        return handle

    def _open_node(
        self, handle: OpenFile, share: VirtualShare, parsed: messages.CreateRequest
    ) -> str:
        try:
            handle.parts = normalize_path(parsed.name)
            existing = share.resolve(handle.parts)
            _check_kind(existing, parsed.options)
            handle.node, action = share.open(
                handle.parts,
                parsed.disposition,
                now=self._now(),
                directory=bool(parsed.options & OPTION_DIRECTORY_FILE),
            )
        except StoreError as error:
            raise RefusalError(error.status) from error
        handle.delete_on_close = bool(parsed.options & OPTION_DELETE_ON_CLOSE)
        operation = "create" if action == "created" else "open"
        self._log.share_access(share=share.name, path=handle.path, operation=operation)
        return action

    def _create_body(self, handle: OpenFile, action: str) -> bytes:
        node = handle.node
        return messages.create_response(
            action=_CREATE_ACTIONS[action],
            times=info.times_of(node) if node else _ZERO_TIMES,
            allocation=info.allocation_of(node) if node else 0,
            size=info.size_of(node) if node else 0,
            attributes=info.attributes_of(node) if node else info.ATTRIBUTE_ARCHIVE,
            file_id=handle.wire_id,
        )

    def _listing(self, handle: OpenFile, share: VirtualShare, pattern: str) -> list:
        node = handle.node
        assert node is not None  # noqa: S101 - callers resolved the handle to a node first
        self._log.share_access(share=share.name, path=handle.path, operation="list")
        entries = [info.DirectoryEntry(child.name, child) for child in share.children(node)]
        if handle.parts:
            entries = [info.DirectoryEntry(".", node), info.DirectoryEntry("..", node), *entries]
        return [entry for entry in entries if info.matches(pattern, entry.name)]

    def _log_once_read(self, handle: OpenFile) -> None:
        if not handle.read_logged:
            handle.read_logged = True
            self._log.share_access(share=handle.tree.share_name, path=handle.path, operation="read")

    def _log_writes(self, handle: OpenFile) -> None:
        record, node = handle.writes, handle.node
        if record is None or node is None:
            return
        handle.writes = None
        size, digest = record.digest(node)
        self._log.file_write(
            share=handle.tree.share_name,
            path=handle.path,
            size=size,
            sha256=digest,
            truncated=record.dropped,
        )

    def _rename(self, handle: OpenFile, share: VirtualShare, buffer: bytes) -> None:
        if len(buffer) < _RENAME_HEADER.size:
            raise RefusalError(nt_errors.STATUS_INFO_LENGTH_MISMATCH)
        replace, _, length = _RENAME_HEADER.unpack_from(buffer)
        raw = buffer[_RENAME_HEADER.size : _RENAME_HEADER.size + length]
        if len(raw) != length or length % 2:
            raise RefusalError(nt_errors.STATUS_INVALID_PARAMETER)
        try:
            new_parts = normalize_path(raw.decode("utf-16le", "replace"))
            share.rename(handle.parts, new_parts, replace=bool(replace), now=self._now())
        except StoreError as error:
            raise RefusalError(error.status) from error
        old_path, handle.parts = handle.path, new_parts
        self._log.share_access(
            share=share.name, path=f"{old_path} -> {handle.path}", operation="rename"
        )

    def _mark_for_deletion(self, handle: OpenFile, node, buffer: bytes) -> None:
        if not buffer:
            raise RefusalError(nt_errors.STATUS_INFO_LENGTH_MISMATCH)
        if not buffer[0] & 1:
            handle.delete_on_close = False
            return
        if node.children:
            raise RefusalError(nt_errors.STATUS_DIRECTORY_NOT_EMPTY)
        handle.delete_on_close = True
        self._log.share_access(share=handle.tree.share_name, path=handle.path, operation="delete")


class PipeOverflowError(Exception):
    """A pipe reply larger than the client's buffer: the first part, with a warning status."""

    def __init__(self, output: bytes) -> None:
        super().__init__("pipe reply larger than the buffer")
        self.output = output


def _bound(request: Request):
    if request.tree is None or request.session is None:
        raise RefusalError(nt_errors.STATUS_NETWORK_NAME_DELETED)
    return request.tree, request.session


def _pipe_parts(name: str) -> tuple[str, ...]:
    try:
        parts = normalize_path(name)
    except StoreError as error:
        raise RefusalError(error.status) from error
    if parts and parts[0].casefold() == "pipe":
        parts = parts[1:]
    if len(parts) != 1:
        raise RefusalError(
            nt_errors.STATUS_ACCESS_DENIED if not parts else nt_errors.STATUS_OBJECT_NAME_NOT_FOUND
        )
    return (parts[0].lower(),)


def _file_of(handle: OpenFile):
    if handle.node is None or handle.tree.share is None:
        raise RefusalError(nt_errors.STATUS_NOT_SUPPORTED)
    return handle.node, handle.tree.share


def _check_kind(existing, options: int) -> None:
    if existing is None:
        return
    if options & OPTION_DIRECTORY_FILE and not existing.is_dir:
        raise StoreError(nt_errors.STATUS_NOT_A_DIRECTORY)
    if options & OPTION_NON_DIRECTORY_FILE and existing.is_dir:
        raise StoreError(nt_errors.STATUS_FILE_IS_A_DIRECTORY)


def _pipe_read(pipe, length: int) -> Reply:
    data, more = pipe.read(length)
    if not data:
        raise RefusalError(nt_errors.STATUS_PIPE_EMPTY)
    status = nt_errors.STATUS_BUFFER_OVERFLOW if more else nt_errors.STATUS_SUCCESS
    return Reply(status, messages.read_response(data))


def _directory_page(handle: OpenFile, parsed: messages.QueryDirectoryRequest) -> Reply:
    listing = handle.listing or []
    remaining = listing[handle.listing_position :]
    if not remaining:
        raise RefusalError(
            nt_errors.STATUS_NO_MORE_FILES
            if handle.listing_position
            else nt_errors.STATUS_NO_SUCH_FILE
        )
    if parsed.flags & FLAG_SINGLE_ENTRY:
        remaining = remaining[:1]
    packed, used = info.pack_directory_entries(parsed.info_class, remaining, parsed.output_length)
    if not used:
        raise RefusalError(nt_errors.STATUS_INFO_LENGTH_MISMATCH)
    handle.listing_position += used
    return Reply(body=messages.output_response(packed))
