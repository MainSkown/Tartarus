"""The Windows answer file renderer (guest/profiles/windows/steps/lib/render_unattend.py)."""

import json
import os
import re
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fixtures.guest_samples import make_guest

REPO = Path(__file__).parents[2]
PROFILE_DIR = REPO / "guest" / "profiles" / "windows"
LIB_DIR = PROFILE_DIR / "steps" / "lib"
SCRIPT = LIB_DIR / "render_unattend.py"
sys.path.insert(0, str(LIB_DIR))

import render_unattend  # noqa: E402

NAMESPACE = {"u": "urn:schemas-microsoft-com:unattend"}
HOSTILE = "a<b>&\"c'<!--]]></Value><Evil/>$x ${GUEST_IP}"
OPTIONS = {
    "defender": True,
    "decoys": False,
    "sysmon": True,
    "key": "",
    "keyboard": "Polish (Programmers)",
}


def guest_record(**changes) -> dict:
    record = make_guest("alpha", ip="192.168.150.10").to_dict()
    record["options"] = {**OPTIONS, **changes.pop("options", {})}
    record["identity"] = {**record["identity"], **changes.pop("identity", {})}
    record["media"] = {**record["media"], **changes.pop("media", {})}
    return {**record, **changes}


def load_json(name: str) -> dict:
    return json.loads((PROFILE_DIR / name).read_text(encoding="utf-8"))


def rendered(**changes) -> str:
    return render_unattend.render_answer_file(
        (PROFILE_DIR / "autounattend.xml.tpl").read_text(encoding="utf-8"),
        guest_record(**changes),
        load_json("names.json"),
        load_json("keyboards.json"),
    )


def parsed(**changes) -> ET.Element:
    return ET.fromstring(rendered(**changes))  # noqa: S314 - our own rendering


def texts(root: ET.Element, path: str) -> list[str | None]:
    return [element.text for element in root.findall(path, NAMESPACE)]


class TestTheParametersLandInTheDocument:
    def test_the_image_index_language_and_keyboard(self):
        root = parsed()
        assert texts(root, ".//u:MetaData/u:Value") == ["5"]
        assert set(texts(root, ".//u:UILanguage")) == {"pl-PL"}
        assert set(texts(root, ".//u:InputLocale")) == {"0415:00000415"}

    def test_the_keyboard_option_selects_the_layout_from_the_table(self):
        root = parsed(options={"keyboard": "German"})
        assert set(texts(root, ".//u:InputLocale")) == {"0407:00000407"}

    def test_the_account_computer_name_and_password(self):
        root = parsed(
            identity={"account": "Casey", "machine": "DESKTOP-Q1", "password": "Pa55word!"}
        )
        assert texts(root, ".//u:ComputerName") == ["DESKTOP-Q1"]
        assert texts(root, ".//u:FullName") == ["Casey"]
        assert texts(root, ".//u:LocalAccount/u:Name") == ["Casey"]
        assert texts(root, ".//u:AutoLogon/u:Username") == ["Casey"]
        assert texts(root, ".//u:Password/u:Value") == ["Pa55word!", "Pa55word!"]

    def test_the_names_come_from_the_names_table(self):
        names = load_json("names.json")
        text = rendered()
        assert names["first_logon_description"] in text
        assert names["cd_marker_file"] in text
        assert f'-FirewallRuleName "{names["firewall_rule"]}"' in text
        assert f'-TaskName "{names["scheduled_task"]}"' in text
        assert f'-LogName "{names["log_file"]}"' in text
        assert f'-DoneMarker "{names["done_marker"]}"' in text

    def test_the_work_folder_and_address_are_the_guests(self):
        text = rendered(work_dir="C:\\ProgramData\\qwertyui", ip="192.168.150.11")
        assert '-WorkDir "C:\\ProgramData\\qwertyui"' in text
        assert "-GuestIp 192.168.150.11" in text

    def test_options_become_powershell_booleans(self):
        text = rendered(options={"defender": False, "decoys": True, "sysmon": False})
        assert "-Defender $false -Decoys $true -Sysmon $false" in text

    def test_nothing_is_left_unsubstituted(self):
        assert "${" not in rendered()


class TestSilentFailures:
    """Setup reports nothing about a broken answer file: it exits and WinPE reboots to the CD."""

    def test_the_document_is_well_formed_namespaced_xml(self):
        text = rendered()
        ET.fromstring(text)  # noqa: S314 - our own rendering
        assert 'xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State"' in text

    def test_no_placeholder_is_left_for_setup_to_find(self):
        assert not re.search(
            r"\$\{[A-Z_]+\}", rendered(options={"key": "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"})
        )


class TestHostileValuesCannotChangeTheDocument:
    @pytest.mark.parametrize("role", ["account", "machine", "password"])
    def test_a_hostile_identity_value_stays_text(self, role):
        root = parsed(identity={role: HOSTILE})
        assert root.find(".//Evil") is None
        assert not [element for element in root.iter() if element.tag.endswith("Evil")]
        assert HOSTILE in {element.text for element in root.iter()}

    def test_the_password_is_not_expanded_as_a_template(self):
        root = parsed(identity={"password": "Pa$$w0rd${GUEST_IP}"})
        assert texts(root, ".//u:Password/u:Value") == ["Pa$$w0rd${GUEST_IP}"] * 2

    def test_a_cdata_terminator_is_escaped(self):
        text = rendered(identity={"password": "x]]>y"})
        assert "x]]>y" not in text
        assert "x]]&gt;y" in text

    def test_quotes_become_entities(self):
        assert render_unattend.xml_text("""a"b'c""") == "a&quot;b&apos;c"

    def test_a_hostile_product_key_stays_text(self):
        root = parsed(options={"key": "A</Key><Evil/>"})
        assert not [element for element in root.iter() if element.tag.endswith("Evil")]
        assert texts(root, ".//u:ProductKey/u:Key") == ["A</Key><Evil/>"]

    @pytest.mark.parametrize("bad", ["a\x00b", "a\x0bb", "a\x1fb", "a\ufffeb"])
    def test_characters_xml_cannot_hold_are_refused(self, bad):
        with pytest.raises(render_unattend.RenderError, match="cannot be written in XML"):
            rendered(identity={"password": bad})


class TestTheProductKeyElement:
    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_it_is_absent_without_a_key(self, blank):
        text = rendered(options={"key": blank})
        assert "ProductKey" not in text
        assert parsed(options={"key": blank}).findall(".//u:ProductKey", NAMESPACE) == []

    def test_it_is_present_with_the_key_and_asks_only_on_error(self):
        key = "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"
        root = parsed(options={"key": key})
        assert texts(root, ".//u:ProductKey/u:Key") == [key]
        assert texts(root, ".//u:ProductKey/u:WillShowUI") == ["OnError"]

    def test_the_document_is_well_formed_either_way(self):
        parsed(options={"key": ""})
        parsed(options={"key": "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"})


class TestARecordThatCannotBeRendered:
    def test_a_media_without_a_language(self):
        with pytest.raises(render_unattend.RenderError, match="language"):
            rendered(media={"language": None})

    def test_a_media_without_a_variant(self):
        with pytest.raises(render_unattend.RenderError, match="variant"):
            rendered(media={"variant": None})

    def test_an_unknown_keyboard_layout(self):
        with pytest.raises(render_unattend.RenderError, match="keyboard layout 'Klingon'"):
            rendered(options={"keyboard": "Klingon"})

    def test_a_missing_option(self):
        record = guest_record()
        del record["options"]["sysmon"]
        with pytest.raises(render_unattend.RenderError, match=r"options\.sysmon"):
            render_unattend.render_answer_file(
                (PROFILE_DIR / "autounattend.xml.tpl").read_text(encoding="utf-8"),
                record,
                load_json("names.json"),
                load_json("keyboards.json"),
            )

    def test_a_template_placeholder_nobody_fills(self):
        with pytest.raises(render_unattend.RenderError, match="UNKNOWN_FIELD"):
            render_unattend.render_answer_file(
                "<a>${UNKNOWN_FIELD}</a>",
                guest_record(),
                load_json("names.json"),
                load_json("keyboards.json"),
            )


class TestTheCommandLine:
    @staticmethod
    def run(tmp_path: Path, record: dict) -> subprocess.CompletedProcess[str]:
        guest_json = tmp_path / "guest.json"
        guest_json.write_text(json.dumps(record))
        environment = {
            "PATH": os.environ["PATH"],
            "TT_GUEST_JSON": str(guest_json),
            "TT_PROFILE_DIR": str(PROFILE_DIR),
        }
        return subprocess.run(  # noqa: S603
            [sys.executable, "-I", str(SCRIPT), str(tmp_path / "autounattend.xml")],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_it_writes_the_answer_file_readable_only_by_the_owner(self, tmp_path):
        result = self.run(tmp_path, guest_record())
        assert result.returncode == 0, result.stderr
        written = tmp_path / "autounattend.xml"
        ET.parse(written)  # noqa: S314 - our own rendering
        assert stat.S_IMODE(written.stat().st_mode) == 0o600

    def test_a_file_left_world_readable_by_an_earlier_attempt_is_locked_again(self, tmp_path):
        left_over = tmp_path / "autounattend.xml"
        left_over.write_text("old")
        left_over.chmod(0o644)
        assert self.run(tmp_path, guest_record()).returncode == 0
        assert stat.S_IMODE(left_over.stat().st_mode) == 0o600

    def test_it_never_prints_the_password(self, tmp_path):
        secret = "Hunter2-secret-value"  # noqa: S105
        result = self.run(tmp_path, guest_record(identity={"password": secret}))
        assert secret not in result.stdout + result.stderr

    def test_a_record_that_cannot_be_rendered_fails_with_a_message_and_no_file(self, tmp_path):
        result = self.run(tmp_path, guest_record(options={"keyboard": "Klingon"}))
        assert result.returncode == 1
        assert "keyboard layout 'Klingon'" in result.stderr
        assert not (tmp_path / "autounattend.xml").exists()


def test_the_renderer_fills_every_placeholder_of_the_real_template_but_the_key_block():
    template = (PROFILE_DIR / "autounattend.xml.tpl").read_text(encoding="utf-8")
    wanted = set(re.findall(r"\$\{([A-Z_]+)\}", template))
    filled = set(
        render_unattend.placeholder_values(
            guest_record(), load_json("names.json"), load_json("keyboards.json")
        )
    )
    assert wanted - {"PRODUCT_KEY_BLOCK"} == filled
