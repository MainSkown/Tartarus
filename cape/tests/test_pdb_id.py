"""Tests of the Windows profile's `steps/lib/pdb_id.py`: the PDB GUID and age of a kernel image.

The images are built byte by byte in fixtures/pe_images.py. Real PE files were read with it too
(pylance-service.exe, pip's launchers); the real kernel waits for the real-run proof.
"""

import struct
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fixtures.pe_images import CODEVIEW, GUID, POGO, codeview, pe_image

LIB_DIR = Path(__file__).parents[2] / "guest" / "profiles" / "windows" / "steps" / "lib"
sys.path.insert(0, str(LIB_DIR))

import pdb_id  # noqa: E402
from pdb_id import PdbId, PdbIdError, read_pdb_id  # noqa: E402


def test_the_guid_age_and_pdb_name_of_the_kernel_are_read_from_its_codeview_entry():
    assert read_pdb_id(pe_image()) == PdbId("ntkrnlmp.pdb", GUID, 1)


def test_the_guid_is_in_the_order_the_symbol_server_and_volatility_print_it():
    # Data1 to Data3 are little-endian in the file, Data4 is in order.
    raw = uuid.UUID(GUID).bytes_le
    assert raw[:4] == bytes.fromhex("DB61DE24")

    assert read_pdb_id(pe_image(entries=((CODEVIEW, codeview()),))).guid == GUID


def test_the_age_is_a_whole_number_not_hexadecimal_text():
    image = pe_image(entries=((CODEVIEW, codeview(age=26)),))

    assert read_pdb_id(image).age == 26


def test_the_pdb_name_is_the_last_part_of_the_path_in_the_file():
    image = pe_image(entries=((CODEVIEW, codeview(name=r"D:\build\obj\ntkrnlmp.pdb")),))

    assert read_pdb_id(image).name == "ntkrnlmp.pdb"


def test_a_32_bit_image_is_read_too():
    assert read_pdb_id(pe_image(pe32_plus=False)) == PdbId("ntkrnlmp.pdb", GUID, 1)


@pytest.mark.parametrize(
    ("image", "complaint"),
    [
        (b"", "not a PE"),
        (b"MZ" + b"\0" * 10, "truncated"),
        (b"\x7fELF" + b"\0" * 200, "not a PE"),
        (pe_image()[:0x7E], "truncated"),
        (pe_image()[:0x120], "truncated"),
        (pe_image()[:0x430], "truncated"),
        (pe_image(entries=((POGO, b"PGU\0"),)), "no CodeView"),
        (pe_image(entries=()), "no debug directory"),
        (pe_image(entries=((CODEVIEW, b"NB10" + b"\0" * 30),)), "no CodeView"),
        (pe_image(entries=((CODEVIEW, codeview(name="../x\\\x01.pdb")),)), "name"),
        (pe_image(debug_directory_size=0xFFFFFF), "truncated"),
    ],
    ids=[
        "empty",
        "cut-in-dos-header",
        "elf",
        "cut-before-pe-signature",
        "cut-in-optional-header",
        "cut-in-debug-directory",
        "no-codeview-entry",
        "no-debug-directory",
        "codeview-of-another-kind",
        "name-not-plain",
        "directory-larger-than-file",
    ],
)
def test_an_image_without_a_readable_pdb_id_is_an_error_that_says_what_is_wrong(image, complaint):
    with pytest.raises(PdbIdError, match=complaint):
        read_pdb_id(image)


def test_a_pe_header_that_points_outside_the_file_is_an_error_not_a_crash():
    image = bytearray(pe_image())
    struct.pack_into("<I", image, 0x3C, 0xFFFFFF)

    with pytest.raises(PdbIdError, match="truncated"):
        read_pdb_id(bytes(image))


def test_the_command_line_prints_name_guid_and_age_on_one_line(tmp_path):
    image = tmp_path / "ntoskrnl.exe"
    image.write_bytes(pe_image())

    done = subprocess.run(  # noqa: S603 - fixed argv, a script of this repository
        [sys.executable, "-I", str(LIB_DIR / "pdb_id.py"), str(image)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (done.returncode, done.stdout) == (0, f"ntkrnlmp.pdb {GUID} 1\n")


def test_the_command_line_fails_with_the_reason_on_stderr(tmp_path):
    image = tmp_path / "not-a-pe"
    image.write_bytes(b"hello")

    done = subprocess.run(  # noqa: S603 - fixed argv, a script of this repository
        [sys.executable, "-I", str(LIB_DIR / "pdb_id.py"), str(image)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 1
    assert done.stdout == ""
    assert "not a PE" in done.stderr


def test_the_module_reads_a_whole_kernel_sized_image_quickly():
    big = pe_image() + b"\0" * (13 * 1024 * 1024)

    assert pdb_id.read_pdb_id(big).guid == GUID
