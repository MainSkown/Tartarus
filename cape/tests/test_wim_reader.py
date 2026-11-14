"""The Windows profile's reader of install.wim and install.esd, as run inside the child."""

import importlib.util
import io
from pathlib import Path

import pytest
from fixtures.iso_images import (
    HEADER_FLAG_COMPRESSION,
    HEADER_FLAG_LZX,
    RESOURCE_FLAG_COMPRESSED,
    RESOURCE_FLAG_METADATA,
    WINDOWS_HOME,
    WINDOWS_PRO,
    wim_file,
    windows_image_xml,
)

READER_PATH = Path(__file__).parents[2] / "guest" / "profiles" / "windows" / "wim_reader.py"


def load_reader():
    spec = importlib.util.spec_from_file_location("windows_wim_reader", READER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reader = load_reader()


class FakeImage:
    """The part of the child's `IsoImage` the reader uses: `open(*path)`, or None, and `exists`."""

    def __init__(self, **files: bytes) -> None:
        self.files = {tuple(name.split("/")): data for name, data in files.items()}

    def open(self, *path: str) -> io.BytesIO | None:
        data = self.files.get(path)
        return None if data is None else io.BytesIO(data)

    def exists(self, *path: str) -> bool:
        return path in self.files


def image_with(wim: bytes, name: str = "install.wim") -> FakeImage:
    return FakeImage(**{f"sources/{name}": wim})


GOOD_XML = windows_image_xml(WINDOWS_PRO, WINDOWS_HOME)


class TestWhichFileIsRead:
    def test_install_wim_gives_the_images_of_its_xml(self):
        found = reader.read(image_with(wim_file(GOOD_XML)))

        assert found["file"] == "install.wim"
        assert found["compression"] == "LZX"
        assert [image["index"] for image in found["images"]] == [1, 2]
        assert "failure" not in found

    def test_install_esd_is_read_when_there_is_no_wim(self):
        found = reader.read(image_with(wim_file(GOOD_XML), "install.esd"))

        assert found["file"] == "install.esd"
        assert len(found["images"]) == 2

    def test_install_wim_is_preferred_over_install_esd(self):
        wim = wim_file(windows_image_xml(WINDOWS_PRO))
        esd = wim_file(GOOD_XML)

        found = reader.read(FakeImage(**{"sources/install.wim": wim, "sources/install.esd": esd}))

        assert found["file"] == "install.wim"
        assert len(found["images"]) == 1

    def test_a_disc_without_sources_has_no_install_image_and_no_boot_image(self):
        assert reader.read(FakeImage(**{"boot/grub.cfg": b"x"})) == {
            "file": None,
            "boot_wim": False,
        }

    def test_a_boot_image_alone_is_reported_as_such(self):
        assert reader.read(FakeImage(**{"sources/boot.wim": b"x"})) == {
            "file": None,
            "boot_wim": True,
        }


class TestTheImages:
    def test_every_field_the_inspector_lists_is_taken_from_the_xml(self):
        (pro, home) = reader.read(image_with(wim_file(GOOD_XML)))["images"]

        assert pro == {
            "index": 1,
            "name": "Windows 11 Pro",
            "edition_id": "Professional",
            "arch": "amd64",
            "languages": ["pl-PL"],
            "default_language": "pl-PL",
            "build": 26200,
            "version": "10.0.26200",
            "installation_type": "Client",
        }
        assert home["edition_id"] == "Core"

    @pytest.mark.parametrize(
        ("code", "name"),
        [(0, "x86"), (5, "arm"), (6, "ia64"), (9, "amd64"), (12, "arm64"), (14, "unknown (14)")],
    )
    def test_the_architecture_number_is_named_as_the_answer_file_spells_it(self, code, name):
        xml = windows_image_xml({**WINDOWS_PRO, "arch": code})

        assert reader.read(image_with(wim_file(xml)))["images"][0]["arch"] == name

    def test_several_languages_are_listed_in_order(self):
        xml = windows_image_xml(
            {**WINDOWS_PRO, "languages": ["en-US", "de-DE"], "default_language": "en-US"}
        )

        (image,) = reader.read(image_with(wim_file(xml)))["images"]

        assert image["languages"] == ["en-US", "de-DE"]
        assert image["default_language"] == "en-US"

    def test_an_image_without_windows_metadata_has_none_for_it(self):
        xml = '<WIM><IMAGE INDEX="1"><NAME>backup</NAME></IMAGE></WIM>'

        (image,) = reader.read(image_with(wim_file(xml)))["images"]

        assert image == {
            "index": 1,
            "name": "backup",
            "edition_id": None,
            "arch": None,
            "languages": [],
            "default_language": None,
            "build": None,
            "version": None,
            "installation_type": None,
        }

    def test_the_xml_may_come_without_a_byte_order_mark(self):
        xml = GOOD_XML.encode("utf-16-le")

        assert len(reader.read(image_with(wim_file(xml)))["images"]) == 2

    def test_a_wim_without_images_lists_none(self):
        assert reader.read(image_with(wim_file("<WIM></WIM>")))["images"] == []


class TestCompression:
    @pytest.mark.parametrize(
        ("flags", "name"),
        [
            (0, "None"),
            (HEADER_FLAG_COMPRESSION | 0x20000, "XPRESS"),
            (HEADER_FLAG_COMPRESSION | 0x200000, "XPRESS"),
            (HEADER_FLAG_COMPRESSION | HEADER_FLAG_LZX, "LZX"),
            (HEADER_FLAG_COMPRESSION | 0x80000, "LZMS"),
            (HEADER_FLAG_COMPRESSION | HEADER_FLAG_LZX | 0x80, "LZX"),
        ],
    )
    def test_it_is_named_from_the_header_flags(self, flags, name):
        found = reader.read(image_with(wim_file(GOOD_XML, header_flags=flags)))

        assert found["compression"] == name


def failure_of(wim: bytes) -> str:
    found = reader.read(image_with(wim))
    assert found["file"] == "install.wim"
    assert "images" not in found
    return found["failure"]


class TestWhatIsRefused:
    def test_a_file_that_is_not_a_wim(self):
        assert failure_of(b"PK\x03\x04" + b"\0" * 400) == "not_a_wim"

    def test_a_file_too_short_to_have_a_magic_number(self):
        assert failure_of(b"MS") == "not_a_wim"
        assert failure_of(b"") == "not_a_wim"

    def test_a_header_that_says_it_has_another_size(self):
        wim = bytearray(wim_file(GOOD_XML))
        wim[8:12] = (100).to_bytes(4, "little")

        assert failure_of(bytes(wim)) == "not_a_wim"

    def test_a_wim_cut_inside_its_header_is_incomplete(self):
        assert failure_of(wim_file(GOOD_XML)[:100]) == "incomplete"

    def test_an_xml_offset_beyond_the_end_of_the_file_is_incomplete(self):
        assert failure_of(wim_file(GOOD_XML, xml_offset=10**9)) == "incomplete"

    def test_an_xml_resource_cut_off_by_the_end_of_the_file_is_incomplete(self):
        assert failure_of(wim_file(GOOD_XML)[:-20]) == "incomplete"

    def test_an_offset_that_would_overflow_is_incomplete(self):
        assert failure_of(wim_file(GOOD_XML, xml_offset=2**64 - 1)) == "incomplete"

    def test_an_xml_resource_inside_the_header_is_damaged(self):
        assert failure_of(wim_file(GOOD_XML, xml_offset=100)) == "damaged"

    def test_an_xml_resource_bigger_than_the_cap_is_damaged_without_reading_it(self):
        size = reader.MAX_XML_BYTES + 2
        assert failure_of(wim_file(GOOD_XML, stored_size=size, original_size=size)) == "damaged"

    def test_an_xml_resource_of_exactly_the_cap_is_still_read(self):
        xml = GOOD_XML + " " * ((reader.MAX_XML_BYTES - 2) // 2 - len(GOOD_XML))
        wim = wim_file(xml)

        assert len(wim) - 208 == reader.MAX_XML_BYTES
        assert len(reader.read(image_with(wim))["images"]) == 2

    def test_an_empty_xml_resource_is_damaged(self):
        assert failure_of(wim_file(b"")) == "damaged"

    def test_an_xml_resource_whose_sizes_disagree_is_damaged(self):
        assert failure_of(wim_file(GOOD_XML, original_size=5)) == "damaged"

    @pytest.mark.parametrize("flag", [RESOURCE_FLAG_COMPRESSED, 0x10])
    def test_a_compressed_or_solid_xml_resource_is_unreadable_not_guessed_at(self, flag):
        wim = wim_file(GOOD_XML, resource_flags=RESOURCE_FLAG_METADATA | flag)

        assert failure_of(wim) == "unreadable"

    def test_a_doctype_is_refused(self):
        xml = '<!DOCTYPE WIM [<!ENTITY a "b">]><WIM><IMAGE INDEX="1"></IMAGE></WIM>'

        assert failure_of(wim_file(xml)) == "damaged"

    def test_an_entity_declaration_is_refused_in_any_case(self):
        assert failure_of(wim_file('<WIM><!entity a "b"></WIM>')) == "damaged"

    def test_xml_that_is_not_well_formed_is_damaged(self):
        assert failure_of(wim_file("<WIM><IMAGE INDEX=")) == "damaged"

    def test_text_that_is_not_utf16_is_damaged(self):
        assert failure_of(wim_file(b"\xff\xfe\x00\xd8")) == "damaged"

    def test_an_odd_number_of_bytes_is_damaged(self):
        assert failure_of(wim_file(b"abc")) == "damaged"

    @pytest.mark.parametrize(
        "xml",
        [
            "<WIM><IMAGE><NAME>no index</NAME></IMAGE></WIM>",
            '<WIM><IMAGE INDEX="one"></IMAGE></WIM>',
            '<WIM><IMAGE INDEX="1"><WINDOWS><VERSION><BUILD>x</BUILD></VERSION></WINDOWS>'
            "</IMAGE></WIM>",
            '<WIM><IMAGE INDEX="1"><WINDOWS><ARCH>x</ARCH></WINDOWS></IMAGE></WIM>',
        ],
    )
    def test_numbers_that_are_not_numbers_are_damaged(self, xml):
        assert failure_of(wim_file(xml)) == "damaged"
