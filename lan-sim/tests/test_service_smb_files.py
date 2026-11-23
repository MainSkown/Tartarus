"""Files on the shares, end to end: impacket's client against the in-memory store."""

import contextlib
import hashlib
import io
import os
import struct
import time

import pytest
from impacket import nt_errors
from impacket.smb3structs import FILE_DIRECTORY_FILE, FILE_WRITE_DATA, SMB2_DIALECT_21
from impacket.smbconnection import SessionError
from test_service_smb_support import MIB, SmbWorld

from lan_sim.services.smb import SmbService
from lan_sim.services.smb_state import SmbStates
from lan_sim.services.smb_store import Budget


@pytest.fixture
def world(tmp_path):
    with SmbWorld(tmp_path, shares=["Public"]) as running:
        yield running


def names(smb, share, pattern="*") -> list[str]:
    return sorted(entry.get_longname() for entry in smb.listPath(share, pattern))


def put(smb, share, path, content: bytes) -> None:
    smb.putFile(share, path, io.BytesIO(content).read)


def get(smb, share, path) -> bytes:
    out = io.BytesIO()
    smb.getFile(share, path, out.write)
    return out.getvalue()


def refused_with(call) -> int:
    with pytest.raises(SessionError) as caught:
        call()
    return caught.value.getErrorCode()


def test_dir_of_the_c_share_looks_alive(world):
    smb = world.client()
    assert names(smb, "C$") == ["Program Files", "README.txt", "Users", "Windows"]
    assert names(smb, "C$", "Windows\\*") == [".", "..", "System32", "Temp"]
    assert names(smb, "C$", "Windows\\System32\\*") == [".", ".."]
    assert names(smb, "C$", "*.txt") == ["README.txt"]


def test_a_pattern_that_matches_nothing_is_an_empty_listing(world):
    smb = world.client()
    assert refused_with(lambda: smb.listPath("C$", "zzz*")) == nt_errors.STATUS_NO_SUCH_FILE


def test_every_share_has_a_readme_and_the_listed_share_exists(world):
    smb = world.client()
    for share in ("ADMIN$", "C$", "Public"):
        assert "README.txt" in names(smb, share)
    assert b"managed file share" in get(smb, "Public", "README.txt")


def test_a_put_to_admin_share_lands_in_the_store_and_is_logged_with_its_hash(world):
    payload = os.urandom(150_000)
    smb = world.client()
    put(smb, "ADMIN$", "payload.exe", payload)
    assert get(smb, "ADMIN$", "payload.exe") == payload
    assert "payload.exe" in names(smb, "ADMIN$")
    [written] = world.records("file-write")
    assert written["share"] == "ADMIN$"
    assert written["path"] == "\\payload.exe"
    assert written["size"] == len(payload)
    assert written["sha256"] == hashlib.sha256(payload).hexdigest()
    assert written["truncated"] is False
    assert any(
        r["operation"] == "create" and r["path"] == "\\payload.exe"
        for r in world.records("share-access")
    )


def test_files_outlive_the_connection_that_wrote_them(world):
    first = world.client()
    put(first, "C$", "dropped.bin", b"stays")
    first.logoff()
    second = world.client()
    assert get(second, "C$", "dropped.bin") == b"stays"


def test_files_of_one_session_are_not_visible_to_another(tmp_path):
    with SmbWorld(tmp_path / "a") as first, SmbWorld(tmp_path / "b") as second:
        put(first.client(), "C$", "mine.bin", b"x")
        assert "mine.bin" not in names(second.client(), "C$")


def test_a_second_20_mib_put_is_capped_but_still_hashed_whole(world):
    smb = world.client(login=False, preferredDialect=SMB2_DIALECT_21)
    smb.login("Administrator", "Passw0rd!", "CORP")
    first = os.urandom(300_000)
    put(smb, "ADMIN$", "first.bin", first)
    big = os.urandom(MIB) * 20
    started = time.monotonic()
    put(smb, "ADMIN$", "big.bin", big)
    assert time.monotonic() - started < 60
    stored = get(smb, "ADMIN$", "big.bin")
    assert len(stored) == 16 * MIB
    assert stored == big[: 16 * MIB]
    big_log = next(r for r in world.records("file-write") if r["path"] == "\\big.bin")
    assert big_log["size"] == 20 * MIB
    assert big_log["sha256"] == hashlib.sha256(big).hexdigest()
    assert big_log["truncated"] is True


def test_the_session_cap_stops_storing_across_files(tmp_path):
    states = SmbStates(budget_factory=lambda: Budget(byte_cap=3 * MIB, file_cap=2 * MIB))
    with SmbWorld(tmp_path, smb_implementation=SmbService(states)) as small:
        smb = small.client()
        for name in ("a", "b", "c"):
            put(smb, "C$", name, bytes([ord(name)]) * (2 * MIB))
        sizes = {entry.get_longname(): entry.get_filesize() for entry in smb.listPath("C$", "*")}
        assert (sizes["a"], sizes["b"], sizes["c"]) == (2 * MIB, MIB, 0)
        logged = {r["path"]: r for r in small.records("file-write")}
        assert logged["\\c"]["size"] == 2 * MIB
        assert logged["\\c"]["truncated"] is True
        assert logged["\\a"]["truncated"] is False
        assert logged["\\b"]["truncated"] is True


@pytest.mark.parametrize(
    "path",
    [
        "..\\..\\Windows\\evil.txt",
        "..",
        "C:\\evil.txt",
        "C:evil.txt",
        "evil.txt:stream",
        "evil.txt::$DATA",
        "nul\x00.txt",
        "a" * 400,
        "dir\\" * 40 + "x",
        "wild*.txt",
        "pipe|name",
    ],
)
def test_hostile_names_are_refused_and_create_nothing(world, tmp_path, path):
    smb = world.client()
    tree = smb.connectTree("C$")
    before = names(smb, "C$")
    status = refused_with(lambda: smb.createFile(tree, path))
    assert status == nt_errors.STATUS_OBJECT_NAME_INVALID
    assert names(smb, "C$") == before


def test_no_file_is_created_on_the_host(world, tmp_path, monkeypatch):
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    before = {p for p in tmp_path.rglob("*") if "root" not in p.parts}
    smb = world.client()
    put(smb, "ADMIN$", "evil.exe", b"MZ" * 1000)
    smb.createDirectory("C$", "dropdir")
    for hostile in ("..\\x", "/etc/passwd", "\\\\host\\x"):
        with contextlib.suppress(SessionError):
            smb.createFile(smb.connectTree("C$"), hostile)
    assert os.listdir(workdir) == []
    assert {p for p in tmp_path.rglob("*") if "root" not in p.parts} == before


def test_directories_can_be_made_removed_and_renamed(world):
    smb = world.client()
    smb.createDirectory("C$", "drop")
    put(smb, "C$", "drop\\a.txt", b"1")
    assert refused_with(lambda: smb.deleteDirectory("C$", "drop")) == (
        nt_errors.STATUS_DIRECTORY_NOT_EMPTY
    )
    smb.rename("C$", "drop\\a.txt", "drop\\b.txt")
    assert names(smb, "C$", "drop\\*") == [".", "..", "b.txt"]
    smb.deleteFile("C$", "drop\\b.txt")
    smb.deleteDirectory("C$", "drop")
    assert "drop" not in names(smb, "C$")
    operations = {r["operation"] for r in world.records("share-access")}
    assert {"rename", "delete", "list"} <= operations


def test_a_rename_to_a_hostile_name_is_refused(world):
    smb = world.client()
    put(smb, "C$", "a.txt", b"1")
    assert refused_with(lambda: smb.rename("C$", "a.txt", "..\\..\\b.txt")) == (
        nt_errors.STATUS_OBJECT_NAME_INVALID
    )
    assert "a.txt" in names(smb, "C$")


def test_missing_things_report_the_right_status(world):
    smb = world.client()
    tree = smb.connectTree("C$")
    assert refused_with(lambda: smb.openFile(tree, "nope.txt")) == (
        nt_errors.STATUS_OBJECT_NAME_NOT_FOUND
    )
    assert refused_with(lambda: smb.openFile(tree, "nodir\\nope.txt")) == (
        nt_errors.STATUS_OBJECT_PATH_NOT_FOUND
    )


def test_a_directory_can_be_opened_for_write_as_psexec_probes_it(world):
    smb = world.client()
    tree = smb.connectTree("ADMIN$")
    handle = smb.openFile(tree, "\\", FILE_WRITE_DATA, creationOption=FILE_DIRECTORY_FILE)
    smb.closeFile(tree, handle)


def test_query_info_reports_the_size_of_a_file(world):
    smb = world.client()
    put(smb, "C$", "sized.bin", b"x" * 1234)
    tree = smb.connectTree("C$")
    handle = smb.openFile(tree, "sized.bin")
    info = smb.getSMBServer().queryInfo(tree, handle)
    assert struct.unpack_from("<Q", info, 8)[0] == 1234
    smb.closeFile(tree, handle)


def test_an_unknown_share_is_refused_and_logged(world):
    smb = world.client()
    assert refused_with(lambda: smb.connectTree("Secret")) == nt_errors.STATUS_BAD_NETWORK_NAME
    operations = [(r["share"], r["operation"]) for r in world.records("share-access")]
    assert ("Secret", "tree-connect-refused") in operations


def test_tree_connects_to_every_share_are_logged(world):
    smb = world.client()
    for share in ("IPC$", "ADMIN$", "C$", "Public"):
        smb.connectTree(share)
    logged = {r["share"] for r in world.records("share-access") if r["operation"] == "tree-connect"}
    assert logged == {"IPC$", "ADMIN$", "C$", "Public"}


def test_the_ipc_share_has_no_files_and_cannot_be_written(world):
    smb = world.client()
    assert refused_with(lambda: smb.listPath("IPC$", "*")) != 0
    tree = smb.connectTree("IPC$")
    assert refused_with(lambda: smb.createFile(tree, "evil.txt")) == (
        nt_errors.STATUS_OBJECT_NAME_NOT_FOUND
    )


def test_a_write_in_flight_is_logged_when_the_connection_drops(world):
    smb = world.client()
    tree = smb.connectTree("C$")
    handle = smb.createFile(tree, "partial.bin")
    smb.writeFile(tree, handle, b"half")
    smb.getSMBServer().get_socket().close()
    for _ in range(100):
        if world.records("file-write"):
            break
        time.sleep(0.05)
    [written] = world.records("file-write")
    assert written["size"] == 4
    assert written["sha256"] == hashlib.sha256(b"half").hexdigest()
