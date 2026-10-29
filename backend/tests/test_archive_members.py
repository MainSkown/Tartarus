import logging
import struct
import warnings
import zipfile
from pathlib import Path

import pytest
import pyzipper

from app.samples import archive
from app.samples.archive import (
    MAX_CENTRAL_DIRECTORY_BYTES,
    MAX_DECLARED_BYTES,
    MAX_MEMBERS,
    ArchiveError,
    ArchiveMember,
    read_archive,
)

PASSWORD = "infected"  # noqa: S105
ZIPCRYPTO_FIXTURE = Path(__file__).parent / "fixtures" / "archives" / "zipcrypto-infected.zip"
ZIPCRYPTO_HEADER_LENGTH = 12
AES_256_HEADER_LENGTH = 16 + 2
EOCD_LENGTH = 22
LOCAL_EXTRA_LENGTH_OFFSET = 28
SCRAMBLED = b"\xff"


def write_aes_zip(path: Path, members: dict[str, bytes], password: str = PASSWORD) -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pyzipper.AESZipFile(
            path, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES
        ) as written:
            written.setpassword(password.encode())
            for name, content in members.items():
                written.writestr(name, content)
    return path


def write_plain_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as written:
        for name, content in members.items():
            written.writestr(name, content)
    return path


def rewrite_bytes(path: Path, old: bytes, new: bytes) -> Path:
    path.write_bytes(path.read_bytes().replace(old, new))
    return path


def scramble_member_data(path: Path, header_length: int) -> None:
    """Overwrites everything after the encryption header of the first member with 0xFF."""
    with pyzipper.AESZipFile(path) as opened:
        info = opened.infolist()[0]
    raw = path.read_bytes()
    name_length, extra_length = struct.unpack_from("<HH", raw, info.header_offset + 26)
    data_start = info.header_offset + 30 + name_length + extra_length
    start, end = data_start + header_length, data_start + info.compress_size
    path.write_bytes(raw[:start] + SCRAMBLED * (end - start) + raw[end:])


def with_zip64_end_records(path: Path, *, central_directory_size: int | None = None) -> Path:
    """Rewrites a one-comment-free zip so its sizes live in zip64 end records."""
    raw = path.read_bytes()
    body, eocd = raw[:-EOCD_LENGTH], raw[-EOCD_LENGTH:]
    _, _, _, _, entries, real_size, offset, _ = struct.unpack("<IHHHHIIH", eocd)
    size = real_size if central_directory_size is None else central_directory_size
    zip64_record = struct.pack(
        "<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, entries, entries, size, offset
    )
    locator = struct.pack("<IIQI", 0x07064B50, 0, len(body), 1)
    # Only a forged size has to be told apart from the end record's own field.
    eocd_size = 0xFFFFFFFF if central_directory_size is None else real_size
    marked_eocd = struct.pack(
        "<IHHHHIIH", 0x06054B50, 0, 0, 0xFFFF, 0xFFFF, eocd_size, 0xFFFFFFFF, 0
    )
    path.write_bytes(body + zip64_record + locator + marked_eocd)
    return path


def with_forged_central_directory_size(path: Path, size: int) -> Path:
    raw = bytearray(path.read_bytes())
    struct.pack_into("<I", raw, len(raw) - EOCD_LENGTH + 12, size)
    path.write_bytes(raw)
    return path


def mark_every_entry_utf8(path: Path) -> None:
    raw = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = raw.find(signature)
        while position != -1:
            raw[position + flag_offset + 1] |= 0x08  # bit 11, in the high byte
            position = raw.find(signature, position + 1)
    path.write_bytes(raw)


def refuse_to_parse(*_: object, **__: object) -> None:
    raise AssertionError("the stdlib was asked to parse the central directory")


def listed(path: Path, password: str = PASSWORD) -> dict[str, ArchiveMember]:
    return {member.name: member for member in read_archive(path, password).members}


def test_one_aes_member_is_listed_with_its_declared_size(tmp_path: Path) -> None:
    path = write_aes_zip(tmp_path / "one.zip", {"sample.exe": b"MZ" * 50})

    listing = read_archive(path, PASSWORD)

    assert listing.members == [
        ArchiveMember(name="sample.exe", size=100, encrypted=True, unsafe=False, unsupported=False)
    ]
    assert listing.password_ok is True


def test_three_aes_members_are_listed_in_archive_order(tmp_path: Path) -> None:
    path = write_aes_zip(
        tmp_path / "three.zip", {"b.exe": b"1", "a.dll": b"22", "docs/readme.txt": b"333"}
    )

    listing = read_archive(path, PASSWORD)

    assert [(member.name, member.size) for member in listing.members] == [
        ("b.exe", 1),
        ("a.dll", 2),
        ("docs/readme.txt", 3),
    ]
    assert all(member.encrypted for member in listing.members)
    assert listing.password_ok is True


def test_wrong_aes_password_is_reported_not_raised(tmp_path: Path) -> None:
    path = write_aes_zip(tmp_path / "one.zip", {"sample.exe": b"MZ"})

    listing = read_archive(path, "not-the-password")

    assert listing.password_ok is False
    assert [member.name for member in listing.members] == ["sample.exe"]


def test_empty_password_on_an_encrypted_zip_is_a_wrong_password(tmp_path: Path) -> None:
    path = write_aes_zip(tmp_path / "one.zip", {"sample.exe": b"MZ"})

    assert read_archive(path, "").password_ok is False


def test_zipcrypto_member_is_listed_and_the_right_password_accepted() -> None:
    listing = read_archive(ZIPCRYPTO_FIXTURE, PASSWORD)

    assert listing.members == [
        ArchiveMember(name="hello.txt", size=15, encrypted=True, unsafe=False, unsupported=False)
    ]
    assert listing.password_ok is True


def test_zipcrypto_wrong_password_is_reported() -> None:
    assert read_archive(ZIPCRYPTO_FIXTURE, "nope").password_ok is False


def test_zip_without_encrypted_members_has_no_password_verdict(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "plain.zip", {"sample.exe": b"MZ"})

    listing = read_archive(path, PASSWORD)

    assert listing.members[0].encrypted is False
    assert listing.password_ok is None


def test_encrypted_member_with_an_unsafe_name_is_not_used_to_check_the_password(
    tmp_path: Path,
) -> None:
    path = write_aes_zip(tmp_path / "unsafe.zip", {"../evil.exe": b"MZ"})

    listing = read_archive(path, PASSWORD)

    assert listing.members[0].unsafe is True
    assert listing.password_ok is None


def reading_the_scrambled_member_fails(path: Path) -> bool:
    """Proves the scrambling worked: a reader that touched the data would fail the same way."""
    with pyzipper.AESZipFile(path) as opened:
        opened.setpassword(PASSWORD.encode())
        try:
            opened.read(opened.infolist()[0])
        except Exception:  # noqa: BLE001
            return True
    return False


def test_aes_password_check_decrypts_and_decompresses_nothing(tmp_path: Path) -> None:
    path = write_aes_zip(tmp_path / "aes.zip", {"a.bin": bytes(5000)})
    scramble_member_data(path, AES_256_HEADER_LENGTH)

    assert reading_the_scrambled_member_fails(path)
    assert read_archive(path, PASSWORD).password_ok is True
    assert read_archive(path, "wrong-password").password_ok is False


def test_zipcrypto_password_check_decrypts_and_decompresses_nothing(tmp_path: Path) -> None:
    path = tmp_path / "crypto.zip"
    path.write_bytes(ZIPCRYPTO_FIXTURE.read_bytes())
    scramble_member_data(path, ZIPCRYPTO_HEADER_LENGTH)

    assert reading_the_scrambled_member_fails(path)
    assert read_archive(path, PASSWORD).password_ok is True
    assert read_archive(path, "nope").password_ok is False


def test_directory_entries_are_not_members(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "dirs.zip", {"folder/": b"", "folder/run.exe": b"MZ"})

    assert list(listed(path)) == ["folder/run.exe"]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="empty-file"),
        pytest.param(b"this is definitely not a zip file" * 10, id="not-a-zip"),
        pytest.param(b"PK\x03\x04" + bytes(40), id="local-header-only"),
    ],
)
def test_data_that_is_not_a_zip_is_rejected(content: bytes, tmp_path: Path) -> None:
    path = tmp_path / "bad.zip"
    path.write_bytes(content)

    with pytest.raises(ArchiveError, match="not a valid zip"):
        read_archive(path, PASSWORD)


def test_truncated_zip_is_rejected(tmp_path: Path) -> None:
    path = write_aes_zip(tmp_path / "whole.zip", {"a.exe": b"MZ" * 100})
    path.write_bytes(path.read_bytes()[:-30])

    with pytest.raises(ArchiveError, match="not a valid zip"):
        read_archive(path, PASSWORD)


def test_corrupt_central_directory_is_rejected(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "corrupt.zip", {"a.exe": b"MZ"})
    raw = bytearray(path.read_bytes())
    raw[raw.rfind(b"PK\x01\x02") + 1] ^= 0xFF
    path.write_bytes(raw)

    with pytest.raises(ArchiveError, match="not a valid zip"):
        read_archive(path, PASSWORD)


def test_local_header_that_disagrees_with_the_directory_is_rejected(tmp_path: Path) -> None:
    path = write_aes_zip(tmp_path / "liar.zip", {"good.exe": b"MZ"})
    path.write_bytes(path.read_bytes().replace(b"good.exe", b"evil.exe", 1))

    with pytest.raises(ArchiveError, match="not a valid zip"):
        read_archive(path, PASSWORD)


def test_central_directory_larger_than_the_file_is_rejected(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "short.zip", {"a.exe": b"MZ"})
    with_forged_central_directory_size(path, 1_000_000)

    with pytest.raises(ArchiveError, match="not a valid zip"):
        read_archive(path, PASSWORD)


def test_member_offset_before_the_start_of_the_file_is_rejected(tmp_path: Path) -> None:
    path = write_aes_zip(tmp_path / "offset.zip", {"a.exe": b"MZ"})
    raw = bytearray(path.read_bytes())
    struct.pack_into("<I", raw, len(raw) - EOCD_LENGTH + 16, 1_000_000)
    path.write_bytes(raw)

    with pytest.raises(ArchiveError, match="not a valid zip"):
        read_archive(path, PASSWORD)


def test_zipcrypto_member_whose_header_runs_past_the_end_of_the_file_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runs-off.zip"
    path.write_bytes(ZIPCRYPTO_FIXTURE.read_bytes())
    raw = bytearray(path.read_bytes())
    struct.pack_into("<H", raw, LOCAL_EXTRA_LENGTH_OFFSET, 102)
    path.write_bytes(raw)

    with pytest.raises(ArchiveError, match="not a valid zip"):
        read_archive(path, PASSWORD)


def test_aes_member_with_an_unknown_key_strength_is_rejected(tmp_path: Path) -> None:
    path = write_aes_zip(tmp_path / "strength.zip", {"a.exe": b"MZ"})
    raw = bytearray(path.read_bytes())
    raw[raw.rfind(b"AE") + 2] = 66
    path.write_bytes(raw)

    with pytest.raises(ArchiveError, match="not a valid zip"):
        read_archive(path, PASSWORD)


def test_name_flagged_utf8_but_not_utf8_is_rejected(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "name.zip", {"aXb": b"MZ"})
    rewrite_bytes(path, b"aXb", b"a\xe9b")
    mark_every_entry_utf8(path)

    with pytest.raises(ArchiveError, match="not a valid zip"):
        read_archive(path, PASSWORD)


def test_name_without_the_utf8_flag_is_read_as_cp437(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "name.zip", {"aXb": b"MZ"})
    rewrite_bytes(path, b"aXb", b"a\xe9b")

    assert list(listed(path)) == ["a" + b"\xe9".decode("cp437") + "b"]


@pytest.mark.parametrize("members", [{}, {"only-a-directory/": b""}], ids=["none", "directories"])
def test_archive_without_files_is_rejected(members: dict[str, bytes], tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "empty.zip", members)

    with pytest.raises(ArchiveError, match="no files"):
        read_archive(path, PASSWORD)


def test_member_count_over_the_cap_is_rejected(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "many.zip", {f"f{i}.bin": b"x" for i in range(3)})

    with pytest.raises(ArchiveError, match="more than 2 files"):
        read_archive(path, PASSWORD, max_members=2)


def test_member_count_at_the_cap_is_accepted(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "many.zip", {f"f{i}.bin": b"x" for i in range(2)})

    assert len(read_archive(path, PASSWORD, max_members=2).members) == 2


def test_directories_do_not_count_towards_the_member_cap(tmp_path: Path) -> None:
    members = {"a/": b"", "b/": b"", "c/": b"", "a/run.exe": b"MZ"}
    path = write_plain_zip(tmp_path / "dirs.zip", members)

    assert len(read_archive(path, PASSWORD, max_members=1).members) == 1


def test_total_declared_size_over_the_cap_is_rejected(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "big.zip", {"a.bin": bytes(60), "b.bin": bytes(60)})

    with pytest.raises(ArchiveError, match="larger than 100 bytes"):
        read_archive(path, PASSWORD, max_declared_bytes=100)


def test_total_declared_size_at_the_cap_is_accepted(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "big.zip", {"a.bin": bytes(60), "b.bin": bytes(40)})

    assert len(read_archive(path, PASSWORD, max_declared_bytes=100).members) == 2


def test_default_caps() -> None:
    assert MAX_MEMBERS == 1000
    assert MAX_DECLARED_BYTES == 2 * 1024**3
    assert MAX_CENTRAL_DIRECTORY_BYTES == 4 * 1024**2


def test_oversized_central_directory_is_rejected_before_the_stdlib_parses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_plain_zip(tmp_path / "huge-directory.zip", {"a.exe": b"MZ"})
    with_forged_central_directory_size(path, MAX_CENTRAL_DIRECTORY_BYTES + 1)

    monkeypatch.setattr(archive.pyzipper, "AESZipFile", refuse_to_parse)

    with pytest.raises(ArchiveError, match="central directory is too large"):
        read_archive(path, PASSWORD)


def test_central_directory_size_at_the_cap_is_not_rejected_for_its_size(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "a.zip", {"a.exe": b"MZ"})

    assert len(read_archive(path, PASSWORD, max_central_directory_bytes=70).members) == 1
    with pytest.raises(ArchiveError, match="central directory is too large"):
        read_archive(path, PASSWORD, max_central_directory_bytes=1)


def append_comment(path: Path, comment: bytes) -> None:
    with zipfile.ZipFile(path, "a") as appended:
        appended.comment = comment


def test_zip_with_a_long_comment_is_read(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "comment.zip", {"a.exe": b"MZ"})
    append_comment(path, b"a long comment " * 500)

    assert list(listed(path)) == ["a.exe"]


def test_fake_end_record_in_the_comment_is_judged_like_the_stdlib_judges_it(
    tmp_path: Path,
) -> None:
    path = write_plain_zip(tmp_path / "fake.zip", {"a.exe": b"MZ"})
    append_comment(path, b"PK\x05\x06" + b"\xff" * 18)

    with pytest.raises(ArchiveError):
        read_archive(path, PASSWORD)


def test_zip_with_a_prefix_is_read(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "prefixed.zip", {"a.exe": b"MZ"})
    path.write_bytes(b"MZ self-extractor stub" * 20 + path.read_bytes())

    assert list(listed(path)) == ["a.exe"]


def test_zip64_end_records_are_read(tmp_path: Path) -> None:
    path = with_zip64_end_records(write_plain_zip(tmp_path / "z64.zip", {"a.exe": b"MZ"}))

    assert list(listed(path)) == ["a.exe"]


def test_oversized_zip64_central_directory_is_rejected_before_the_stdlib_parses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_plain_zip(tmp_path / "z64.zip", {"a.exe": b"MZ"})
    with_zip64_end_records(path, central_directory_size=MAX_CENTRAL_DIRECTORY_BYTES + 1)
    monkeypatch.setattr(archive.pyzipper, "AESZipFile", refuse_to_parse)

    with pytest.raises(ArchiveError, match="central directory is too large"):
        read_archive(path, PASSWORD)


@pytest.mark.parametrize(
    "name",
    [
        "../x",
        "..",
        "a/../../b",
        "a/../b",
        "..\\x",
        "a\\..\\..\\b",
        "C:\\x",
        "c:/x",
        "/etc/x",
        "\\windows\\x",
        "\\\\server\\share\\x",
    ],
)
def test_names_that_escape_the_directory_are_unsafe(name: str, tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "unsafe.zip", {name: b"MZ"})

    assert listed(path)[name].unsafe is True


@pytest.mark.parametrize("name", ["run.exe", "dir/run.exe", "dir/..x", "a..b", "dir\\run.exe"])
def test_ordinary_names_are_safe(name: str, tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "safe.zip", {name: b"MZ"})

    assert listed(path)[name].unsafe is False


def test_name_with_a_nul_byte_is_unsafe_and_shown_as_the_stdlib_truncates_it(
    tmp_path: Path,
) -> None:
    # zipfile cuts the name at the NUL; only ZipInfo.orig_filename still has the whole name.
    path = write_plain_zip(tmp_path / "nul.zip", {"okXrest": b"MZ"})
    rewrite_bytes(path, b"okXrest", b"ok\x00rest")

    members = listed(path)

    assert list(members) == ["ok"]
    assert members["ok"].unsafe is True


@pytest.mark.parametrize(
    "name", ["a,b.exe", ",", " lead.exe", "trail.exe ", "tab.exe\t", "dir/a,b.exe"]
)
def test_names_the_option_string_cannot_carry_are_unsupported(name: str, tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "unsupported.zip", {name: b"MZ"})

    assert listed(path)[name].unsupported is True


@pytest.mark.parametrize(
    "name", ["run.exe", "my sample (1).exe", "dir/inner name.exe", "dir/ spaced.exe", "a;b.exe"]
)
def test_names_without_commas_or_edge_whitespace_are_supported(name: str, tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "supported.zip", {name: b"MZ"})

    assert listed(path)[name].unsupported is False


def test_unsafe_and_unsupported_are_independent(tmp_path: Path) -> None:
    path = write_plain_zip(tmp_path / "both.zip", {"../a,b": b"MZ", "../fine": b"MZ"})

    members = listed(path)

    assert (members["../a,b"].unsafe, members["../a,b"].unsupported) == (True, True)
    assert (members["../fine"].unsafe, members["../fine"].unsupported) == (True, False)


def test_duplicate_names_are_rejected_because_the_entry_would_be_ambiguous(
    tmp_path: Path,
) -> None:
    path = write_plain_zip(tmp_path / "dup.zip", {"a.exe": b"MZ", "bXexe": b"MZ"})
    rewrite_bytes(path, b"bXexe", b"a.exe")

    with pytest.raises(ArchiveError, match="more than once"):
        read_archive(path, PASSWORD)


def test_the_password_is_in_no_error_message_or_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "hunter2-top-secret"  # noqa: S105
    garbage = tmp_path / "garbage.zip"
    garbage.write_bytes(b"not a zip" * 20)
    liar = write_aes_zip(tmp_path / "liar.zip", {"good.exe": b"MZ"}, password=secret)
    liar.write_bytes(liar.read_bytes().replace(b"good.exe", b"evil.exe", 1))
    fine = write_aes_zip(tmp_path / "fine.zip", {"a.exe": b"MZ"}, password=secret)

    with caplog.at_level(logging.DEBUG):
        for bad in (garbage, liar):
            with pytest.raises(ArchiveError) as raised:
                read_archive(bad, secret)
            assert secret not in str(raised.value)
            assert secret not in repr(raised.value)
        read_archive(fine, secret)
        read_archive(fine, secret + "-wrong")

    assert secret not in caplog.text
